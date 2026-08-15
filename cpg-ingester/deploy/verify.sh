#!/usr/bin/env bash
# cpg-ingester/deploy/verify.sh — Verify cpg-ingester deployment
#
# Checks pods, images, supervision, routed health, and BFF dependencies.
# Retries sandbox checks for up to 90s to handle startup races.
#
# Usage:
#   ./cpg-ingester/deploy/verify.sh [--config <path>] [--tag <sha>]

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

# Sandbox checks with retry
SANDBOXES=(sb-ingestion sb-llm-analysis sb-assembly sb-delivery)
verify_sandboxes "$IMAGE_TAG" "${SANDBOXES[@]}" || ERRORS=$?

# BFF health — must have minio and sonataflow connected (Fix 4)
echo ""
log "BFF dependency check:"
bff_health=$(oc exec deployment/cpg-ingester-bff -n "$NAMESPACE" -- \
    curl -s --max-time 5 http://localhost:8080/health 2>/dev/null || echo "{}")
bff_minio=$(echo "$bff_health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('minio',False))" 2>/dev/null || echo "False")
bff_sonataflow=$(echo "$bff_health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('sonataflow',False))" 2>/dev/null || echo "False")

if [ "$bff_minio" = "True" ] && [ "$bff_sonataflow" = "True" ]; then
    echo "  ✓ BFF: minio=true, sonataflow=true"
else
    echo "  ✗ BFF dependencies missing: $bff_health"
    ERRORS=$((ERRORS + 1))
fi

echo ""
if [ $ERRORS -eq 0 ]; then
    log "cpg-ingester verification: ALL CHECKS PASSED"
else
    log "cpg-ingester verification: $ERRORS CHECK(S) FAILED"
    exit 1
fi
