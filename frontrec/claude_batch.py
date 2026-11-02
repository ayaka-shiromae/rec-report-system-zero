"""Claude Message Batches API の薄いラッパー。複数リクエストをまとめて投げ、完了まで待って custom_id → テキストで返す。"""
from __future__ import annotations

import json
import re
import sys
import time

import anthropic


def run_batch(requests: list[dict], model: str, max_tokens: int, system: str,
              poll_seconds: int = 60, timeout_minutes: int = 120) -> dict[str, str]:
    """requests: [{"custom_id": str, "user": str}, ...]  →  {custom_id: response_text}"""
    if not requests:
        return {}
    # custom_id は ^[a-zA-Z0-9_-]{1,64}$ 限定(日本語不可)なので、連番 ID に置き換えて後で戻す
    id_map = {f"r{i:03d}": r["custom_id"] for i, r in enumerate(requests)}
    client = anthropic.Anthropic()
    batch = client.messages.batches.create(requests=[{
        "custom_id": f"r{i:03d}",
        "params": {
            "model": model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": r["user"]}],
        },
    } for i, r in enumerate(requests)])
    print(f"batch created: {batch.id} ({len(requests)} requests)", flush=True)

    deadline = time.time() + timeout_minutes * 60
    while True:
        b = client.messages.batches.retrieve(batch.id)
        if b.processing_status == "ended":
            break
        if time.time() > deadline:
            raise SystemExit(f"batch {batch.id} が {timeout_minutes} 分以内に終わりませんでした")
        time.sleep(poll_seconds)

    out: dict[str, str] = {}
    for r in client.messages.batches.results(batch.id):
        key = id_map.get(r.custom_id, r.custom_id)
        if r.result.type == "succeeded":
            out[key] = "".join(c.text for c in r.result.message.content if c.type == "text")
        else:
            print(f"batch request failed: {key}: {r.result}", file=sys.stderr)
    return out


def extract_json(text: str):
    """応答から最初の JSON オブジェクトを取り出す(```json フェンス対応)。"""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = m.group(1) if m else text
    body = body[body.find("{"): body.rfind("}") + 1]
    return json.loads(body)
