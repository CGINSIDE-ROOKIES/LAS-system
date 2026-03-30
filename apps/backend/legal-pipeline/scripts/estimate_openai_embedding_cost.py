from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.io_utils import _iter_jsonl

APPENDIX_VECTOR_PLACEHOLDER = "[NO_APPENDIX_LINKED]"
DEFAULT_MODEL_NAME = "text-embedding-3-large"
DEFAULT_PRICE_PER_1M_TOKENS = 0.13
DEFAULT_CHARS_PER_TOKEN = 2.5


def _load_token_counter(
    *,
    model_name: str,
    allow_rough_estimate: bool,
    chars_per_token: float,
) -> tuple[Callable[[str], int], str]:
    try:
        import tiktoken  # type: ignore
    except ImportError:
        if not allow_rough_estimate:
            raise RuntimeError(
                "tiktoken is not installed. Install dependencies or rerun with --allow-rough-estimate."
            )

        def rough_counter(text: str) -> int:
            stripped = str(text or "").strip()
            if not stripped:
                return 0
            return max(1, int(round(len(stripped) / chars_per_token)))

        return rough_counter, "rough_chars_per_token"

    try:
        encoding = tiktoken.encoding_for_model(model_name)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    def token_counter(text: str) -> int:
        stripped = str(text or "").strip()
        if not stripped:
            return 0
        return len(encoding.encode(stripped))

    return token_counter, "tiktoken"


def _summarize_dataset(
    dataset_dir: Path,
    *,
    count_tokens: Callable[[str], int],
) -> dict:
    summary = {
        "law_article_body": {"rows": 0, "tokens": 0},
        "law_article_appendix": {"rows": 0, "tokens": 0},
        "legal_case": {"rows": 0, "tokens": 0},
        "legal_relation": {"rows": 0, "tokens": 0},
    }

    for row in _iter_jsonl(dataset_dir / "legal_corpus.jsonl"):
        doc_type = str(row.get("doc_type") or "").strip()
        text = str(row.get("text") or "").strip()

        if doc_type == "law":
            if text:
                summary["law_article_body"]["rows"] += 1
                summary["law_article_body"]["tokens"] += count_tokens(text)

            appendix_text = str(row.get("appendix_vector_text") or APPENDIX_VECTOR_PLACEHOLDER).strip()
            if appendix_text:
                summary["law_article_appendix"]["rows"] += 1
                summary["law_article_appendix"]["tokens"] += count_tokens(appendix_text)
            continue

        if text:
            summary["legal_case"]["rows"] += 1
            summary["legal_case"]["tokens"] += count_tokens(text)

    for row in _iter_jsonl(dataset_dir / "legal_relations.jsonl"):
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        summary["legal_relation"]["rows"] += 1
        summary["legal_relation"]["tokens"] += count_tokens(text)

    total_rows = sum(item["rows"] for item in summary.values())
    total_tokens = sum(item["tokens"] for item in summary.values())
    summary["total"] = {
        "rows": total_rows,
        "tokens": total_tokens,
    }
    return summary


def _build_cost_summary(
    dataset_dir: Path,
    *,
    model_name: str,
    price_per_1m_tokens: float,
    allow_rough_estimate: bool,
    chars_per_token: float,
) -> dict:
    count_tokens, token_counter_mode = _load_token_counter(
        model_name=model_name,
        allow_rough_estimate=allow_rough_estimate,
        chars_per_token=chars_per_token,
    )
    breakdown = _summarize_dataset(dataset_dir, count_tokens=count_tokens)
    total_tokens = breakdown["total"]["tokens"]
    estimated_cost_usd = (total_tokens / 1_000_000) * price_per_1m_tokens

    return {
        "dataset_dir": str(dataset_dir),
        "model_name": model_name,
        "token_counter_mode": token_counter_mode,
        "price_per_1m_tokens_usd": price_per_1m_tokens,
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "breakdown": breakdown,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estimate OpenAI embedding token usage and cost")
    parser.add_argument("--dataset-dir", type=Path, default=Path("data/dataset"))
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--price-per-1m-tokens", type=float, default=DEFAULT_PRICE_PER_1M_TOKENS)
    parser.add_argument("--allow-rough-estimate", action="store_true")
    parser.add_argument("--chars-per-token", type=float, default=DEFAULT_CHARS_PER_TOKEN)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = _build_cost_summary(
        args.dataset_dir,
        model_name=args.model,
        price_per_1m_tokens=args.price_per_1m_tokens,
        allow_rough_estimate=args.allow_rough_estimate,
        chars_per_token=args.chars_per_token,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
