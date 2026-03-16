from __future__ import annotations

from typing import Any, Literal, TypedDict
import json

import httpx
import xmltodict
from bs4 import BeautifulSoup

from src.models.registry_models import RequestSpec


ResponseFormat = Literal["json", "xml", "html", "text"]


class ParsedResponse(TypedDict):
    format: ResponseFormat
    content_type: str
    text: str
    parsed: Any
    status_code: int
    url: str


class HttpClientError(RuntimeError):
    pass


def send_request(request: RequestSpec) -> httpx.Response:
    method = request.method.upper()

    if method != "GET":
        raise ValueError(f"Unsupported HTTP method: {request.method}")

    try:
        response = httpx.request(
            method=method,
            url=request.url,
            params=request.params,
            timeout=request.timeout_sec,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response

    except httpx.HTTPStatusError as exc:
        preview = exc.response.text[:300].replace("\n", " ")
        raise HttpClientError(
            f"HTTP {exc.response.status_code} error for {request.url} "
            f"params={request.params} body={preview}"
        ) from exc

    except httpx.RequestError as exc:
        raise HttpClientError(
            f"Request failed for {request.url}: {exc}"
        ) from exc


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _looks_like_xml(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("<?xml") or (
        stripped.startswith("<")
        and not stripped.lower().startswith("<!doctype html")
        and not stripped.lower().startswith("<html")
    )


def _looks_like_html(text: str) -> bool:
    stripped = text.lstrip().lower()
    return (
        "<html" in stripped
        or "<body" in stripped
        or "<table" in stripped
        or "<div" in stripped
        or stripped.startswith("<!doctype html")
    )


def detect_response_format(response: httpx.Response) -> ResponseFormat:
    content_type = response.headers.get("content-type", "").lower()
    text = response.text.strip()

    # 1) content-type 우선
    if "json" in content_type:
        return "json"
    if "xml" in content_type:
        return "xml"
    if "html" in content_type:
        return "html"

    # 2) body heuristic fallback
    if _looks_like_json(text):
        return "json"
    if _looks_like_html(text):
        return "html"
    if _looks_like_xml(text):
        return "xml"

    return "text"


def parse_response_body(response: httpx.Response, fmt: ResponseFormat) -> Any:
    text = response.text

    if fmt == "json":
        try:
            return response.json()
        except ValueError as exc:
            preview = text[:300].replace("\n", " ")
            raise HttpClientError(
                f"Response looked like JSON but could not be parsed. "
                f"content-type={response.headers.get('content-type', '')} body={preview}"
            ) from exc

    if fmt == "xml":
        try:
            return xmltodict.parse(text)
        except Exception as exc:
            preview = text[:300].replace("\n", " ")
            raise HttpClientError(
                f"Response looked like XML but could not be parsed. "
                f"content-type={response.headers.get('content-type', '')} body={preview}"
            ) from exc

    if fmt == "html":
        # HTML은 우선 raw HTML + text 추출 둘 다 활용 가능하게 soup 반환
        try:
            soup = BeautifulSoup(text, "html.parser")
            return {
                "html": text,
                "text": soup.get_text("\n", strip=True),
            }
        except Exception as exc:
            preview = text[:300].replace("\n", " ")
            raise HttpClientError(
                f"Response looked like HTML but could not be parsed. "
                f"content-type={response.headers.get('content-type', '')} body={preview}"
            ) from exc

    # text
    return {"text": text}


def execute_api_request(request: RequestSpec) -> ParsedResponse:
    response = send_request(request)
    fmt = detect_response_format(response)
    parsed = parse_response_body(response, fmt)

    return ParsedResponse(
        format=fmt,
        content_type=response.headers.get("content-type", ""),
        text=response.text,
        parsed=parsed,
        status_code=response.status_code,
        url=str(response.url),
    )


def execute_json_request(request: RequestSpec) -> dict[str, Any]:
    """
    기존 코드와의 호환용.
    JSON 응답만 기대하는 기존 collector를 당장 다 못 바꿀 때 임시 사용.
    """
    result = execute_api_request(request)

    if result["format"] != "json":
        preview = result["text"][:300].replace("\n", " ")
        raise HttpClientError(
            f"Expected JSON response but got {result['format']}. "
            f"content-type={result['content_type']} body={preview}"
        )

    data = result["parsed"]
    if not isinstance(data, dict):
        raise HttpClientError("JSON response must be an object at top level")

    return data