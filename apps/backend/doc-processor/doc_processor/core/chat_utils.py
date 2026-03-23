def trim_chat_history(
    chat_history: list[tuple[str, str]],
    system_prompt: str,
    max_tokens: int = 4096,
    reserved_tokens: int = 512,
    chars_per_token: float = 2.5,
) -> list[tuple[str, str]]:
    """Trim chat history to fit within token budget.

    Walks backwards through history keeping the most recent messages that fit.
    reserved_tokens is headroom left for the model's response.
    chars_per_token=2.5 is a conservative estimate for Korean text.
    """
    budget = (max_tokens - reserved_tokens) * chars_per_token
    budget -= len(system_prompt)

    kept = []
    for role, content in reversed(chat_history):
        budget -= len(content)
        if budget < 0:
            break
        kept.append((role, content))

    return list(reversed(kept))
