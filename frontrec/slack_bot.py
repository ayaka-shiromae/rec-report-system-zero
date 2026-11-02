"""Slack Bot トークンでファイルを投稿する(files_upload_v2 フロー。標準ライブラリのみ)。

必要スコープ: files:write(+ 投稿先チャンネルに Bot を招待済みであること)
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.parse
import urllib.request
import uuid

API = "https://slack.com/api/"


class SlackError(RuntimeError):
    pass


def _api_form(token: str, method: str, fields: dict) -> dict:
    req = urllib.request.Request(
        API + method, data=urllib.parse.urlencode(fields).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode())
    if not res.get("ok"):
        raise SlackError(f"{method}: {res.get('error', 'unknown')}")
    return res


def _api_json(token: str, method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        API + method, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode())
    if not res.get("ok"):
        raise SlackError(f"{method}: {res.get('error', 'unknown')}")
    return res


def _multipart(filename: str, data: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = "----frontrec" + uuid.uuid4().hex
    safe = filename.replace('"', "_").replace("\r", "").replace("\n", "")
    head = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{safe}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n").encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + data + tail, f"multipart/form-data; boundary={boundary}"


def upload_file(token: str, channel: str, path, title: str | None = None,
                comment: str | None = None) -> bool:
    """成功で True。失敗は stderr にエラー内容(トークンは出さない)を出して False。"""
    p = pathlib.Path(path)
    try:
        data = p.read_bytes()
        # ① アップロード URL 取得
        r1 = _api_form(token, "files.getUploadURLExternal",
                       {"filename": p.name, "length": str(len(data))})
        upload_url, file_id = r1["upload_url"], r1["file_id"]
        # ② バイト列を POST
        ctype = "application/pdf" if p.suffix.lower() == ".pdf" else "application/octet-stream"
        body, ct = _multipart(p.name, data, ctype)
        req = urllib.request.Request(upload_url, data=body, headers={"Content-Type": ct})
        with urllib.request.urlopen(req, timeout=120) as r:
            if r.status != 200:
                raise SlackError(f"upload: HTTP {r.status}")
        # ③ 完了(チャンネル共有)
        payload = {"files": [{"id": file_id, "title": title or p.name}], "channel_id": channel}
        if comment:
            payload["initial_comment"] = comment
        _api_json(token, "files.completeUploadExternal", payload)
        return True
    except SlackError as e:
        print(f"slack_bot error: {e}", file=sys.stderr)
    except Exception as e:  # ネットワーク・ファイル系。メッセージにトークンは含まれない
        print(f"slack_bot error: {type(e).__name__}: {e}", file=sys.stderr)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="PDF 等を Slack に Bot トークンで投稿")
    ap.add_argument("path")
    ap.add_argument("--title")
    ap.add_argument("--comment")
    a = ap.parse_args()
    token, channel = os.environ.get("SLACK_BOT_TOKEN"), os.environ.get("SLACK_CHANNEL")
    if not token or not channel:
        print("SLACK_BOT_TOKEN と SLACK_CHANNEL(チャンネルID)を環境変数に設定してください", file=sys.stderr)
        return 2
    ok = upload_file(token, channel, a.path, a.title, a.comment)
    print("slack_bot: ok" if ok else "slack_bot: failed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
