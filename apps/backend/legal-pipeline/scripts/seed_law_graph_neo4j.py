from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.env import load_backend_env
from src.export.law_graph_neo4j_seed import build_seed_manifest, iter_seed_operations, load_graph_seed_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed exported law graph JSONL rows into Neo4j.")
    parser.add_argument("--graph-dir", default="data/handoff/law_graph_v1")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def _batched(rows: list[dict], size: int):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _load_driver():
    try:
        from neo4j import GraphDatabase  # type: ignore
    except ImportError as exc:
        raise RuntimeError("neo4j package is required to seed the graph. Add it to the project dependencies first.") from exc

    neo4j_uri = os.getenv("NEO4J_URI") or None
    neo4j_username = os.getenv("NEO4J_USER") or None
    neo4j_password = os.getenv("NEO4J_PASSWORD") or None
    if not neo4j_uri or not neo4j_username or not neo4j_password:
        raise RuntimeError("NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD must be configured.")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_username, neo4j_password))


def main() -> None:
    load_backend_env()
    args = parse_args()
    rows = load_graph_seed_rows(args.graph_dir)
    manifest = build_seed_manifest(rows)

    if args.dry_run:
        print(manifest)
        return

    driver = _load_driver()
    neo4j_database = os.getenv("NEO4J_DATABASE") or None
    with driver.session(database=neo4j_database) as session:
        session.run("CREATE CONSTRAINT law_uid_unique IF NOT EXISTS FOR (n:Law) REQUIRE n.law_uid IS UNIQUE")
        session.run("CREATE CONSTRAINT article_uid_unique IF NOT EXISTS FOR (n:Article) REQUIRE n.article_uid IS UNIQUE")
        session.run("CREATE CONSTRAINT case_canonical_case_id_unique IF NOT EXISTS FOR (n:Case) REQUIRE n.canonical_case_id IS UNIQUE")
        for query, payload_rows in iter_seed_operations(rows):
            for batch in _batched(payload_rows, args.batch_size):
                if not batch:
                    continue
                session.run(query, rows=batch)

    driver.close()
    print(manifest)


if __name__ == "__main__":
    main()
