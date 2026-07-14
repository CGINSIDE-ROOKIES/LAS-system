from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Iterator


def _safe_filename(text: str) -> str:
    text = text.strip()
    text = text.replace("ㆍ", "·")  # U+318D (Korean interpunct) → U+00B7 (middle dot), both → _
    text = re.sub(r"[^\w가-힣.-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "unnamed"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"JSON payload must be an object: {path}")

    return data


def write_jsonl(rows: Iterable[dict[str, Any]], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    write_jsonl(rows, path)



def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue

            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"JSONL row must be an object: {path}:{line_no}")
            yield data
