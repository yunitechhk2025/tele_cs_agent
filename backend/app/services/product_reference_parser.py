from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any


@dataclass(frozen=True)
class ProductReferenceResult:
    slot: int | None = None
    relative_kind: str = ""
    offset_from_end: int | None = None
    is_selection_only: bool = False
    is_active_product_reference: bool = False
    confidence: float = 0.0
    matched_text: str = ""


_PUNCT_TO_SPACE = r"[\s\-_、，,./|:;；：()\[\]{}¿?¡!。！]+"

_CN_NUMBERS = {
    "一": 1,
    "壹": 1,
    "二": 2,
    "两": 2,
    "兩": 2,
    "贰": 2,
    "貳": 2,
    "三": 3,
    "叁": 3,
    "參": 3,
    "四": 4,
    "肆": 4,
    "五": 5,
    "伍": 5,
    "六": 6,
    "陆": 6,
    "陸": 6,
    "七": 7,
    "柒": 7,
    "八": 8,
    "捌": 8,
    "九": 9,
    "玖": 9,
}

_JP_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_KR_NUMBERS = {
    "첫": 1,
    "한": 1,
    "하나": 1,
    "일": 1,
    "두": 2,
    "둘": 2,
    "이": 2,
    "세": 3,
    "셋": 3,
    "삼": 3,
    "네": 4,
    "넷": 4,
    "사": 4,
    "다섯": 5,
    "오": 5,
    "여섯": 6,
    "육": 6,
    "일곱": 7,
    "칠": 7,
    "여덟": 8,
    "팔": 8,
    "아홉": 9,
    "구": 9,
}

_ABSOLUTE_WORDS = {
    1: [
        "第一",
        "第一个",
        "第一個",
        "第一款",
        "第一件",
        "第一号",
        "第一號",
        "头一个",
        "頭一個",
        "first",
        "1st",
        "primero",
        "primera",
        "primer",
        "premier",
        "premiere",
        "一番目",
        "一つ目",
        "ひとつ目",
        "最初",
        "첫번째",
        "첫 번째",
    ],
    2: [
        "第二",
        "第二个",
        "第二個",
        "第二款",
        "第二件",
        "第二号",
        "第二號",
        "second",
        "2nd",
        "segundo",
        "segunda",
        "deuxieme",
        "second",
        "seconde",
        "二番目",
        "二つ目",
        "ふたつ目",
        "두번째",
        "두 번째",
    ],
    3: [
        "第三",
        "第三个",
        "第三個",
        "第三款",
        "第三件",
        "第三号",
        "第三號",
        "third",
        "3rd",
        "tercero",
        "tercera",
        "tercer",
        "troisieme",
        "三番目",
        "三つ目",
        "みっつ目",
        "세번째",
        "세 번째",
    ],
    4: [
        "第四",
        "第四个",
        "第四個",
        "第四款",
        "fourth",
        "4th",
        "cuarto",
        "cuarta",
        "quatrieme",
        "四番目",
        "四つ目",
        "네번째",
        "네 번째",
    ],
    5: [
        "第五",
        "第五个",
        "第五個",
        "第五款",
        "fifth",
        "5th",
        "quinto",
        "quinta",
        "cinquieme",
        "五番目",
        "五つ目",
        "다섯번째",
        "다섯 번째",
    ],
    6: [
        "第六",
        "第六个",
        "第六個",
        "第六款",
        "sixth",
        "6th",
        "sexto",
        "sexta",
        "sixieme",
        "六番目",
        "六つ目",
        "여섯번째",
        "여섯 번째",
    ],
    7: [
        "第七",
        "第七个",
        "第七個",
        "第七款",
        "seventh",
        "7th",
        "septimo",
        "septima",
        "septieme",
        "七番目",
        "七つ目",
        "일곱번째",
        "일곱 번째",
    ],
    8: [
        "第八",
        "第八个",
        "第八個",
        "第八款",
        "eighth",
        "8th",
        "octavo",
        "octava",
        "huitieme",
        "八番目",
        "八つ目",
        "여덟번째",
        "여덟 번째",
    ],
    9: [
        "第九",
        "第九个",
        "第九個",
        "第九款",
        "ninth",
        "9th",
        "noveno",
        "novena",
        "neuvieme",
        "九番目",
        "九つ目",
        "아홉번째",
        "아홉 번째",
    ],
}

_LAST_PHRASES = [
    "最后",
    "最後",
    "末尾",
    "last",
    "last one",
    "ultimo",
    "ultima",
    "dernier",
    "derniere",
    "最後の商品",
    "마지막",
    "마지막 제품",
]
_SECOND_FROM_END_PHRASES = [
    "second to last",
    "second last",
    "second from last",
    "penultimate",
    "penultimo",
    "penultima",
    "avant dernier",
    "avant derniere",
    "penultieme",
]
_THIRD_FROM_END_PHRASES = [
    "third to last",
    "third last",
    "third from last",
    "antepenultimate",
    "antepenultimo",
    "antepenultima",
    "antepenultieme",
]
_MIDDLE_PHRASES = [
    "中间",
    "中間",
    "middle",
    "middle one",
    "del medio",
    "el del medio",
    "la del medio",
    "du milieu",
    "celui du milieu",
    "celle du milieu",
    "真ん中",
    "真ん中の商品",
    "가운데",
    "가운데 제품",
]
_PREVIOUS_PHRASES = [
    "上一个",
    "上一個",
    "前一个",
    "前一個",
    "previous",
    "previous one",
    "anterior",
    "precedent",
    "precedente",
    "前の商品",
    "이전",
    "이전 제품",
]
_NEXT_PHRASES = [
    "下一个",
    "下一個",
    "后一个",
    "後一個",
    "next",
    "next one",
    "siguiente",
    "suivant",
    "suivante",
    "次の商品",
    "다음",
    "다음 제품",
]
_FORMER_PHRASES = ["前者", "former", "the former"]
_LATTER_PHRASES = ["后者", "後者", "latter", "the latter"]
_ACTIVE_REFERENCE_PHRASES = [
    "这个",
    "這個",
    "这款",
    "這款",
    "这件",
    "這件",
    "这个产品",
    "這個產品",
    "它",
    "this one",
    "this product",
    "it",
    "este producto",
    "este",
    "ese producto",
    "ce produit",
    "celui ci",
    "celui la",
    "この商品",
    "その商品",
    "これ",
    "それ",
    "이 제품",
    "그 제품",
    "이것",
    "그것",
]
_ACTION_CONTEXT_PHRASES = [
    "show me",
    "see",
    "generate",
    "living room",
    "room",
    "style",
    "styled",
    "scene",
    "ver",
    "muestrame",
    "mostrar",
    "salon",
    "sala",
    "estilo",
    "montre",
    "voir",
    "salon",
    "style",
    "看看",
    "生成",
    "效果图",
    "客厅",
    "風格",
    "风格",
    "見たい",
    "リビング",
    "スタイル",
    "보고",
    "거실",
    "스타일",
]


def normalize_reference_text(value: Any) -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).lower()
    without_marks = unicodedata.normalize(
        "NFC",
        "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn"),
    )
    spaced = re.sub(_PUNCT_TO_SPACE, " ", without_marks)
    return re.sub(r"\s+", " ", spaced).strip()


def _compact(value: str) -> str:
    return re.sub(_PUNCT_TO_SPACE, "", value)


def _normalize_phrase(value: str) -> tuple[str, str]:
    spaced = normalize_reference_text(value)
    return spaced, _compact(spaced)


def _contains_phrase(spaced: str, compact: str, phrase: str) -> bool:
    phrase_spaced, phrase_compact = _normalize_phrase(phrase)
    if not phrase_spaced:
        return False
    if re.fullmatch(r"[a-z0-9 ]+", phrase_spaced):
        pattern = rf"(?<![a-z0-9]){re.escape(phrase_spaced)}(?![a-z0-9])"
        return re.search(pattern, spaced) is not None
    return phrase_compact in compact


def _first_phrase(spaced: str, compact: str, phrases: list[str]) -> str:
    for phrase in sorted(phrases, key=len, reverse=True):
        if _contains_phrase(spaced, compact, phrase):
            return phrase
    return ""


def _parse_number_token(token: str | None) -> int | None:
    if not token:
        return None
    clean = normalize_reference_text(token)
    if clean.isdigit():
        value = int(clean)
        return value if 1 <= value <= 9 else None
    if clean in _CN_NUMBERS:
        return _CN_NUMBERS[clean]
    if clean in _JP_NUMBERS:
        return _JP_NUMBERS[clean]
    if clean in _KR_NUMBERS:
        return _KR_NUMBERS[clean]
    return None


def _relative_slot(
    kind: str, item_count: int | None, *, offset: int | None = None, current_slot: int | None = None
) -> int | None:
    if kind == "from_end":
        if not item_count or not offset or offset < 1 or offset > item_count:
            return None
        return item_count - offset + 1
    if kind == "middle":
        if not item_count or item_count % 2 == 0:
            return None
        return (item_count + 1) // 2
    if kind == "previous":
        if not item_count or not current_slot or current_slot <= 1:
            return None
        return current_slot - 1
    if kind == "next":
        if not item_count or not current_slot or current_slot >= item_count:
            return None
        return current_slot + 1
    return None


def _result(
    *,
    slot: int | None = None,
    relative_kind: str = "",
    offset_from_end: int | None = None,
    matched_text: str = "",
    confidence: float = 0.0,
    is_active_product_reference: bool = False,
    spaced: str = "",
    compact: str = "",
) -> ProductReferenceResult:
    return ProductReferenceResult(
        slot=slot,
        relative_kind=relative_kind,
        offset_from_end=offset_from_end,
        is_selection_only=_selection_only(
            spaced, compact, bool(slot or relative_kind or is_active_product_reference)
        ),
        is_active_product_reference=is_active_product_reference,
        confidence=confidence,
        matched_text=matched_text,
    )


def _selection_only(spaced: str, compact: str, has_reference: bool) -> bool:
    if not has_reference:
        return False
    if _first_phrase(spaced, compact, _ACTION_CONTEXT_PHRASES):
        return False
    words = spaced.split()
    return len(words) <= 5 or len(compact) <= 16


def _parse_from_end(
    spaced: str, compact: str, item_count: int | None
) -> tuple[int | None, int | None, str]:
    cn_match = re.search(r"倒[数數](?:第)?([1-9一二两兩三四五六七八九壹贰貳叁參])", compact)
    if cn_match:
        offset = _parse_number_token(cn_match.group(1))
        return _relative_slot("from_end", item_count, offset=offset), offset, cn_match.group(0)

    jp_match = re.search(r"後ろから([1-9一二三四五六七八九])(?:番目|つ目)?", compact)
    if jp_match:
        offset = _parse_number_token(jp_match.group(1))
        return _relative_slot("from_end", item_count, offset=offset), offset, jp_match.group(0)

    kr_match = re.search(
        r"뒤에서([1-9]|첫|한|하나|두|둘|세|셋|네|넷|다섯|여섯|일곱|여덟|아홉)(?:번째|번)", compact
    )
    if kr_match:
        offset = _parse_number_token(kr_match.group(1))
        return _relative_slot("from_end", item_count, offset=offset), offset, kr_match.group(0)

    phrase = _first_phrase(spaced, compact, _THIRD_FROM_END_PHRASES)
    if phrase:
        return _relative_slot("from_end", item_count, offset=3), 3, phrase
    phrase = _first_phrase(spaced, compact, _SECOND_FROM_END_PHRASES)
    if phrase:
        return _relative_slot("from_end", item_count, offset=2), 2, phrase
    phrase = _first_phrase(spaced, compact, _LAST_PHRASES)
    if phrase:
        return _relative_slot("from_end", item_count, offset=1), 1, phrase
    return None, None, ""


def _parse_absolute(spaced: str, compact: str) -> tuple[int | None, str]:
    if re.fullmatch(r"#?[1-9]", compact):
        return int(compact.replace("#", "")), compact

    explicit = re.search(
        r"(?:#|编号|編號|商品|产品|產品|no|n\s*o|number|num|numero)\s*([1-9])",
        spaced,
        flags=re.IGNORECASE,
    )
    if explicit:
        return int(explicit.group(1)), explicit.group(0)

    patterns = [
        r"第([1-9一二两兩三四五六七八九壹贰貳叁參])(?:个|個|款|件|号|號)?",
        r"([1-9])(?:个|個|款|件|号|號|番|番目|つ目|번째|번)",
        r"([一二三四五六七八九])(?:番目|つ目)",
        r"([1-9])(?:st|nd|rd|th|er|eme|e)",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            value = _parse_number_token(match.group(1))
            if value:
                return value, match.group(0)

    for slot, phrases in _ABSOLUTE_WORDS.items():
        phrase = _first_phrase(spaced, compact, phrases)
        if phrase:
            return slot, phrase
    return None, ""


def parse_product_reference(
    text: str,
    *,
    item_count: int | None = None,
    current_slot: int | None = None,
) -> ProductReferenceResult:
    spaced = normalize_reference_text(text)
    compact = _compact(spaced)
    if not compact:
        return ProductReferenceResult()

    slot, offset, matched = _parse_from_end(spaced, compact, item_count)
    if matched:
        return _result(
            slot=slot,
            relative_kind="from_end",
            offset_from_end=offset,
            matched_text=matched,
            confidence=0.92,
            spaced=spaced,
            compact=compact,
        )

    phrase = _first_phrase(spaced, compact, _MIDDLE_PHRASES)
    if phrase:
        return _result(
            slot=_relative_slot("middle", item_count),
            relative_kind="middle",
            matched_text=phrase,
            confidence=0.86,
            spaced=spaced,
            compact=compact,
        )

    phrase = _first_phrase(spaced, compact, _PREVIOUS_PHRASES)
    if phrase:
        return _result(
            slot=_relative_slot("previous", item_count, current_slot=current_slot),
            relative_kind="previous",
            matched_text=phrase,
            confidence=0.78,
            spaced=spaced,
            compact=compact,
        )

    phrase = _first_phrase(spaced, compact, _NEXT_PHRASES)
    if phrase:
        return _result(
            slot=_relative_slot("next", item_count, current_slot=current_slot),
            relative_kind="next",
            matched_text=phrase,
            confidence=0.78,
            spaced=spaced,
            compact=compact,
        )

    phrase = _first_phrase(spaced, compact, _FORMER_PHRASES)
    if phrase:
        return _result(
            slot=1 if item_count == 2 else None,
            relative_kind="former",
            matched_text=phrase,
            confidence=0.78,
            spaced=spaced,
            compact=compact,
        )

    phrase = _first_phrase(spaced, compact, _LATTER_PHRASES)
    if phrase:
        return _result(
            slot=2 if item_count == 2 else None,
            relative_kind="latter",
            matched_text=phrase,
            confidence=0.78,
            spaced=spaced,
            compact=compact,
        )

    absolute_slot, matched = _parse_absolute(spaced, compact)
    if absolute_slot:
        return _result(
            slot=absolute_slot,
            relative_kind="absolute",
            matched_text=matched,
            confidence=0.9,
            spaced=spaced,
            compact=compact,
        )

    phrase = _first_phrase(spaced, compact, _ACTIVE_REFERENCE_PHRASES)
    if phrase:
        return _result(
            relative_kind="active",
            matched_text=phrase,
            confidence=0.72,
            is_active_product_reference=True,
            spaced=spaced,
            compact=compact,
        )

    return ProductReferenceResult()


def is_product_selection_only_text(text: str, *, item_count: int | None = None) -> bool:
    return parse_product_reference(text, item_count=item_count).is_selection_only


def is_active_product_reference_text(text: str) -> bool:
    return parse_product_reference(text).is_active_product_reference


def is_product_reference_followup_text(text: str, *, item_count: int | None = None) -> bool:
    result = parse_product_reference(text, item_count=item_count)
    return bool(result.slot or result.relative_kind or result.is_active_product_reference)
