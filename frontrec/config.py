import os
import pathlib
from zoneinfo import ZoneInfo

import yaml

DEFAULT_CONFIG = pathlib.Path(__file__).resolve().parent.parent / "config.yaml"


class Config:
    def __init__(self, path: str | os.PathLike | None = None):
        path = pathlib.Path(path or os.environ.get("FRONTREC_CONFIG") or DEFAULT_CONFIG)
        with open(path, encoding="utf-8") as f:
            self.raw = yaml.safe_load(f)
        self.path = path

    def __getitem__(self, key):
        return self.raw[key]

    def get(self, *keys, default=None):
        cur = self.raw
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.get("timezone", default="Asia/Tokyo"))

    def path_of(self, name: str) -> pathlib.Path:
        p = pathlib.Path(self["paths"][name])
        p.mkdir(parents=True, exist_ok=True)
        return p

    def canonical_name(self, name: str) -> str:
        return (self.get("staff", "aliases", default={}) or {}).get(name, name)

    @property
    def hotel_name(self) -> str:
        return self["hotel"]["name"]


def env(name: str, required: bool = True) -> str | None:
    v = os.environ.get(name)
    if required and not v:
        raise SystemExit(f"環境変数 {name} が未設定です(/etc/rec/env を確認)")
    return v
