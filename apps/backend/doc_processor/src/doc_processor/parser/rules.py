from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ..parser_types import NumberingLevel

ARTICLE_RE = re.compile(
    r"^\s*제\s*(?P<number>\d+)\s*조(?:의\s*(?P<subnumber>\d+))?\s*(?:[(:（](?P<title>[^)）]{1,120})[)）])?",
)
NUMERIC_DOT_RE = re.compile(r"^\s*(?P<number>\d+)\.\s*(?P<title>.+)?")

CIRCLED_NUMERAL_RE = re.compile(r"^\s*(?P<number>[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])")
PAREN_NUMERIC_RE = re.compile(r"^\s*\((?P<number>\d+)\)")
SUB_NUMERIC_DOT_RE = re.compile(r"^\s*(?P<number>\d+)\.\s+")

ANY_CIRCLED_NUMERAL_RE = re.compile(r"(?P<number>[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])")
ANY_PAREN_NUMERIC_RE = re.compile(r"\((?P<number>\d+)\)")
ANY_SUB_NUMERIC_DOT_RE = re.compile(r"(?<!\S)(?P<number>\d+)\.\s+")

APPENDIX_MARKER_RE = re.compile(r"^\s*(\[?(?:별표|별지|서식|붙임)\s*\d*\]?|붙임\s*\d+)")
HEADER_KEYWORD_RE = re.compile(r"(고시|공고|훈령|예규|지침|장관|부령|호수)")
FOOTER_RE = re.compile(r"^\s*(?:-?\s*\d+\s*-?|페이지\s*\d+|Page\s*\d+)\s*$", re.I)
INPUT_RE = re.compile(
    r"(?:_{3,}|[□■○●]\s*|서명|성명|대표자|주민등록번호|생년월일|주소|연락처|인\)|\(인\)|날인|도장|년\s*월\s*일)"
)


@dataclass(frozen=True)
class NumberingMatch:
    rule_name: str
    level: NumberingLevel
    number: str
    start: int
    end: int
    title: str | None = None


CLAUSE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("article", ARTICLE_RE),
    ("numeric_dot", NUMERIC_DOT_RE),
)

SUBCLAUSE_START_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("circled", CIRCLED_NUMERAL_RE),
    ("paren_numeric", PAREN_NUMERIC_RE),
    ("numeric_dot", SUB_NUMERIC_DOT_RE),
)

SUBCLAUSE_ANY_RULES: dict[str, re.Pattern[str]] = {
    "circled": ANY_CIRCLED_NUMERAL_RE,
    "paren_numeric": ANY_PAREN_NUMERIC_RE,
    "numeric_dot": ANY_SUB_NUMERIC_DOT_RE,
}

SUBCLAUSE_RULE_PRIORITY: dict[str, int] = {
    "circled": 300,
    "paren_numeric": 200,
    "numeric_dot": 100,
}

_CIRCLED_TO_INT = {
    glyph: str(index)
    for index, glyph in enumerate("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳", start=1)
}


def _normalize_number(rule_name: str, raw_number: str) -> str:
    if rule_name == "circled":
        return _CIRCLED_TO_INT[raw_number]
    return raw_number


def match_clause_start(text: str, *, rule_name: str | None = None) -> NumberingMatch | None:
    rules = CLAUSE_RULES if rule_name is None else tuple(rule for rule in CLAUSE_RULES if rule[0] == rule_name)
    for current_rule_name, pattern in rules:
        match = pattern.match(text)
        if not match:
            continue
        title = match.groupdict().get("title")
        number = match.group("number")
        subnumber = match.groupdict().get("subnumber")
        if subnumber:
            number = f"{number}-{subnumber}"
        return NumberingMatch(
            rule_name=current_rule_name,
            level=NumberingLevel.CLAUSE,
            number=number,
            start=match.start(),
            end=match.end(),
            title=title.strip() if title else None,
        )
    return None


def match_subclause_start(
    text: str,
    *,
    rule_name: str | None = None,
    allow_numeric_dot: bool = True,
) -> NumberingMatch | None:
    rules = SUBCLAUSE_START_RULES if rule_name is None else tuple(rule for rule in SUBCLAUSE_START_RULES if rule[0] == rule_name)
    for current_rule_name, pattern in rules:
        if current_rule_name == "numeric_dot" and not allow_numeric_dot:
            continue
        match = pattern.match(text)
        if not match:
            continue
        raw_number = match.group("number")
        return NumberingMatch(
            rule_name=current_rule_name,
            level=NumberingLevel.SUBCLAUSE,
            number=_normalize_number(current_rule_name, raw_number),
            start=match.start(),
            end=match.end(),
        )
    return None


def iter_subclause_matches(
    text: str,
    *,
    rule_name: str,
    start_pos: int = 0,
) -> Iterable[NumberingMatch]:
    pattern = SUBCLAUSE_ANY_RULES[rule_name]
    for match in pattern.finditer(text, pos=start_pos):
        if match.start() > 0:
            prefix = text[max(0, match.start() - 1) : match.start()]
            if prefix and not prefix.isspace():
                continue
        raw_number = match.group("number")
        yield NumberingMatch(
            rule_name=rule_name,
            level=NumberingLevel.SUBCLAUSE,
            number=_normalize_number(rule_name, raw_number),
            start=match.start(),
            end=match.end(),
        )


def detect_clause_rule(texts: Iterable[str]) -> str | None:
    for text in texts:
        if not text.strip():
            continue
        match = match_clause_start(text)
        if match:
            return match.rule_name
    return None


def detect_first_subclause_rule(
    texts: Iterable[str],
    *,
    allow_numeric_dot: bool,
) -> str | None:
    for text in texts:
        if not text.strip():
            continue
        match = match_subclause_start(text, allow_numeric_dot=allow_numeric_dot)
        if match:
            return match.rule_name
    return None


def strip_numbering_prefix(text: str, match: NumberingMatch | None) -> str:
    if match is None:
        return text.strip()
    return text[match.end :].strip()
