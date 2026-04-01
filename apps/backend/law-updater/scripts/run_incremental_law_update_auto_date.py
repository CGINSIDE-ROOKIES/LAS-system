from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEZONE = os.getenv("REG_DT_TIMEZONE", "Asia/Seoul")
DEFAULT_OFFSET_DAYS = int(os.getenv("REG_DT_OFFSET_DAYS", "0"))


def _resolve_reg_dt(*, timezone_name: str, days_offset: int) -> str:
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise SystemExit(f"Unsupported timezone: {timezone_name}") from exc

    target_date = datetime.now(tz).date() + timedelta(days=days_offset)
    return target_date.strftime("%Y%m%d")


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Run the incremental law updater with an auto-generated --reg-dt."
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"default: {DEFAULT_TIMEZONE}",
    )
    parser.add_argument(
        "--days-offset",
        type=int,
        default=DEFAULT_OFFSET_DAYS,
        help="0=today, -1=yesterday, 1=tomorrow",
    )
    return parser.parse_known_args()


def _has_reg_dt_argument(args: list[str]) -> bool:
    return any(arg == "--reg-dt" or arg.startswith("--reg-dt=") for arg in args)


def main() -> int:
    args, remaining = parse_args()
    remaining = [arg for arg in remaining if arg != "--"]

    command = [sys.executable, "scripts/run_incremental_law_update.py"]
    if not _has_reg_dt_argument(remaining):
        command.extend(
            [
                "--reg-dt",
                _resolve_reg_dt(
                    timezone_name=args.timezone,
                    days_offset=args.days_offset,
                ),
            ]
        )
    command.extend(remaining)

    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
