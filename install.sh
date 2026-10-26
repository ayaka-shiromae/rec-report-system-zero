#!/usr/bin/env bash
# ミニPC(Ubuntu Server 24.04)への導入・更新スクリプト。何度実行しても安全(冪等)。
#   初回:   git clone ... ~/hotel-front-recording && cd ~/hotel-front-recording && ./install.sh
#   更新:   cd ~/hotel-front-recording && git pull && ./install.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
VENV="${VENV:-/home/$USER_NAME/whisper-venv}"
ENV_FILE=/etc/rec/env

say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

say "1/6 OS パッケージ"
sudo apt-get install -y -q alsa-utils ffmpeg iw python3-venv fonts-noto-cjk \
  libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 libcairo2 >/dev/null

say "2/6 Python 仮想環境 ($VENV)"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -U pip
"$VENV/bin/pip" install -q --only-binary=:all: "av<15" || true
"$VENV/bin/pip" install -q -r "$REPO/requirements.txt"

say "3/6 ディレクトリと権限"
sudo mkdir -p /var/rec/{raw,text,shifts,daily,report,state} /etc/rec
sudo chown -R "$USER_NAME:$USER_NAME" /var/rec
sudo usermod -aG audio "$USER_NAME"
if [ ! -f "$ENV_FILE" ]; then
  sudo cp "$REPO/.env.example" "$ENV_FILE"
  echo "  -> $ENV_FILE を作成しました。あとで値を入れてください(sudo nano $ENV_FILE)"
fi
sudo chown "root:$USER_NAME" "$ENV_FILE"; sudo chmod 640 "$ENV_FILE"
for k in ANTHROPIC_API_KEY SLACK_WEBHOOK_URL CALENDAR_ICS_URL; do
  if ! sudo grep -q "^$k=" "$ENV_FILE"; then echo "$k=" | sudo tee -a "$ENV_FILE" >/dev/null; echo "  -> $k を $ENV_FILE に追加(値は空)"; fi
done

say "4/6 systemd ユニット"
WIFI="$(iw dev 2>/dev/null | awk '/Interface/{print $2; exit}')"
for f in "$REPO"/systemd/*; do
  name="$(basename "$f")"
  sed -e "s#__USER__#$USER_NAME#g" -e "s#__REPO__#$REPO#g" -e "s#__VENV__#$VENV#g" -e "s#__WIFI__#${WIFI:-wlan0}#g" \
    "$f" | sudo tee "/etc/systemd/system/$name" >/dev/null
done
sudo systemctl daemon-reload
# 旧ユニット(初期版の週次解析)があれば止める
if systemctl list-unit-files | grep -q '^rec-analyze.timer'; then
  sudo systemctl disable --now rec-analyze.timer 2>/dev/null || true
  sudo rm -f /etc/systemd/system/rec-analyze.{service,timer}; sudo systemctl daemon-reload
fi
sudo systemctl enable --now wifi-powersave-off.service rec-capture.service \
  rec-transcribe.timer rec-daily.timer rec-weekly.timer

say "5/6 録音 WAV の掃除(7 日)"
( crontab -l 2>/dev/null | grep -v 'find /var/rec/raw' ; echo "15 4 * * * find /var/rec/raw -name '*.wav' -mtime +7 -delete" ) | crontab -

say "6/6 状態"
chmod +x "$REPO"/scripts/*.sh 2>/dev/null || true
systemctl --no-pager list-timers 'rec-*' | sed 's/^/  /'
systemctl is-active rec-capture.service | sed 's/^/  rec-capture: /'
arecord -l 2>/dev/null | grep -q CODEC && echo "  マイク: 認識OK" || echo "  マイク: 未認識(CODEC が見えません)"
missing=$(sudo awk -F= '/^(ANTHROPIC_API_KEY|SLACK_WEBHOOK_URL|CALENDAR_ICS_URL)=$/{print $1}' "$ENV_FILE" | tr '\n' ' ')
[ -n "$missing" ] && echo "  未設定: $missing  -> sudo nano $ENV_FILE"
echo
echo "動作確認:  $VENV/bin/python -m frontrec.daily --dry-run   (config: $REPO/config.yaml)"
