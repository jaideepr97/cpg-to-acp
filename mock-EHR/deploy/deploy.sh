#!/usr/bin/env bash
# mock-EHR/deploy/deploy.sh — Deploy mock-EHR (Medplum) to OpenShift
#
# No OpenShell sandboxes — Medplum runs as standard Helm-deployed pods.
#
# Usage:
#   ./mock-EHR/deploy/deploy.sh [--skip-build] [--tag <sha>] [--config <path>]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$REPO_ROOT/deploy/lib.sh"

SKIP_BUILD=false
CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
TAG_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-build) SKIP_BUILD=true; shift;;
        --config) CONFIG_PATH="$2"; shift 2;;
        --tag) TAG_OVERRIDE="$2"; shift 2;;
        -h|--help)
            echo "Usage: mock-EHR/deploy/deploy.sh [--skip-build] [--tag <sha>] [--config <path>]"
            exit 0;;
        *) shift;;
    esac
done

load_config "$CONFIG_PATH"
[ -n "$TAG_OVERRIDE" ] && IMAGE_TAG="$TAG_OVERRIDE"
preflight

REGISTRY="image-registry.openshift-image-registry.svc:5000"

log_step "Deploying mock-EHR (namespace=$NAMESPACE, tag=$IMAGE_TAG)"

if [ "$SKIP_BUILD" = false ]; then
    log_step "Building mock-EHR images"
    "$SCRIPT_DIR/setup-openshift.sh" \
        --namespace "$NAMESPACE" \
        --branch "$GIT_BRANCH" \
        --tag "$IMAGE_TAG"
else
    log "Skipping builds (--skip-build)"
fi

log_step "Deploying Helm chart"

# Check if medplum-user-credentials secret exists → enable loader
LOADER_ENABLED="false"
if oc get secret medplum-user-credentials -n "$NAMESPACE" &>/dev/null; then
    LOADER_ENABLED="true"
    log "  medplum-user-credentials secret found — loader job enabled"
else
    log "  medplum-user-credentials secret not found — loader job disabled"
fi

log "Installing mock-EHR chart (timeout 300s)..."
helm_start=$SECONDS
helm upgrade --install cpg-mock-ehr "$SCRIPT_DIR/chart" \
    -n "$NAMESPACE" \
    --set image.namespace="$NAMESPACE" \
    --set clusterDomain="$CLUSTER_DOMAIN" \
    --set postgres.image="${REGISTRY}/${NAMESPACE}/postgres-16:16" \
    --set redis.image="${REGISTRY}/${NAMESPACE}/redis-7:7" \
    --set medplumServer.image="${REGISTRY}/${NAMESPACE}/medplum-server-upstream:5.1.27" \
    --set medplumApp.image="${REGISTRY}/${NAMESPACE}/medplum-app-upstream:5.1.27" \
    --set mockEhrApp.image.tag="$IMAGE_TAG" \
    --set loader.enabled="$LOADER_ENABLED" \
    --set loader.image.tag="$IMAGE_TAG" \
    --wait --timeout 300s || { log "ERROR: mock-EHR helm install failed"; exit 1; }
log "  mock-EHR installed ($(( SECONDS - helm_start ))s)"

# If the loader ran, restart the acp-writer UI to pick up the SMART credentials Secret
if [ "$LOADER_ENABLED" = "true" ]; then
    log "Waiting for loader job to complete..."
    oc wait --for=condition=Complete job -l app.kubernetes.io/instance=cpg-mock-ehr -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
    if oc get secret smart-client-credentials -n "$NAMESPACE" &>/dev/null; then
        log "SMART credentials Secret found — restarting acp-writer UI to mount credentials"
        oc rollout restart deployment/acp-ui -n "$NAMESPACE" 2>/dev/null || true
        oc rollout status deployment/acp-ui -n "$NAMESPACE" --timeout=60s 2>/dev/null || true
    else
        log "WARNING: SMART credentials Secret not found after loader — SMART launch will fail"
    fi
fi

log_step "Deploying MCP server"
render_template "$SCRIPT_DIR/mcp/mock-ehr-mcp.yaml.tmpl" "$REPO_ROOT/deploy/.rendered/mock-ehr-mcp.yaml"
oc apply -f "$REPO_ROOT/deploy/.rendered/mock-ehr-mcp.yaml" -n "$NAMESPACE" 2>/dev/null \
    || log "WARNING: MCP server deploy failed"
oc apply -f "$SCRIPT_DIR/mcp/registration.yaml" -n "$NAMESPACE" 2>/dev/null \
    || log "WARNING: MCP registration apply failed"

save_deploy_state "mock-ehr" "$IMAGE_TAG"

log_step "Verifying mock-EHR"
"$SCRIPT_DIR/verify.sh" --config "$CONFIG_PATH"

log_step "mock-EHR deployment complete"
