# hotel-front-recording

ホテルのフロント接客を録音 → ローカル文字起こし → Google カレンダーのシフトで担当者に割当 → Claude API で解析 → 人別フィードバック(PDF/md)と管理者向け運用メモを毎週出す、現地設置ミニPC用の一式。

```
録音(arecord, 1h WAV)  ─► 文字起こし(faster-whisper, 10分毎)  ─► シフト切り出し + 一次解析(毎晩 03:30, Claude Batch)
                                                                        │
                                              週次集約(月曜 05:00) ◄────┘
                                              ├ YYYYMMDD_配布用_簡易接客レポート.pdf   (1人1ページ・全員分)
                                              ├ 詳細レポート/<名前>/YYYYMMDD_<名前>_詳細接客レポート.md
                                              ├ 管理レポート/YYYYMMDD_管理レポート.md   (運用メモ形式)
                                              ├ Slack に全員分の簡易フィードバック
                                              └ rclone で OneDrive へ同期(任意)
```

## 導入(ミニPC・Ubuntu Server 24.04)

```bash
git clone <このリポジトリ> ~/hotel-front-recording
cd ~/hotel-front-recording
./install.sh                      # apt / venv / ディレクトリ / systemd まで全部
sudo nano /etc/rec/env            # ANTHROPIC_API_KEY, SLACK_WEBHOOK_URL, CALENDAR_ICS_URL
~/whisper-venv/bin/python -m frontrec.daily --dry-run     # 対象シフトが出れば OK
```

更新は `git pull && ./install.sh`。

### 前提
- USB マイクが ALSA で `CODEC` という名前で見えること(`arecord -l`)。違う場合は `systemd/rec-capture.service` の `plughw:CARD=...` を直す
- Google カレンダーにシフトが「`開始時刻` + `名前 (役割)`」の予定で入っていること(役割は省略可)。
  - 予定に 1 時間を超える終了時刻が入っていればそれを使う。無ければ「次のシフト開始まで(最短 6h・最長 10h)」で推定(`config.yaml` の `calendar`)
  - 同じ時間帯に 2 人いる場合は両方のレポートに同じ会話が載り、どちらの発言か不明なものは本人評価に使わない
- Claude Console の API キー(ホテル名義推奨)、Slack Incoming Webhook

## 別ホテルへの横展開
1. ミニPC + USB バウンダリーマイクを用意し、Ubuntu Server を入れて SSH できる状態にする
2. そのホテル用のシフトカレンダーを Google カレンダーで作り、iCal 非公開 URL を取得
3. この repo を clone し、`config.yaml` の `hotel` / `staff.aliases` / 必要なら `calendar.summary_pattern` を書き換える
4. `./install.sh` → `/etc/rec/env` に 3 つの値を入れる

## 手動実行

```bash
V=~/whisper-venv/bin/python
$V -m frontrec.daily                 # 終了済みシフトを解析(未処理分だけ)
$V -m frontrec.daily --force --days 7   # 直近 7 日をやり直し
$V -m frontrec.weekly                # 昨日までの 7 日分でレポート一式
$V -m frontrec.weekly --end 2026-10-25 --no-slack
journalctl -u rec-daily -u rec-weekly -n 50 --no-pager
```

## ファイル
| パス | 内容 |
|---|---|
| `config.yaml` | ホテル名・パス・カレンダー解釈・スタッフ名寄せ・モデル・出力ファイル名 |
| `.env.example` | `/etc/rec/env` の雛形(秘密情報は repo に入れない) |
| `frontrec/shifts.py` | ICS → シフト区間、文字起こし行の時刻割当 |
| `frontrec/daily.py` | シフト単位の一次解析(JSON) |
| `frontrec/weekly.py` | 週次集約、PDF/md/Slack |
| `frontrec/prompts/*.md` | Claude へのプロンプト(評価軸はここを直す) |
| `scripts/transcribe.py` | faster-whisper 文字起こし |
| `scripts/sync-onedrive.sh` | rclone で OneDrive へ copy(remote 未設定なら何もしない) |
| `systemd/` | ユニットの雛形(`__USER__` 等を install.sh が置換) |
| `tests/make_fixtures.py` | テスト用の ICS と文字起こしを生成 |

## OneDrive 同期(任意)
ミニPC に画面が無いので、認証は手元の Windows で行う:
```
# Windows (rclone.exe を置いたフォルダで)
rclone authorize "onedrive"        # ブラウザでログイン → 表示されたトークンをコピー
# ミニPC
sudo apt install -y rclone
rclone config    # n → 名前 onedrive → onedrive → 認証は「他のマシンで」 → トークン貼付 → OneDrive Personal/Business を選択
rclone lsd onedrive:接客対応品質
```
`scripts/sync-onedrive.sh` が週次の後に自動で走る(`RCLONE_REMOTE` 環境変数で remote/パスを変更可)。

## データ保持
- `/var/rec/raw` の WAV は 7 日で自動削除(cron)
- `text` `shifts` `daily` `report` は残す(必要なら cron を足す)

## Phase B(未実装): 話者識別
pyannote による話者分離 + 話者埋め込みで、重複シフト時の「誰の発言か」と「スタッフ vs 客」の判別精度を上げる。
1 人シフトの時間帯の主要話者をその人の声として自動学習する想定。CPU 負荷が重いので、まずシフト割当だけで運用してから判断する。
