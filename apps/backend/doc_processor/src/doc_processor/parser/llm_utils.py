from __future__ import annotations

import json
import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel

from ..llm.factory import get_chat_model, get_structured_method
from ..observability import get_langchain_invoke_config

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def invoke_structured_model(
    *,
    profile: str,
    prompt: str,
    payload: dict[str, Any],
    schema: type[T],
    model_override: Any | None = None,
    config: Any | None = None,
) -> T:
    max_attempts = getattr(config, "llm_repair_max_attempts", 3) if config is not None else 3
    max_attempts = max(1, int(max_attempts or 1))
    current_prompt = prompt
    last_exc: Exception | None = None

    structured = None
    if model_override is None or not hasattr(model_override, "invoke_structured"):
        timeout_seconds = getattr(config, "llm_timeout_seconds", None) if config is not None else None
        model = get_chat_model(
            profile=profile,
            model_override=model_override,
            timeout_seconds=timeout_seconds,
        )
        method = get_structured_method(profile=profile)
        if method is not None:
            structured = model.with_structured_output(schema, method=method)
        else:
            structured = model.with_structured_output(schema)

    for attempt_no in range(1, max_attempts + 1):
        try:
            if model_override is not None and hasattr(model_override, "invoke_structured"):
                result = model_override.invoke_structured(
                    profile=profile,
                    prompt=current_prompt,
                    payload=payload,
                    schema=schema,
                )
            else:
                prompt_payload = _format_structured_prompt(current_prompt, payload)
                invoke_config = get_langchain_invoke_config(
                    config,
                    metadata={"llm_profile": profile, "schema": schema.__name__, "attempt": attempt_no},
                )
                if invoke_config:
                    result = structured.invoke(prompt_payload, config=invoke_config)
                else:
                    result = structured.invoke(prompt_payload)
            if isinstance(result, schema):
                return result
            return schema.model_validate(result)
        except Exception as exc:
            last_exc = exc
            if attempt_no >= max_attempts:
                break
            delay = _retry_delay(getattr(config, "llm_retry_base_delay_sec", 1.0), attempt_no)
            logger.warning(
                "Structured LLM invocation failed; retrying "
                "(profile=%s, schema=%s, attempt=%s/%s, delay_sec=%.2f, error=%s)",
                profile,
                schema.__name__,
                attempt_no,
                max_attempts,
                delay,
                _truncate_text(str(exc), 1000),
            )
            if delay > 0:
                time.sleep(delay)
            current_prompt = _build_structured_repair_prompt(
                prompt,
                schema=schema,
                error=exc,
                next_attempt=attempt_no + 1,
                max_attempts=max_attempts,
            )
    if last_exc is not None:
        logger.warning(
            "Structured LLM invocation failed after max attempts "
            "(profile=%s, schema=%s, attempts=%s, error=%s)",
            profile,
            schema.__name__,
            max_attempts,
            _truncate_text(str(last_exc), 1000),
        )
        raise last_exc
    raise RuntimeError("Structured model invocation failed without an exception.")


def _format_structured_prompt(prompt: str, payload: dict[str, Any]) -> str:
    return f"{prompt}\n\nInput JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"


def _build_structured_repair_prompt(
    base_prompt: str,
    *,
    schema: type[BaseModel],
    error: Exception,
    next_attempt: int,
    max_attempts: int,
) -> str:
    return "\n\n".join(
        [
            base_prompt,
            "[repair_instruction]",
            (
                "Your previous response failed structured-output validation. "
                f"Return only data that conforms to the {schema.__name__} schema."
            ),
            f"This is attempt {next_attempt} of {max_attempts}.",
            "[validation_failure]",
            _truncate_text(str(error), 3000),
        ]
    )


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}... [truncated]"


def _retry_delay(base_delay_sec: float, attempt_no: int) -> float:
    return min(float(base_delay_sec or 0.0) * (2 ** (attempt_no - 1)), 30.0)
