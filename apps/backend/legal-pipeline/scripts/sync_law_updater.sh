#!/usr/bin/env bash
# legal-pipeline/src/export → law-updater/src/export 동기화
# 실행: bash scripts/sync_law_updater.sh (repo 루트 또는 legal-pipeline 루트 어디서든 가능)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
SRC="$REPO_ROOT/apps/backend/legal-pipeline/src/export"
DST="$REPO_ROOT/apps/backend/law-updater/src/export"

FILES=(
  legal_case_dataset_builder.py
  legal_case_relation_builder.py
  dataset_builder.py
  legal_relation_builder.py
)

echo "=== law-updater 동기화 시작 ==="
for f in "${FILES[@]}"; do
  cp "$SRC/$f" "$DST/$f"
  echo "synced: $f"
done

echo ""
echo "=== diff 결과 (차이 없으면 정상) ==="
for f in "${FILES[@]}"; do
  diff "$SRC/$f" "$DST/$f" && echo "$f: identical" || echo "$f: DIFF 존재"
done
