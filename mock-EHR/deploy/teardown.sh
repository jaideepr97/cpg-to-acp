#!/usr/bin/env bash
# mock-EHR/deploy/teardown.sh — Remove mock-EHR deployment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
while [[ $# -gt 0 ]]; do
    case "$1" in --config) CONFIG_PATH="$2"; shift 2;; -h|--help) echo "Usage: mock-EHR/deploy/teardown.sh [--config <path>]"; exit 0;; *) shift;; esac
done

load_config "$CONFIG_PATH"
preflight

log_step "Tearing down mock-EHR (namespace=$NAMESPACE)"

helm uninstall cpg-mock-ehr -n "$NAMESPACE" 2>/dev/null || log "  cpg-mock-ehr not installed"

log_step "mock-EHR teardown complete"
