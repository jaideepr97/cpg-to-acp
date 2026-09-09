#!/usr/bin/env bash
# acp-writer/deploy/verify.sh — Verify acp-writer deployment
#
# Checks pods, images, supervision, and routed health.
# Retries sandbox checks for up to 90s to handle startup races.
#
# Usage:
#   ./acp-writer/deploy/verify.sh [--config <path>] [--tag <sha>]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck disable=SC1091
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
TAG_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; shift 2;;
        --tag) TAG_OVERRIDE="$2"; shift 2;;
        -h|--help) echo "Usage: acp-writer/deploy/verify.sh [--config <path>] [--tag <sha>]"; exit 0;;
        *) shift;;
    esac
done

load_config "$CONFIG_PATH"
IMAGE_TAG=$(resolve_deploy_tag "acp-writer" "$TAG_OVERRIDE")

log_step "Verifying acp-writer deployment (tag: ${IMAGE_TAG})"

ERRORS=0

# Sandbox checks with retry
SANDBOXES=(sb-patient-data sb-llm-reasoning sb-decision-engine sb-fhir-generation sb-fhir-server)
verify_sandboxes "$IMAGE_TAG" "${SANDBOXES[@]}" || ERRORS=$?

# Effective SonataFlow workflow in the running pod.
# The operator mounts the flow definition into the `acpwriter` pod; a re-apply
# that only changes the flow body does not always roll the pod, so an old
# definition can keep serving. Grep the pod's mounted flow for a current-version
# marker (F17 threads careplan_review_history through ComposePlan) to prove the
# restart landed the new definition.
echo ""
log "SonataFlow workflow (effective in pod):"
WF_MARKER="careplan_review_history"
if oc get deployment/acpwriter -n "$NAMESPACE" >/dev/null 2>&1; then
    if oc exec deployment/acpwriter -n "$NAMESPACE" -- \
        sh -c "grep -rql '$WF_MARKER' /home/kogito 2>/dev/null || grep -rql '$WF_MARKER' /deployments 2>/dev/null" \
        >/dev/null 2>&1; then
        echo "  ✓ acpwriter pod serving current workflow (marker '$WF_MARKER' present)"
    else
        echo "  ✗ acpwriter pod workflow is stale (marker '$WF_MARKER' missing) — rerun deploy or 'oc rollout restart deployment/acpwriter'"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "  ⚠ acpwriter deployment not found — skipping workflow marker check"
fi

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
