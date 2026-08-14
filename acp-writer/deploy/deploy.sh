#!/usr/bin/env bash
# acp-writer/deploy/deploy.sh — Deploy acp-writer to OpenShift
#
# Builds images, deploys Helm chart, creates OpenShell sandboxes,
# applies SonataFlow workflow, and verifies.
#
# Usage:
#   ./acp-writer/deploy/deploy.sh [--skip-build] [--skip-openshell] [--tag <sha>] [--config <path>]
#   ./acp-writer/deploy/deploy.sh --help

set -euo pipefail
[ -n "${ZSH_VERSION:-}" ] && setopt SH_WORD_SPLIT

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck disable=SC1091
source "$REPO_ROOT/deploy/lib.sh"

SKIP_BUILD=false
SKIP_OPENSHELL=false
CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
TAG_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-build) SKIP_BUILD=true; shift;;
        --skip-openshell) SKIP_OPENSHELL=true; shift;;
        --config) CONFIG_PATH="$2"; shift 2;;
        --tag) TAG_OVERRIDE="$2"; shift 2;;
        -h|--help)
            echo "Usage: acp-writer/deploy/deploy.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-build      Skip image builds (use existing images)"
            echo "  --skip-openshell  Skip OpenShell sandbox creation (Helm-only deploy)"
            echo "  --tag <sha>       Override image tag (default: git HEAD SHA)"
            echo "  --config <path>   Path to cluster.env"
            exit 0;;
        *) shift;;
    esac
done

load_config "$CONFIG_PATH"
[ -n "$TAG_OVERRIDE" ] && IMAGE_TAG="$TAG_OVERRIDE"

preflight

LLM_BASE_URL="${MAAS_GATEWAY_URL}/${MAAS_ROUTE_SEGMENT}"
LLM_MODEL="${ACP_WRITER_LLM_MODEL:-$LLM_MODEL_DEFAULT}"

log_step "Deploying acp-writer (namespace=$NAMESPACE, tag=$IMAGE_TAG)"

# --- Step 1: Build images ---

if [ "$SKIP_BUILD" = false ]; then
    log_step "Building acp-writer images"

    # Ensure ImageStreams + BuildConfigs exist
    "$SCRIPT_DIR/setup-images.sh" --config "$CONFIG_PATH" --tag "$IMAGE_TAG"

    # Start all builds in parallel
    start_builds_parallel \
        acp-writer-patient-data \
        acp-writer-llm \
        acp-writer-decision \
        acp-writer-fhir-gen \
        acp-writer-fhir-srv \
        acp-writer-ui \
        acp-writer-mcp \
        decision-service

    # Prune old builds
    prune_builds "acp-writer"
    prune_builds "decision-service"
else
    log "Skipping builds (--skip-build)"
fi

# --- Step 2: Deploy Helm charts ---

log_step "Deploying Helm charts"

# Decision service
log "Installing decision-service chart (timeout 120s)..."
helm_start=$SECONDS
helm upgrade --install cpg-decision-svc "$SCRIPT_DIR/../decision-service/deploy/chart" \
    -n "$NAMESPACE" \
    --set image.tag="$IMAGE_TAG" \
    --wait --timeout 120s || { log "ERROR: decision-service helm install failed"; exit 1; }
log "  decision-service installed ($(( SECONDS - helm_start ))s)"

# acp-writer pod-split chart
log "Installing acp-writer chart (timeout 120s)..."
helm_start=$SECONDS
helm upgrade --install acp "$SCRIPT_DIR/chart-pods" \
    -n "$NAMESPACE" \
    --set image.namespace="$NAMESPACE" \
    --set mlflow.trackingUri="$MLFLOW_TRACKING_URI" \
    --set pods.patient-data.tag="$IMAGE_TAG" \
    --set pods.llm-reasoning.tag="$IMAGE_TAG" \
    --set pods.llm-reasoning.env.litellmUrl="$LLM_BASE_URL" \
    --set pods.llm-reasoning.env.llmModel="$LLM_MODEL" \
    --set pods.decision-engine.tag="$IMAGE_TAG" \
    --set pods.fhir-generation.tag="$IMAGE_TAG" \
    --set pods.fhir-generation.env.litellmUrl="$LLM_BASE_URL" \
    --set pods.fhir-generation.env.llmModel="$LLM_MODEL" \
    --set pods.fhir-server.tag="$IMAGE_TAG" \
    --set pods.ui.tag="$IMAGE_TAG" \
    --wait --timeout 120s || { log "ERROR: acp-writer helm install failed"; exit 1; }
log "  acp-writer installed ($(( SECONDS - helm_start ))s)"

# --- Step 3: Apply SonataFlow workflow ---

log_step "Applying SonataFlow workflow"
oc apply -f "$SCRIPT_DIR/orchestrator/acp-writer-workflow.yaml" -n "$NAMESPACE" 2>/dev/null \
    || log "WARNING: SonataFlow workflow apply failed"

# --- Step 4: Scale down Helm pods (OpenShell replaces them) ---

if [ "$SKIP_OPENSHELL" = false ]; then
    log_step "Scaling down Helm pods (OpenShell sandboxes will replace them)"
    for dep in acp-patient-data acp-llm-reasoning acp-decision-engine acp-fhir-generation acp-fhir-server; do
        oc scale deployment "$dep" --replicas=0 -n "$NAMESPACE" 2>/dev/null || true
    done

    # Create OpenShell sandboxes
    "$SCRIPT_DIR/openshell/deploy.sh" --config "$CONFIG_PATH" --tag "$IMAGE_TAG"
else
    log "Skipping OpenShell sandboxes (--skip-openshell)"
fi

# --- Step 5: Verify ---

log_step "Verifying acp-writer deployment"
"$SCRIPT_DIR/verify.sh" --config "$CONFIG_PATH"

# --- Step 6: Prune old image tags ---

for is in acp-writer-patient-data acp-writer-llm acp-writer-decision acp-writer-fhir-gen acp-writer-fhir-srv acp-writer-ui acp-writer-mcp decision-service; do
    prune_image_tags "$is" 5
done

log_step "acp-writer deployment complete"
