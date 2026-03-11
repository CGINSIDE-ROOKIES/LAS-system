from __future__ import annotations

from typing import Any

import httpx

from src.models.registry_models import RequestSpec



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


def execute_json_request(request: RequestSpec) -> dict[str, Any]:
    response = send_request(request)

    try:
        data = response.json()
    except ValueError as exc:
        preview = response.text[:300].replace("\n", " ")
        content_type = response.headers.get("content-type", "")
        raise HttpClientError(
            f"Response was not valid JSON. content-type={content_type} body={preview}"
        ) from exc

    if not isinstance(data, dict):
        raise HttpClientError("JSON response must be an object at top level")

    return data