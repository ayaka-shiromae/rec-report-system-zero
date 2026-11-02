"""週次: 直近 N 日のシフト別一次解析(JSON)を集約し、
  - 配布用 PDF(1 人 1 ページ、全員分 1 ファイル)
  - 詳細レポート/<名前>/YYYYMMDD_<名前>_詳細接客レポート.md
  - 管理レポート/YYYYMMDD_管理レポート.md
  - Slack へ全員分の簡易フィードバック
使い方: python -m frontrec.weekly [--dry-run] [--days N] [--end YYYY-MM-DD] [--no-slack] [--fixture DIR]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
from collections import defaultdict

from .claude_batch import run_batch
from .config import Config
from .pdf import build_html, write_pdf
from .slack import post
from .slack_bot import upload_file

PROMPT_DIR = pathlib.Path(__file__).parent / "prompts"
PERSON_PROMPT = (PROMPT_DIR / "person_weekly.md").read_text(encoding="utf-8")
ADMIN_PROMPT = (PROMPT_DIR / "admin_weekly.md").read_text(encoding="utf-8")


def load_daily(cfg: Config, since: dt.date, until: dt.date) -> list[dict]:
    """since <= シフト開始日 <= until の一次解析を読む。"""
    out = []
    for p in sorted(cfg.path_of("daily").glob("*.json")):
        m = re.match(r"(\d{4})(\d{2})(\d{2})_", p.name)
        if not m:
            continue
        d = dt.date(int(m[1]), int(m[2]), int(m[3]))
        if since <= d <= until:
            out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def split_blocks(text: str) -> tuple[str, str]:
    m = re.search(r"=== BRIEF ===\s*(.*?)\s*=== DETAIL ===\s*(.*)$", text, re.S)
    if not m:
        return "(BRIEF を抽出できませんでした。詳細レポートを確認してください)", text.strip()
    return m.group(1).strip(), m.group(2).strip()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="API を呼ばず対象とプロンプト長だけ表示")
    ap.add_argument("--days", type=int)
    ap.add_argument("--end", help="集計終了日(含む)。既定は昨日")
    ap.add_argument("--no-slack", action="store_true")
    ap.add_argument("--fixture", help="API の代わりにこのディレクトリの <custom_id>.txt を応答として使う(PDF 等のテスト用)")
    args = ap.parse_args(argv)

    cfg = Config()
    tz = cfg.tz
    today = dt.datetime.now(tz).date()
    until = dt.date.fromisoformat(args.end) if args.end else today - dt.timedelta(days=1)
    days = args.days or int(cfg.get("analysis", "weekly_days", default=7))
    since = until - dt.timedelta(days=days - 1)
    period = f"{since.isoformat()} 〜 {until.isoformat()}"
    date_tag = today.strftime("%Y%m%d")

    daily = load_daily(cfg, since, until)
    if not daily:
        print(f"{period} の一次解析がありません")
        return

    by_person: dict[str, list[dict]] = defaultdict(list)
    for d in daily:
        by_person[d["staff"]].append(d)
    ops = [{"shift": d["shift"], "staff_hidden": True, "ops_facts": d.get("ops_facts", [])}
           for d in daily if d.get("ops_facts")]

    fmt = dict(hotel=cfg.hotel_name, hotel_desc=cfg["hotel"].get("description", ""), period=period,
               today=today.isoformat())
    requests = []
    for name, items in sorted(by_person.items()):
        requests.append({"custom_id": f"person:{name}", "kind": "person",
                         "system": PERSON_PROMPT.format(staff=name, **fmt),
                         "user": f"対象スタッフ: {name}\n対象期間: {period}\n"
                                 f"(DETAIL の見出しの {{staff}} / {{period}} にはこの値を使うこと)\n\n一次解析(JSON):\n"
                                 + json.dumps(items, ensure_ascii=False, indent=1)})
    requests.append({"custom_id": "admin", "kind": "admin", "system": ADMIN_PROMPT.format(**fmt),
                     "user": f"対象期間: {period}\n\n運用上の事実(シフト別、JSON):\n"
                             + json.dumps(ops, ensure_ascii=False, indent=1)})

    if args.dry_run:
        for r in requests:
            print(f"would request: {r['custom_id']} (user {len(r['user'])} chars)")
        return

    if args.fixture:
        results = {r["custom_id"]: pathlib.Path(args.fixture, r["custom_id"].replace(":", "_") + ".txt")
                   .read_text(encoding="utf-8") for r in requests}
    else:
        # system がリクエストごとに違うので、人別とまとめて 1 バッチにしつつ system を個別に渡す
        results = _run_mixed_batch(cfg, requests)

    report_root = cfg.path_of("report")
    rc = cfg["report"]
    people: list[tuple[str, str]] = []
    for name in sorted(by_person):
        text = results.get(f"person:{name}")
        if not text:
            print(f"warning: {name} の応答なし")
            continue
        brief, detail = split_blocks(text)
        people.append((name, brief))
        d = report_root / rc["detail_dir"] / name
        d.mkdir(parents=True, exist_ok=True)
        p = d / rc["detail_file"].format(date=date_tag, name=name)
        p.write_text(detail + "\n", encoding="utf-8")
        print(f"saved: {p}")

    if admin := results.get("admin"):
        d = report_root / rc["admin_dir"]
        d.mkdir(parents=True, exist_ok=True)
        p = d / rc["admin_file"].format(date=date_tag)
        p.write_text(admin.strip() + "\n", encoding="utf-8")
        print(f"saved: {p}")

    if people:
        pdf_path = report_root / rc["distribution_pdf"].format(date=date_tag)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        write_pdf(build_html(cfg.hotel_name, period, people, rc.get("pdf_font", "Noto Sans CJK JP"),
                             today.isoformat()), str(pdf_path))
        print(f"saved: {pdf_path}")

        webhook = os.environ.get("SLACK_WEBHOOK_URL")
        if webhook and not args.no_slack:
            title = cfg["slack"]["title"].format(hotel=cfg.hotel_name, period=period)
            body = "\n\n".join(f"*▼ {n} さん*\n{b}" for n, b in people)
            status = post(webhook, f"*{title}*\n\n{body}\n\n_配布用PDF: {pdf_path}_")
            print(f"slack: {status}")

        bot_token, bot_channel = os.environ.get("SLACK_BOT_TOKEN"), os.environ.get("SLACK_CHANNEL")
        if bot_token and bot_channel and not args.no_slack:
            title = cfg["slack"]["title"].format(hotel=cfg.hotel_name, period=period)
            ok = upload_file(bot_token, bot_channel, pdf_path, title=title,
                             comment=f"{cfg.hotel_name} 接客レポート({period})の配布用PDFです。")
            print(f"slack file upload: {'ok' if ok else 'failed'}")


def _run_mixed_batch(cfg: Config, requests: list[dict]) -> dict[str, str]:
    """system がリクエストごとに異なるので、system 別にグループ化して run_batch を呼ぶ。"""
    results: dict[str, str] = {}
    # 人別は system を共通化(プロンプトキャッシュを効かせる)し、名前・期間は user 側で指定する。
    person_reqs = [r for r in requests if r["kind"] == "person"]
    admin_reqs = [r for r in requests if r["kind"] == "admin"]
    fmt_common = PERSON_PROMPT.format(staff="(user 側参照)", hotel=cfg.hotel_name,
                                      hotel_desc=cfg["hotel"].get("description", ""),
                                      period="(user 側参照)", today=dt.date.today().isoformat())
    if person_reqs:
        results.update(run_batch(person_reqs, cfg["analysis"]["model"], int(cfg["analysis"]["weekly_max_tokens"]),
                                 fmt_common, int(cfg.get("analysis", "batch_poll_seconds", default=60)),
                                 int(cfg.get("analysis", "batch_timeout_minutes", default=120))))
    if admin_reqs:
        results.update(run_batch(admin_reqs, cfg["analysis"]["model"], int(cfg["analysis"]["weekly_max_tokens"]),
                                 admin_reqs[0]["system"], int(cfg.get("analysis", "batch_poll_seconds", default=60)),
                                 int(cfg.get("analysis", "batch_timeout_minutes", default=120))))
    return results


if __name__ == "__main__":
    main()
