#!/usr/bin/env bash
# Benchmark runner wrapper (RHAIENG-6461).
#
# Usage:
#   ./run-benchmark.sh --synthetic   # CI-safe, no network
#   ./run-benchmark.sh --real        # scores downloaded real CPGs (local only)
#   ./run-benchmark.sh --all
#
# Uses the cpg-ingester venv (where Docling is installed). Override the
# interpreter with BENCH_PYTHON=/path/to/python if your venv lives elsewhere.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# cpg-ingester/tests/benchmarks/parsing -> cpg-ingester
CPG_INGESTER_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PY="${BENCH_PYTHON:-${CPG_INGESTER_DIR}/.venv/bin/python}"

if [[ ! -x "${PY}" ]]; then
  echo "ERROR: Python interpreter not found at ${PY}" >&2
  echo "Set BENCH_PYTHON to your venv python, or create the venv." >&2
  exit 1
fi

exec "${PY}" "${SCRIPT_DIR}/run_benchmark.py" "$@"
