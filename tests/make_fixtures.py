"""テスト用の ICS と文字起こしを生成する(カレンダーのスクショ 10/26〜11/1 を再現)。
使い方: python tests/make_fixtures.py <出力ディレクトリ>
"""
import datetime as dt
import pathlib
import random
import sys
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tokyo")
WEEK = {
    "20261026": [("01:00", "山本 (フロント)"), ("09:00", "伊東"), ("17:00", "辻 (フロント)")],
    "20261027": [("01:00", "坂本 (フロント)"), ("09:00", "伊東"), ("17:00", "川上")],
    "20261028": [("01:00", "野呂瀬 (フロント)"), ("09:00", "伊東"), ("17:00", "川上")],
    "20261029": [("01:00", "山本 (フロント)"), ("09:00", "辻 (フロント)"), ("17:00", "川上")],
    "20261030": [("01:00", "坂本 (フロント)"), ("09:00", "川畑"), ("17:00", "川上"), ("20:30", "辻 (フロント)")],
    "20261031": [("01:00", "田口 (フロント)"), ("09:00", "川畑"), ("17:00", "坂本 (フロント)")],
    "20261101": [("01:00", "田口 (フロント)"), ("09:00", "川畑"), ("17:00", "辻 (フロント)")],
}
SAMPLE = [
    "いらっしゃいませ。ご休憩ですか、ご宿泊ですか。",
    "3時間ですと3690円になります。",
    "申し訳ございません、ただいま宿泊の受付人数が超えておりまして。",
    "お部屋は405号室になります。鍵をお渡しします。",
    "延長料金が30分ごとに690円かかります。",
    "シャンプーが切れてて、補充お願いしていいですか。",
    "6階の水漏れまだ直ってないんで、603は止めといてください。",
    "ありがとうございました。お気をつけて。",
]


def main(out: pathlib.Path):
    out.mkdir(parents=True, exist_ok=True)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//frontrec//JP"]
    for day, evs in WEEK.items():
        for hm, summary in evs:
            start = dt.datetime.strptime(f"{day} {hm}", "%Y%m%d %H:%M").replace(tzinfo=TZ).astimezone(dt.UTC)
            end = start + dt.timedelta(hours=1)  # Google 既定の 1 時間(=終了時刻なし扱い)
            lines += ["BEGIN:VEVENT", f"UID:{day}{hm.replace(':', '')}@test",
                      f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}",
                      f"SUMMARY:{summary}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    (out / "shifts.ics").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")

    text = out / "text"
    text.mkdir(exist_ok=True)
    rnd = random.Random(1)
    t = dt.datetime(2026, 10, 26, 0, 27, 14, tzinfo=TZ)
    end = dt.datetime(2026, 10, 27, 12, 0, tzinfo=TZ)
    while t < end:
        rows = []
        for _ in range(rnd.randint(3, 8)):
            s = rnd.uniform(0, 3500)
            rows.append((s, f"[{s:07.1f}-{s + 4:07.1f}] {rnd.choice(SAMPLE)}"))
        rows.sort()
        (text / f"{t:%Y%m%d_%H%M%S}.txt").write_text("\n".join(r[1] for r in rows) + "\n", encoding="utf-8")
        t += dt.timedelta(hours=1)
    print("fixtures ->", out)


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]))
