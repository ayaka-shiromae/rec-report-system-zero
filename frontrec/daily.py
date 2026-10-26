"""毎晩: 終了済みシフトを切り出し、Claude(Batch)で一次解析して /var/rec/daily/<shift>.json に保存する。
使い方: python -m frontrec.daily [--dry-run] [--days N] [--force]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib

from .claude_batch import extract_json, run_batch
from .config import Config, env
from .masking import mask
from .shifts import Shift, build_shift_files, fetch_ics, parse_shifts

PROMPT = (pathlib.Path(__file__).parent / "prompts" / "shift_analysis.md").read_text(encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="API を呼ばず、対象シフトとプロンプトだけ出す")
    ap.add_argument("--days", type=int, help="遡る日数(既定: config の daily_lookback_days)")
    ap.add_argument("--force", action="store_true", help="解析済みでもやり直す")
    args = ap.parse_args(argv)

    cfg = Config()
    tz = cfg.tz
    now = dt.datetime.now(tz)
    days = args.days or int(cfg.get("analysis", "daily_lookback_days", default=3))
    settle = dt.timedelta(minutes=int(cfg.get("analysis", "shift_settle_minutes", default=90)))
    window_start = now - dt.timedelta(days=days)

    ics = fetch_ics(env("CALENDAR_ICS_URL"), cfg.path_of("state") / "calendar.ics")
    shifts = parse_shifts(ics, window_start, now, cfg)
    done_shifts = [s for s in shifts if s.end + settle <= now]
    if not done_shifts:
        print("終了済みシフトなし")
        return

    files = build_shift_files(cfg, done_shifts, window_start, now)
    daily_dir = cfg.path_of("daily")

    requests, meta = [], {}
    for shift, path in files:
        out = daily_dir / f"{shift.key}.json"
        if out.exists() and not args.force:
            continue
        text = pathlib.Path(path).read_text(encoding="utf-8")
        body = text.split("\n\n", 1)[1] if "\n\n" in text else ""
        if not body.strip():
            _write_empty(out, shift, "文字起こしが空(録音なし or 無音)")
            print(f"skip(empty): {shift.key}")
            continue
        requests.append({"custom_id": shift.key, "user": "以下がこのシフトの文字起こしです。\n\n" + mask(text)})
        meta[shift.key] = shift

    if not requests:
        print("新規に解析するシフトなし")
        return

    if args.dry_run:
        for r in requests:
            print(f"would analyze: {r['custom_id']} ({len(r['user'])} chars)")
        return

    # system はシフトごとに変わる変数を含むのでリクエスト側に埋めるが、Batch の system は共通にしたい。
    # → 変数部分は user 側に入れ、system は固定にする(キャッシュが効く)。
    system = PROMPT.format(hotel=cfg.hotel_name, hotel_desc=cfg["hotel"].get("description", ""),
                           shift_key="(user 側参照)", staff="(user 側参照)", coworkers="[]")
    for r in requests:
        s = meta[r["custom_id"]]
        r["user"] = (f"shift: {s.key}\nstaff: {s.name}\ncoworkers: {json.dumps(s.coworkers, ensure_ascii=False)}\n"
                     f"JSON の shift/staff/coworkers にはこの値をそのまま入れること。\n\n" + r["user"])

    results = run_batch(requests, cfg["analysis"]["model"], int(cfg["analysis"]["daily_max_tokens"]), system,
                        int(cfg.get("analysis", "batch_poll_seconds", default=60)),
                        int(cfg.get("analysis", "batch_timeout_minutes", default=120)))

    for key, text in results.items():
        out = daily_dir / f"{key}.json"
        try:
            data = extract_json(text)
        except Exception as e:  # noqa: BLE001
            print(f"JSON 解析失敗 {key}: {e}; 生テキストを保存")
            (daily_dir / f"{key}.raw.txt").write_text(text, encoding="utf-8")
            continue
        s = meta[key]
        data.setdefault("shift", key)
        data["staff"] = s.name
        data["coworkers"] = s.coworkers
        data["shift_start"], data["shift_end"] = s.start.isoformat(), s.end.isoformat()
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, out)
        print(f"saved: {out}")


def _write_empty(out: pathlib.Path, shift: Shift, reason: str):
    out.write_text(json.dumps({
        "shift": shift.key, "staff": shift.name, "coworkers": shift.coworkers,
        "shift_start": shift.start.isoformat(), "shift_end": shift.end.isoformat(),
        "interactions": [], "good_points": [], "improvement_points": [], "suggested_phrases": [],
        "ops_facts": [], "transcript_quality": reason, "customer_interactions_count": 0,
    }, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
