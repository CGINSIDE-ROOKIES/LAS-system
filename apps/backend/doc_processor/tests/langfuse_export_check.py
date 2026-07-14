from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

from doc_processor import ParserConfig, run_parser
from doc_processor.env import ensure_local_env_loaded
from doc_processor.observability import flush_langfuse, langfuse_callback_context
from doc_processor.observability.langfuse import langfuse_enabled
from doc_processor.parser_types import RelevanceMode


RELEVANT_ENV_KEYS = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "LANGFUSE_TIMEOUT",
    "LANGFUSE_FLUSH_AT",
    "LANGFUSE_FLUSH_INTERVAL",
    "LANGFUSE_TRACING_ENABLED",
    "LANGFUSE_DEBUG",
    "LANGFUSE_SAMPLE_RATE",
)

PARSER_PROFILES = {
    "minimal": {
        "relevance_mode": RelevanceMode.DISABLED,
        "boundary_review_enabled": False,
        "label_review_enabled": False,
        "max_concurrent_workers": 1,
    },
    "notebook": {
        "relevance_mode": RelevanceMode.KEYWORD_ONLY,
        "boundary_review_enabled": True,
        "label_review_enabled": True,
        "max_concurrent_workers": 10,
    },
}


def _mask_secret(value: str | None) -> str:
    if value is None:
        return "<unset>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_parser_target() -> Path:
    candidate = _repo_root() / "tests" / "doc_samples" / "표준계약서모음(hwp-hwpx)" / "05. 대중문화예술인 표준전속계약서(1).hwp"
    if candidate.exists():
        return candidate
    fallback = _repo_root() / "tests" / "doc_samples" / "new_test" / "02. 청소년 대중문화예술인 표준 부속합의서.hwpx"
    return fallback


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose Langfuse export issues without going through the full notebook flow.",
    )
    parser.add_argument(
        "--mode",
        choices=("direct", "callback", "parser", "all"),
        default="all",
        help="Which export path to exercise.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=10,
        help="How many direct/callback traces to emit.",
    )
    parser.add_argument(
        "--payload-size",
        type=int,
        default=200,
        help="Approximate message payload size for callback traces.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=_default_parser_target(),
        help="Target document for --mode parser or --mode all.",
    )
    parser.add_argument(
        "--parser-profile",
        choices=tuple(PARSER_PROFILES),
        default="minimal",
        help="Parser config profile for --mode parser or --mode all.",
    )
    parser.add_argument(
        "--langfuse-timeout",
        type=int,
        default=None,
        help="Override LANGFUSE_TIMEOUT for this process.",
    )
    parser.add_argument(
        "--langfuse-flush-at",
        type=int,
        default=None,
        help="Override LANGFUSE_FLUSH_AT for this process.",
    )
    parser.add_argument(
        "--langfuse-flush-interval",
        type=float,
        default=None,
        help="Override LANGFUSE_FLUSH_INTERVAL for this process.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Set LANGFUSE_DEBUG=true for this process.",
    )
    return parser.parse_args()


def _apply_env_overrides(args: argparse.Namespace) -> None:
    if args.langfuse_timeout is not None:
        os.environ["LANGFUSE_TIMEOUT"] = str(args.langfuse_timeout)
    if args.langfuse_flush_at is not None:
        os.environ["LANGFUSE_FLUSH_AT"] = str(args.langfuse_flush_at)
    if args.langfuse_flush_interval is not None:
        os.environ["LANGFUSE_FLUSH_INTERVAL"] = str(args.langfuse_flush_interval)
    if args.debug:
        os.environ["LANGFUSE_DEBUG"] = "true"


def _print_env_summary() -> None:
    ensure_local_env_loaded()
    print("Langfuse environment")
    for key in RELEVANT_ENV_KEYS:
        value = os.getenv(key)
        if key.endswith(("PUBLIC_KEY", "SECRET_KEY")):
            display = "<redacted>" if value else "<unset>"
        else:
            display = value or "<unset>"
        print(f"  {key}={display}")


def _base_config() -> ParserConfig:
    return ParserConfig(
        langfuse_enabled=True,
        langfuse_flush_at_end=False,
        console_logging_enabled=True,
        console_log_level="INFO",
    )


def _check_langfuse_ready(config: ParserConfig) -> bool:
    try:
        return langfuse_enabled(config)
    except Exception as exc:
        print(f"Langfuse configuration error: {exc}", file=sys.stderr)
        return False


def _flush(config: ParserConfig, *, label: str) -> None:
    started = time.perf_counter()
    flush_langfuse(config)
    elapsed = time.perf_counter() - started
    print(f"[{label}] flush complete in {elapsed:.2f}s")


def _run_direct_mode(config: ParserConfig, *, repeat: int) -> None:
    from langfuse import get_client

    client = get_client()
    print(f"[direct] emitting {repeat} direct spans")
    for index in range(repeat):
        with client.start_as_current_observation(
            name="doc_processor.langfuse_export_check.direct",
            as_type="span",
            input={"mode": "direct", "iteration": index + 1},
            metadata={"script": "tests/langfuse_export_check.py"},
        ):
            pass
    _flush(config, label="direct")


def _run_callback_mode(config: ParserConfig, *, repeat: int, payload_size: int) -> None:
    from langchain_core.runnables import RunnableLambda

    payload = "x" * max(payload_size, 1)
    runnable = RunnableLambda(
        lambda item: {
            "ok": True,
            "iteration": item["iteration"],
            "message_length": len(item["message"]),
        }
    )

    print(f"[callback] emitting {repeat} callback traces with payload_size={payload_size}")
    for index in range(repeat):
        with langfuse_callback_context(
            config,
            source=f"tests/langfuse_export_check.py:callback:{index + 1}",
        ) as invoke_config:
            call_config = dict(invoke_config)
            call_config["run_name"] = "doc_processor.langfuse_export_check.callback"
            runnable.invoke(
                {"iteration": index + 1, "message": payload},
                config=call_config,
            )
    _flush(config, label="callback")


def _run_parser_mode(config: ParserConfig, *, target: Path, parser_profile: str) -> None:
    profile_updates = PARSER_PROFILES[parser_profile]
    parser_config = config.model_copy(update=profile_updates)
    print(
        f"[parser] running parser graph against {target} "
        f"with profile={parser_profile} "
        f"boundary_review_enabled={parser_config.boundary_review_enabled} "
        f"label_review_enabled={parser_config.label_review_enabled} "
        f"max_concurrent_workers={parser_config.max_concurrent_workers}"
    )
    started = time.perf_counter()
    result = run_parser(target, config=parser_config)
    elapsed = time.perf_counter() - started
    print(
        "[parser] run complete in "
        f"{elapsed:.2f}s accepted={result.parser_result.accepted if result.parser_result else None} "
        f"clauses={result.parser_result.clause_count if result.parser_result else None}"
    )
    _flush(parser_config, label="parser")


def main() -> int:
    args = _parse_args()
    _apply_env_overrides(args)
    _print_env_summary()

    config = _base_config()
    if not _check_langfuse_ready(config):
        return 2

    modes = ("direct", "callback", "parser") if args.mode == "all" else (args.mode,)
    failures: list[str] = []

    for mode in modes:
        try:
            if mode == "direct":
                _run_direct_mode(config, repeat=args.repeat)
            elif mode == "callback":
                _run_callback_mode(config, repeat=args.repeat, payload_size=args.payload_size)
            elif mode == "parser":
                _run_parser_mode(config, target=args.target, parser_profile=args.parser_profile)
            else:  # pragma: no cover
                raise ValueError(f"Unsupported mode: {mode}")
        except Exception as exc:
            failures.append(f"{mode}: {exc}")
            print(f"[{mode}] failed: {exc}", file=sys.stderr)
            traceback.print_exc()

    try:
        from langfuse import get_client

        get_client().shutdown()
        print("[shutdown] Langfuse client shutdown complete")
    except Exception as exc:
        failures.append(f"shutdown: {exc}")
        print(f"[shutdown] failed: {exc}", file=sys.stderr)
        traceback.print_exc()

    if failures:
        print("\nSummary: failures detected")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("\nSummary: all selected Langfuse export checks completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
