#!/usr/bin/env bash
# cpg-ingester/deploy/verify.sh — Verify cpg-ingester deployment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
TAG_OVERRIDE=""
while [[ $# -gt 0 ]]; do
    case "$1" in --config) CONFIG_PATH="$2"; shift 2;; --tag) TAG_OVERRIDE="$2"; shift 2;; *) shift;; esac
done
load_config "$CONFIG_PATH"
IMAGE_TAG=$(resolve_deploy_tag "cpg-ingester" "$TAG_OVERRIDE")

log_step "Verifying cpg-ingester deployment (tag: ${IMAGE_TAG})"
ERRORS=0
SANDBOXES=(sb-ingestion sb-llm-analysis sb-assembly sb-delivery)

for sb in "${SANDBOXES[@]}"; do
    local_phase=$(oc get pod "$sb" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
    if [ "$local_phase" != "Running" ]; then
        echo "  ✗ $sb: not running ($local_phase)"
        ERRORS=$((ERRORS + 1))
        continue
    fi

    local_image=$(oc get pod "$sb" -n "$NAMESPACE" -o jsonpath='{.spec.containers[0].image}' 2>/dev/null)
    if echo "$local_image" | grep -q ":${IMAGE_TAG}"; then
        echo "  ✓ $sb: Running, image :${IMAGE_TAG}"
    else
        echo "  ✗ $sb: wrong image (expected :${IMAGE_TAG})"
        ERRORS=$((ERRORS + 1))
    fi

    local_user=$(oc exec "$sb" -n "$NAMESPACE" -- ps aux 2>/dev/null | grep uvicorn | grep -v grep | awk '{print $1}' | head -1)
    if [ "$local_user" = "default" ]; then
        echo "  ✓ $sb: supervised (user: default)"
    else
        echo "  ✗ $sb: supervision check failed (user: ${local_user:-none})"
        ERRORS=$((ERRORS + 1))
    fi
done

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

echo ""
if [ $ERRORS -eq 0 ]; then
    log "cpg-ingester verification: ALL CHECKS PASSED"
else
    log "cpg-ingester verification: $ERRORS CHECK(S) FAILED"
    exit 1
fi
