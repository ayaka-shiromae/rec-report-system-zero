import json
import urllib.request


def post(webhook: str, text: str) -> int:
    """Slack Incoming Webhook に 1 投稿。長文は Slack の上限(約 40,000 字)で切る。"""
    if len(text) > 39000:
        text = text[:39000] + "\n…(長いため省略)"
    req = urllib.request.Request(webhook, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status
