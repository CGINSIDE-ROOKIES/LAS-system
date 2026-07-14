from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.export.law_graph_exporter import write_law_graph_export


def main() -> None:
    parser = argparse.ArgumentParser(description="Export law/article graph JSONL files from dataset outputs.")
    parser.add_argument("--output-dir", default="data/handoff/law_graph_v1")
    parser.add_argument("--legal-corpus-path", default="data/dataset/legal_corpus.jsonl")
    parser.add_argument("--legal-relations-path", default="data/dataset/legal_relations.jsonl")
    args = parser.parse_args()

    manifest = write_law_graph_export(
        args.output_dir,
        legal_corpus_path=args.legal_corpus_path,
        legal_relations_path=args.legal_relations_path,
    )
    print(manifest)


if __name__ == "__main__":
    main()
