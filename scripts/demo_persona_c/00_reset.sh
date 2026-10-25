#!/usr/bin/env bash
# Limpieza pre-demo: borra DB + uploads, re-siembra sitios.
# Necesario para empezar cada toma desde estado verde limpio.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${BACKEND_DIR:-${REPO_ROOT}/backend}"

cd "$BACKEND_DIR"
rm -f data/edge.db data/central.db data/jalrekha.db
rm -rf data/uploads/* 2>/dev/null || true
PYTHONPATH=src python3 -m jalrekha.scripts.seed
echo "[reset] DB re-seeded. Listo para grabar."
