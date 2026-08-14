#!/usr/bin/env bash
# mock-EHR/deploy/verify.sh — Verify mock-EHR deployment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
while [[ $# -gt 0 ]]; do
    case "$1" in --config) CONFIG_PATH="$2"; shift 2;; *) shift;; esac
done
load_config "$CONFIG_PATH"

log_step "Verifying mock-EHR deployment"
ERRORS=0

# Check key Medplum pods
for dep in cpg-mock-ehr-medplum-server cpg-mock-ehr-postgres cpg-mock-ehr-redis; do
    ready=$(oc get deployment "$dep" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [ "${ready:-0}" -ge 1 ]; then
        echo "  ✓ $dep: ready"
    else
        echo "  ✗ $dep: not ready"
        ERRORS=$((ERRORS + 1))
    fi
done

# Medplum health
local_code=$(oc exec deployment/cpg-mock-ehr-medplum-server -n "$NAMESPACE" -- \
    curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
    http://localhost:8103/healthcheck 2>/dev/null || echo "000")
if [ "$local_code" = "200" ]; then
    echo "  ✓ Medplum health: HTTP 200"
else
    echo "  ✗ Medplum health: HTTP $local_code"
    ERRORS=$((ERRORS + 1))
fi

echo ""
if [ $ERRORS -eq 0 ]; then
    log "mock-EHR verification: ALL CHECKS PASSED"
else
    log "mock-EHR verification: $ERRORS CHECK(S) FAILED"
    exit 1
fi
