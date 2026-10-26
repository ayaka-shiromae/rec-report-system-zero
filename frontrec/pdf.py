"""配布用 PDF: 1 人 1 ページ、全員分を 1 ファイルに。印刷してロッカーに入れる前提。"""
from __future__ import annotations

import html

CSS = """
@page {{ size: A4; margin: 22mm 20mm; }}
body {{ font-family: "{font}", "Noto Sans CJK JP", "Noto Sans JP", sans-serif; color: #222; font-size: 11.5pt; line-height: 1.75; }}
.page {{ page-break-after: always; }}
.page:last-child {{ page-break-after: auto; }}
.hotel {{ font-size: 9.5pt; color: #666; letter-spacing: .08em; }}
h1 {{ font-size: 22pt; margin: 2mm 0 1mm; font-weight: 700; }}
.period {{ font-size: 10.5pt; color: #444; margin-bottom: 8mm; padding-bottom: 3mm; border-bottom: 1.2px solid #222; }}
h2 {{ font-size: 12.5pt; margin: 7mm 0 2mm; padding-left: 3mm; border-left: 4px solid #222; }}
h2.good {{ border-color: #2e7d32; }}
h2.bad {{ border-color: #c62828; }}
h2.how {{ border-color: #1565c0; }}
p {{ margin: 0 0 1.5mm 3mm; white-space: pre-wrap; }}
.foot {{ position: fixed; bottom: 10mm; left: 20mm; right: 20mm; font-size: 8.5pt; color: #888; border-top: .6px solid #ccc; padding-top: 2mm; }}
"""

SECTIONS = [("よかったこと", "good"), ("わるかったこと", "bad"), ("改善のしかた", "how")]


def parse_brief(brief: str) -> dict[str, str]:
    """'よかったこと: ...' 形式のテキストを 3 セクションに分ける。"""
    out: dict[str, str] = {k: "" for k, _ in SECTIONS}
    cur = None
    for raw in brief.splitlines():
        line = raw.strip()
        if not line:
            continue
        hit = next((k for k, _ in SECTIONS if line.startswith(k)), None)
        if hit:
            cur = hit
            rest = line[len(hit):].lstrip(":： ")
            out[cur] = rest
        elif cur:
            out[cur] = (out[cur] + "\n" + line).strip()
    return out


def build_html(hotel: str, period: str, people: list[tuple[str, str]], font: str, today: str) -> str:
    """people: [(名前, brief テキスト), ...]"""
    pages = []
    for name, brief in people:
        sec = parse_brief(brief)
        body = "".join(
            f'<h2 class="{cls}">{k}</h2><p>{html.escape(sec[k] or "—")}</p>' for k, cls in SECTIONS
        )
        pages.append(
            f'<section class="page"><div class="hotel">{html.escape(hotel)} フロント 接客フィードバック</div>'
            f'<h1>{html.escape(name)} さん</h1><div class="period">対象期間: {html.escape(period)}</div>{body}</section>'
        )
    foot = f'<div class="foot">{html.escape(hotel)} / 作成 {today} / 録音の自動文字起こしをもとに作成しています。聞き取り誤りが含まれる場合があります。</div>'
    return f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>{CSS.format(font=font)}</style></head><body>{foot}{"".join(pages)}</body></html>'


def write_pdf(html_str: str, out_path: str) -> None:
    from weasyprint import HTML  # 重いので遅延 import
    HTML(string=html_str).write_pdf(out_path)
