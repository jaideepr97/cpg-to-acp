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
log "Installing mock-EHR chart (timeout 300s)..."
helm_start=$SECONDS
helm upgrade --install cpg-mock-ehr "$SCRIPT_DIR/chart" \
    -n "$NAMESPACE" \
    --set image.namespace="$NAMESPACE" \
    --set postgres.image="${REGISTRY}/${NAMESPACE}/postgres-16:16" \
    --set redis.image="${REGISTRY}/${NAMESPACE}/redis-7:7" \
    --set medplumServer.image="${REGISTRY}/${NAMESPACE}/medplum-server-upstream:5.1.27" \
    --set medplumApp.image="${REGISTRY}/${NAMESPACE}/medplum-app-upstream:5.1.27" \
    --set mockEhrApp.image.tag="$IMAGE_TAG" \
    --set ipsViewer.image.tag="$IMAGE_TAG" \
    --set loader.image.tag="$IMAGE_TAG" \
    --wait --timeout 300s || { log "ERROR: mock-EHR helm install failed"; exit 1; }
log "  mock-EHR installed ($(( SECONDS - helm_start ))s)"

log_step "Verifying mock-EHR"
"$SCRIPT_DIR/verify.sh" --config "$CONFIG_PATH"

log_step "mock-EHR deployment complete"
