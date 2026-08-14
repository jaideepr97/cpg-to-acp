#!/usr/bin/env bash
# acp-writer/deploy/verify.sh — Verify acp-writer deployment
#
# Checks pods, images, supervision, and routed health.
# Runs in <30 seconds.
#
# Usage:
#   ./acp-writer/deploy/verify.sh [--config <path>]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck disable=SC1091
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; shift 2;;
        -h|--help) echo "Usage: acp-writer/deploy/verify.sh [--config <path>]"; exit 0;;
        *) shift;;
    esac
done

load_config "$CONFIG_PATH"

log_step "Verifying acp-writer deployment"

ERRORS=0

# Check sandbox pods
SANDBOXES=(sb-patient-data sb-llm-reasoning sb-decision-engine sb-fhir-generation sb-fhir-server)

for sb in "${SANDBOXES[@]}"; do
    # Pod exists and running?
    local_phase=$(oc get pod "$sb" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
    if [ "$local_phase" != "Running" ]; then
        echo "  ✗ $sb: not running (phase: $local_phase)"
        ERRORS=$((ERRORS + 1))
        continue
    fi

    # Correct image tag?
    local_image=$(oc get pod "$sb" -n "$NAMESPACE" -o jsonpath='{.spec.containers[0].image}' 2>/dev/null)
    if echo "$local_image" | grep -q ":${IMAGE_TAG}"; then
        echo "  ✓ $sb: Running, image :${IMAGE_TAG}"
    else
        echo "  ✗ $sb: wrong image tag (expected :${IMAGE_TAG}, got ${local_image})"
        ERRORS=$((ERRORS + 1))
    fi

    # Supervised? (uvicorn as user 'default', not root)
    local_user=$(oc exec "$sb" -n "$NAMESPACE" -- ps aux 2>/dev/null | grep uvicorn | grep -v grep | awk '{print $1}' | head -1)
    if [ "$local_user" = "default" ]; then
        echo "  ✓ $sb: supervised (user: default)"
    elif [ -n "$local_user" ]; then
        echo "  ✗ $sb: uvicorn running as '$local_user' (expected: default)"
        ERRORS=$((ERRORS + 1))
    else
        echo "  ✗ $sb: no uvicorn process found"
        ERRORS=$((ERRORS + 1))
    fi
done

# Routed health checks (via openshell-router)
echo ""
log "Routed health checks:"
for sb in "${SANDBOXES[@]}"; do
    local_code=$(oc exec deployment/openshell-router -n "$NAMESPACE" -- \
        curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -H "Host: ${sb}--http.openshell.localhost" \
        http://openshell-http:8080/health 2>/dev/null || echo "000")
    if [ "$local_code" = "200" ]; then
        echo "  ✓ $sb routed: HTTP 200"
    else
        echo "  ✗ $sb routed: HTTP $local_code"
        ERRORS=$((ERRORS + 1))
    fi
done

# Decision service (Helm-deployed, not sandboxed)
echo ""
log "Decision service:"
local_code=$(oc exec deployment/openshell-router -n "$NAMESPACE" -- \
    curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
    http://cpg-decision-svc-decision-service:8081/q/health/ready 2>/dev/null || echo "000")
if [ "$local_code" = "200" ]; then
    echo "  ✓ Kogito decision service: HTTP 200"
else
    echo "  ✗ Kogito decision service: HTTP $local_code"
    ERRORS=$((ERRORS + 1))
fi

# Summary
echo ""
if [ $ERRORS -eq 0 ]; then
    log "acp-writer verification: ALL CHECKS PASSED"
else
    log "acp-writer verification: $ERRORS CHECK(S) FAILED"
    exit 1
fi
