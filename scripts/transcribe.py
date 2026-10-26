#!/usr/bin/env python3
"""書き終わった録音 WAV を faster-whisper で文字起こしして /var/rec/text に保存する(10 分 timer から呼ばれる)。
行形式: [開始秒-終了秒] テキスト   ※ frontrec.shifts がこの形式を読む
"""
import fcntl
import glob
import os
import sys
import time

import yaml

CFG = yaml.safe_load(open(os.environ.get("FRONTREC_CONFIG", os.path.join(os.path.dirname(__file__), "..", "config.yaml")), encoding="utf-8"))
RAW = CFG.get("paths", {}).get("raw", "/var/rec/raw")
TEXT = CFG["paths"]["text"]
MODEL = CFG.get("transcribe", {}).get("model", "small")
LOCK = "/tmp/transcribe.lock"

lock = open(LOCK, "w")
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(0)  # 前回の処理がまだ動いている

now = time.time()
todo = []
for wav in sorted(glob.glob(f"{RAW}/*.wav")):
    base = os.path.splitext(os.path.basename(wav))[0]
    out = f"{TEXT}/{base}.txt"
    if now - os.path.getmtime(wav) < 120 or os.path.exists(out):
        continue
    todo.append((wav, out))

if not todo:
    sys.exit(0)

from faster_whisper import WhisperModel  # noqa: E402  (重いので必要なときだけ)

model = WhisperModel(MODEL, device="cpu", compute_type="int8")
os.makedirs(TEXT, exist_ok=True)
for wav, out in todo:
    segments, _ = model.transcribe(wav, language="ja", vad_filter=True, beam_size=5)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for s in segments:
            f.write(f"[{s.start:07.1f}-{s.end:07.1f}] {s.text.strip()}\n")
    os.replace(tmp, out)
    print(f"done: {out}")
