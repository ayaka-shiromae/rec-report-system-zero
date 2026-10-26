#!/usr/bin/env bash
# /var/rec/report を OneDrive の「接客対応品質」へ同期する(rclone)。
# rclone の設定(remote 名 "onedrive")が無ければ何もしない。
set -u
REMOTE="${RCLONE_REMOTE:-onedrive:接客対応品質}"
SRC="${REPORT_DIR:-/var/rec/report}"

command -v rclone >/dev/null 2>&1 || { echo "rclone 未インストール、同期スキップ"; exit 0; }
rclone listremotes 2>/dev/null | grep -q "^${REMOTE%%:*}:" || { echo "rclone remote 未設定、同期スキップ"; exit 0; }

# copy(削除は同期しない): ミニPC側で古いレポートを消しても OneDrive 側には残す
rclone copy "$SRC" "$REMOTE" --exclude "スクリプト/**" --log-level NOTICE
