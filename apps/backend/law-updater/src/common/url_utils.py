from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_QUERY_KEYS = {"OC"}
INLINE_URL_PATTERN = re.compile(r"((?:https?://|/DRF/)\S+)")


def sanitize_detail_link(url: str | None) -> str | None:
    text = str(url or "").strip()
    if not text:
        return None

    parsed = urlsplit(text)
    if not parsed.query:
        return text

    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if str(key).strip().upper() not in SENSITIVE_QUERY_KEYS
    ]
    sanitized_query = urlencode(query_items, doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, sanitized_query, parsed.fragment))


def sanitize_inline_urls(text: str | None) -> str:
    raw = str(text or "")
    if not raw:
        return ""

    def _replace(match: re.Match[str]) -> str:
        candidate = match.group(1)
        return sanitize_detail_link(candidate) or ""

    return INLINE_URL_PATTERN.sub(_replace, raw)
