"""Google カレンダー(ICS)からシフト区間を作り、文字起こしの各行を担当者ごとに振り分ける。"""
from __future__ import annotations

import datetime as dt
import glob
import os
import re
import urllib.request
from dataclasses import dataclass, field

import icalendar
import recurring_ical_events

from .config import Config

LINE_RE = re.compile(r"^\[(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\]\s*(.*)$")
FILE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.txt$")


@dataclass
class Shift:
    name: str
    role: str | None
    start: dt.datetime
    end: dt.datetime
    summary: str
    coworkers: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.start:%Y%m%d_%H%M}_{self.name}"

    def overlaps(self, other: "Shift") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass
class Line:
    at: dt.datetime
    text: str


# ---------------------------------------------------------------- ICS

def fetch_ics(url: str, cache: str | os.PathLike) -> bytes:
    """ICS を取得。失敗したらキャッシュを返す(Wi-Fi 切れ対策)。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "frontrec/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        with open(cache, "wb") as f:
            f.write(data)
        return data
    except Exception as e:  # noqa: BLE001
        if os.path.exists(cache):
            print(f"warning: ICS 取得失敗 ({e}); キャッシュを使用")
            with open(cache, "rb") as f:
                return f.read()
        raise


def parse_shifts(ics: bytes, window_start: dt.datetime, window_end: dt.datetime, cfg: Config) -> list[Shift]:
    """期間内のシフトを返す。終了時刻の無い予定は前後のシフトから推定する。"""
    tz = cfg.tz
    pat = re.compile(cfg["calendar"]["summary_pattern"])
    front_roles = [r.lower() for r in (cfg.get("calendar", "front_roles", default=[]) or [])]
    min_h = float(cfg.get("calendar", "shift_min_hours", default=6))
    max_h = float(cfg.get("calendar", "shift_max_hours", default=10))

    cal = icalendar.Calendar.from_ical(ics)
    # 推定のために窓を前後 1 日広げて読む
    q_start = (window_start - dt.timedelta(days=1)).astimezone(tz)
    q_end = (window_end + dt.timedelta(days=1)).astimezone(tz)
    events = recurring_ical_events.of(cal).between(q_start, q_end)

    raw: list[tuple[str, str | None, dt.datetime, dt.datetime | None, str]] = []
    for ev in events:
        summary = str(ev.get("SUMMARY", "")).strip()
        m = pat.match(summary)
        if not m:
            continue
        name, role = m.group("name"), m.group("role")
        if role and front_roles and role.strip().lower() not in front_roles:
            continue
        start = _as_dt(ev["DTSTART"].dt, tz)
        if start is None:  # 終日予定は対象外
            continue
        end = _as_dt(ev["DTEND"].dt, tz) if "DTEND" in ev else None
        if end is not None and (end - start) <= dt.timedelta(hours=1):
            end = None  # Google の既定 1 時間はダミー扱い
        raw.append((cfg.canonical_name(name), role, start, end, summary))

    raw.sort(key=lambda r: r[2])
    starts = [r[2] for r in raw]

    shifts: list[Shift] = []
    for name, role, start, end, summary in raw:
        if end is None:
            earliest = start + dt.timedelta(hours=min_h)
            cap = start + dt.timedelta(hours=max_h)
            nxt = next((s for s in starts if s >= earliest), None)
            end = min(nxt, cap) if nxt else cap
        shifts.append(Shift(name, role, start, end, summary))

    for s in shifts:
        s.coworkers = sorted({o.name for o in shifts if o is not s and s.overlaps(o) and o.name != s.name})

    return [s for s in shifts if s.end > window_start and s.start < window_end]


def _as_dt(v, tz) -> dt.datetime | None:
    if isinstance(v, dt.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=tz)
        return v.astimezone(tz)
    return None  # date のみ(終日)


# ---------------------------------------------------------------- 文字起こし

def load_lines(cfg: Config, start: dt.datetime, end: dt.datetime) -> list[Line]:
    """期間に重なる文字起こしファイルを読み、各行に絶対時刻を付ける。"""
    tz = cfg.tz
    out: list[Line] = []
    for path in sorted(glob.glob(str(cfg.path_of("text") / "*.txt"))):
        m = FILE_RE.match(os.path.basename(path))
        if not m:
            continue
        y, mo, d, h, mi, s = map(int, m.groups())
        f_start = dt.datetime(y, mo, d, h, mi, s, tzinfo=tz)
        # 1 ファイルは最大 1 時間 + 余裕
        if f_start > end or f_start + dt.timedelta(hours=1, minutes=5) < start:
            continue
        with open(path, encoding="utf-8") as f:
            for ln in f:
                lm = LINE_RE.match(ln.rstrip("\n"))
                if not lm:
                    continue
                at = f_start + dt.timedelta(seconds=float(lm.group(1)))
                if start <= at < end:
                    out.append(Line(at, lm.group(3).strip()))
    out.sort(key=lambda l: l.at)
    return out


def assign(lines: list[Line], shifts: list[Shift]) -> dict[str, list[Line]]:
    """各行を、その時刻に在席している全シフトへ振り分ける(重複在席なら両方へ)。"""
    buckets: dict[str, list[Line]] = {s.key: [] for s in shifts}
    for ln in lines:
        for s in shifts:
            if s.start <= ln.at < s.end:
                buckets[s.key].append(ln)
    return buckets


def render_shift_file(shift: Shift, lines: list[Line], cfg: Config) -> str:
    head = [
        f"# {cfg.hotel_name} フロント文字起こし(シフト単位)",
        f"担当: {shift.name}" + (f"  役割: {shift.role}" if shift.role else ""),
        f"シフト: {shift.start:%Y-%m-%d %H:%M} 〜 {shift.end:%Y-%m-%d %H:%M}",
        f"同時在席: {', '.join(shift.coworkers) if shift.coworkers else 'なし'}",
        f"行数: {len(lines)}",
        "",
    ]
    body = [f"[{l.at:%m/%d %H:%M:%S}] {l.text}" for l in lines]
    return "\n".join(head + body) + "\n"


def build_shift_files(cfg: Config, shifts: list[Shift], window_start: dt.datetime, window_end: dt.datetime,
                      overwrite: bool = False) -> list[tuple[Shift, str]]:
    """シフトファイルを書き出し、(shift, path) を返す。既存はスキップ(overwrite=True で上書き)。"""
    out_dir = cfg.path_of("shifts")
    lines = load_lines(cfg, window_start, window_end)
    buckets = assign(lines, shifts)
    written = []
    for s in shifts:
        path = out_dir / f"{s.key}.txt"
        if path.exists() and not overwrite:
            written.append((s, str(path)))
            continue
        tmp = path.with_suffix(".tmp")
        tmp.write_text(render_shift_file(s, buckets[s.key], cfg), encoding="utf-8")
        os.replace(tmp, path)
        written.append((s, str(path)))
    return written
