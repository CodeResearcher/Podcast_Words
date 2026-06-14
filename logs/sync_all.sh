#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
for p in logbuch_netzpolitik ukw neue_zwanziger; do
  echo "=== SYNC $p $(date -Iseconds) ==="
  $PY -m podcast_words sync --podcast "$p" --backfill --fallback --no-count
done
echo "=== FREAKSHOW FALLBACK $(date -Iseconds) ==="
$PY -m podcast_words sync --podcast freakshow --fallback --no-count
echo "=== DONE $(date -Iseconds) ==="
