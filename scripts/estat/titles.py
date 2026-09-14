"""Normalize period and prefecture tokens in e-Stat titles for template deduplication. Uses the Python standard library and returns normalized strings."""

from __future__ import annotations

import re
import unicodedata


_ERA = r"(?:令和|平成|昭和|大正|明治)"
_PERIOD_PATTERNS = [

    r"\d{4}年\d{1,2}月\d{1,2}日(?:現在|時点)?",
    r"\d{4}年\d{1,2}月(?:期|分|号|末)?(?:現在|時点)?",
    r"\d{4}年度?",

    _ERA + r"(?:元|\d{1,2})年\d{1,2}月\d{1,2}日(?:現在|時点)?",
    _ERA + r"(?:元|\d{1,2})年\d{1,2}月(?:期|分|号|末)?(?:現在|時点)?",
    _ERA + r"(?:元|\d{1,2})年度?",

    r"(?<![A-Za-z0-9])[HRSMT]\d{1,2}年度?",

    r"第\d{1,2}四半期",
    r"\d{1,2}[〜~‐–—-]\d{1,2}月期?",

    r"\d{1,2}月\d{1,2}日(?:現在|時点)?",
    r"\d{1,2}月(?:期|分|号|末)?(?:現在|時点)?",

    r"(?:上|下)半期",
    r"第\d{1,3}回",

    r"(?<!\d)(?:19|20)\d{2}(?:[〜~‐–—-](?:19|20)\d{2})?(?:年度?)?(?!\d)",
]
_PERIOD_RE = re.compile("|".join(f"(?:{p})" for p in _PERIOD_PATTERNS))


_PREF_FULL = (
    "北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|埼玉県|千葉県|"
    "東京都|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|岐阜県|静岡県|愛知県|三重県|"
    "滋賀県|京都府|大阪府|兵庫県|奈良県|和歌山県|鳥取県|島根県|岡山県|広島県|山口県|徳島県|"
    "香川県|愛媛県|高知県|福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県"
)
_PREF_SHORT = (
    "青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|東京|神奈川|新潟|富山|石川|福井|"
    "山梨|長野|岐阜|静岡|愛知|三重|滋賀|京都|大阪|兵庫|奈良|和歌山|鳥取|島根|岡山|広島|山口|"
    "徳島|香川|愛媛|高知|福岡|佐賀|長崎|熊本|大分|宮崎|鹿児島|沖縄"
)
_DELIM = r"[_・()\[\]\s/、,‐–—-]"
_REGION_RE = re.compile(

    rf"(?<![0-9])(?:[0-9]{{1,2}})?(?:{_PREF_FULL})"

    rf"|(?<![0-9])[0-9]{{1,2}}(?:{_PREF_SHORT})(?![都府県])"

    rf"|(?:^|(?<={_DELIM}))(?:{_PREF_SHORT})(?={_DELIM}|$)"
)



_EMPTY_BRACKETS_RE = re.compile(r"[(\[【〈《「『][\s・、,/〜~‐–—_-]*[)\]】〉》」』]")
_DANGLING_RE = re.compile(r"(?:^|(?<=\s))[・、,/〜~‐–—_-]+(?=\s|$)")
_UNDERSCORE_RUN_RE = re.compile(r"[\s_]*_[\s_]*")
_SEP_RUN_RE = re.compile(r"[・、,/]{2,}")
_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = _EMPTY_BRACKETS_RE.sub(" ", text)
        text = _DANGLING_RE.sub(" ", text)
    text = _UNDERSCORE_RUN_RE.sub("_", text)
    text = _SEP_RUN_RE.sub("・", text)
    text = _WS_RE.sub(" ", text).strip()
    return text.strip("・、,/〜~‐–—-_ ")


def dataset_title_stem(title: str | None, *, strip_region: bool = True) -> str:
    if not title:
        return ""
    text = unicodedata.normalize("NFKC", title)
    text = _PERIOD_RE.sub(" ", text)
    if strip_region:
        text = _REGION_RE.sub(" ", text)
    return _clean(text)


def normalize_table_name(name: str | None) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name)
    return _WS_RE.sub(" ", text).strip()
