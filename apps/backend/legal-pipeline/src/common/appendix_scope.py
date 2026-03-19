from __future__ import annotations

import re
from typing import Any

EXCLUDED_APPENDIX_TOKENS = ("별지", "서식")
INCLUDED_APPENDIX_TOKENS = ("별표",)


def _normalize_scope_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def appendix_exclusion_reason(
    appendix_kind: Any,
    appendix_title: Any,
    appendix_key: Any = None,
) -> str | None:
    kind_text = _normalize_scope_text(appendix_kind)
    title_text = _normalize_scope_text(appendix_title)
    key_text = _normalize_scope_text(appendix_key).upper()

    if any(token in kind_text for token in EXCLUDED_APPENDIX_TOKENS):
        return "excluded_non_target_kind"
    if any(token in title_text for token in EXCLUDED_APPENDIX_TOKENS):
        return "excluded_non_target_title"

    if any(token in kind_text for token in INCLUDED_APPENDIX_TOKENS):
        return None
    if any(token in title_text for token in INCLUDED_APPENDIX_TOKENS):
        return None

    if key_text.endswith("F"):
        return "excluded_non_target_key_suffix"
    if key_text.endswith("E"):
        return None

    return "excluded_not_identified_as_annex_table"


def is_target_appendix(
    appendix_kind: Any,
    appendix_title: Any,
    appendix_key: Any = None,
) -> bool:
    return appendix_exclusion_reason(appendix_kind, appendix_title, appendix_key) is None
