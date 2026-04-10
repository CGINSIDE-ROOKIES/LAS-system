from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel

from ..llm.factory import get_chat_model, get_structured_method
from ..observability import get_langchain_invoke_config

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
    if model_override is not None and hasattr(model_override, "invoke_structured"):
        return model_override.invoke_structured(  # type: ignore[return-value]
            profile=profile,
            prompt=prompt,
            payload=payload,
            schema=schema,
        )

    model = get_chat_model(profile=profile, model_override=model_override)
    method = get_structured_method(profile=profile)
    if method is not None:
        structured = model.with_structured_output(schema, method=method)
    else:
        structured = model.with_structured_output(schema)

    prompt_payload = f"{prompt}\n\nInput JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    invoke_config = get_langchain_invoke_config(
        config,
        metadata={"llm_profile": profile, "schema": schema.__name__},
    )
    if invoke_config:
        result = structured.invoke(prompt_payload, config=invoke_config)
    else:
        result = structured.invoke(prompt_payload)
    if isinstance(result, schema):
        return result
    return schema.model_validate(result)
