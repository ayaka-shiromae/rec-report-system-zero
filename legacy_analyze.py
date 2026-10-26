#!/usr/bin/env python3
"""
週次解析バッチ: 直近7日分の文字起こしをマスキングして Claude API (Batch) に投げ、
  1) 週次レポート(md) を /var/rec/report/ に保存
  2) 本人向けフィードバック(6行程度) を Slack に送信

環境変数は /etc/rec/env から読む (systemd の EnvironmentFile):
  ANTHROPIC_API_KEY=sk-ant-...
  SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
  MODEL=claude-opus-5-5        # 省略可
  DAYS=7                       # 省略可
"""
import os, re, sys, glob, json, time, datetime as dt, urllib.request
import anthropic

TEXT_DIR = "/var/rec/text"
REPORT_DIR = "/var/rec/report"
MODEL = os.environ.get("MODEL", "claude-opus-5-5")
DAYS = int(os.environ.get("DAYS", "7"))
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")

# ---------- 1. 入力収集 ----------
today = dt.date.today()
since = today - dt.timedelta(days=DAYS)
chunks = []
for path in sorted(glob.glob(f"{TEXT_DIR}/*.txt")):
    base = os.path.basename(path)
    m = re.match(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})", base)
    if not m:
        continue
    d = dt.date(int(m[1]), int(m[2]), int(m[3]))
    if not (since <= d < today):
        continue
    body = open(path, encoding="utf-8").read().strip()
    if not body:
        continue
    chunks.append(f"### {m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]} 開始\n{body}")

if not chunks:
    print("no transcripts in range; nothing to do")
    sys.exit(0)

raw = "\n\n".join(chunks)

# ---------- 2. マスキング ----------
def mask(t: str) -> str:
    t = re.sub(r"0\d{1,4}[-ー‐]?\d{1,4}[-ー‐]?\d{3,4}", "[電話番号]", t)
    t = re.sub(r"\d{3,4}\s*号室", "[部屋番号]", t)
    t = re.sub(r"[\u3040-\u30ff\u4e00-\u9fff]{1,4}(?:様|さま)", "[お客様]", t)
    t = re.sub(r"[一-龥ぁ-んァ-ン]{1,4}\s?\d{2,3}\s?[あ-ん]\s?\d{1,4}[-ー]?\d{0,2}", "[車番]", t)
    return t

masked = mask(raw)
period = f"{since.isoformat()} 〜 {(today - dt.timedelta(days=1)).isoformat()}"

# ---------- 3. プロンプト ----------
SYSTEM = f"""あなたはホテルZERO(名古屋・レジャーホテル)のフロント接客を改善するための分析担当です。
フロントカウンターの録音を文字起こししたテキスト(1時間ごとに分割、話者分離なし、誤認識あり)を読み、
以下の評価軸で接客を分析してください。

【評価軸】(Googleマップ口コミで指摘された内容に基づく)
1. 挨拶・言葉遣い・トーン: 無愛想、高圧的、ぶっきらぼうな応対になっていないか
2. ルール説明の仕方: 半ドア停電・フリータイム条件・途中退店の返金規定などを、
   「禁止・警告」ではなく「理由+代替案」の形で伝えているか
3. 断り方・クレーム時の対応: お客様の要望を断る場面、不満が出た場面での受け止め方
4. 電話の受け答え: 電話応対があれば、その印象と案内の正確さ

【注意】
- 文字起こしには誤認識や無関係な雑音(TV、独り言、スタッフ同士の雑談)が含まれる。接客場面だけを対象にする
- 個人名・電話番号・部屋番号・車番は出力に含めない(マスク済みだが残っていた場合も伏せる)
- 特定のスタッフを断定・非難しない。事実(発言の引用)と改善案を分けて書く
- 引用は必要最小限にし、文脈が分かる程度に短くする

出力は必ず次の2ブロックを、この区切り文字で分けて返すこと:

=== REPORT ===
(週次レポート本文。Markdown。見出し構成:
# ホテルZERO フロント接客 週次レポート({period})
## 1. 今週のサマリ(3〜5行)
## 2. シチュエーション別の件数と傾向(チェックイン/精算/ルール説明/問い合わせ/クレーム/電話 など)
## 3. 良かった対応(具体例を2〜4件、短い引用付き)
## 4. 改善が必要な対応(具体例を2〜4件、短い引用+何が問題か)
## 5. 改善提案(来週から実践できる言い回し・行動を3〜5件)
## 6. 文字起こし品質メモ(聞き取れていない場面・雑音など、システム側の改善点)
)

=== FEEDBACK ===
(フロントスタッフ本人に渡す短いフィードバック。全体で6行程度。見出しなしのプレーンテキスト:
よかったこと: 1〜2行
わるかったこと: 1〜2行
改善のしかた: 2〜3行
責める口調にせず、明日から試せる具体的な言い回しを入れる)
"""

user_msg = f"対象期間: {period}\n\n以下が文字起こしです。\n\n{masked}"

# ---------- 4. Batch API ----------
client = anthropic.Anthropic()
batch = client.messages.batches.create(
    requests=[{
        "custom_id": f"weekly-{today.isoformat()}",
        "params": {
            "model": MODEL,
            "max_tokens": 8000,
            "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user_msg}],
        },
    }]
)
print(f"batch created: {batch.id}")

while True:
    b = client.messages.batches.retrieve(batch.id)
    if b.processing_status == "ended":
        break
    time.sleep(60)

text = None
for r in client.messages.batches.results(batch.id):
    if r.result.type == "succeeded":
        text = "".join(c.text for c in r.result.message.content if c.type == "text")
    else:
        print("batch request failed:", r.result, file=sys.stderr)
        sys.exit(1)

# ---------- 5. 分割・保存・通知 ----------
m = re.search(r"=== REPORT ===\s*(.*?)\s*=== FEEDBACK ===\s*(.*)$", text, re.S)
if not m:
    report, feedback = text, "(FEEDBACK ブロックを抽出できませんでした。レポートを確認してください)"
else:
    report, feedback = m.group(1).strip(), m.group(2).strip()

os.makedirs(REPORT_DIR, exist_ok=True)
out = f"{REPORT_DIR}/{today.isoformat()}_weekly.md"
with open(out, "w", encoding="utf-8") as f:
    f.write(report + "\n\n---\n\n## 本人向けフィードバック\n\n" + feedback + "\n")
print(f"saved: {out}")

if WEBHOOK:
    payload = {"text": f"*ホテルZERO フロント 週次フィードバック({period})*\n\n{feedback}\n\n_レポート本体: {out}_"}
    req = urllib.request.Request(WEBHOOK, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        print("slack:", resp.status)
