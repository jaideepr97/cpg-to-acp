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

log_step "Deploying mock-EHR (namespace=$NAMESPACE, tag=$IMAGE_TAG)"

if [ "$SKIP_BUILD" = false ]; then
    log_step "Building mock-EHR images"
    "$SCRIPT_DIR/setup-openshift.sh" --namespace "$NAMESPACE" --branch "$GIT_BRANCH" --tag "$IMAGE_TAG"
else
    log "Skipping builds (--skip-build)"
fi

log_step "Deploying Helm chart"
helm upgrade --install cpg-mock-ehr "$SCRIPT_DIR/chart" \
    -n "$NAMESPACE" \
    --wait --timeout 300s 2>/dev/null || log "WARNING: mock-EHR helm install failed"

log_step "Verifying mock-EHR"
"$SCRIPT_DIR/verify.sh" --config "$CONFIG_PATH"

log_step "mock-EHR deployment complete"
