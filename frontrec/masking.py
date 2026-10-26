"""お客様の個人情報らしき箇所を Claude に渡す前に伏せる(正規表現ベース、完璧ではない)。"""
import re

_RULES = [
    (re.compile(r"0\d{1,4}[-ー‐]?\d{1,4}[-ー‐]?\d{3,4}"), "[電話番号]"),
    (re.compile(r"[一-龥ぁ-んァ-ン]{1,4}\s?\d{2,3}\s?[あ-ん]\s?\d{1,4}[-ー]?\d{0,2}"), "[車番]"),
    (re.compile(r"[぀-ヿ一-鿿]{1,4}(?:様|さま)(?![々])"), "[お客様]"),
]


def mask(text: str, staff_names: list[str] | None = None) -> str:
    """部屋番号は運用上の事実(設備不良など)に必要なので残す。スタッフ名も残す。"""
    for pat, rep in _RULES:
        text = pat.sub(rep, text)
    return text
