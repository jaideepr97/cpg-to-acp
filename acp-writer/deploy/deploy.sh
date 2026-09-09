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
            echo "  --skip-openshell  Deploy Helm-managed pods instead of OpenShell sandboxes"
            echo "  --tag <sha>       Override image tag (default: git HEAD SHA)"
            echo "  --config <path>   Path to cluster.env"
            exit 0;;
        *) shift;;
    esac
done

load_config "$CONFIG_PATH"
[ -n "$TAG_OVERRIDE" ] && IMAGE_TAG="$TAG_OVERRIDE"

preflight

if [ -n "${MAAS_ROUTE_SEGMENT:-}" ]; then
    LLM_BASE_URL="${MAAS_GATEWAY_URL}/${MAAS_ROUTE_SEGMENT}"
else
    LLM_BASE_URL="${MAAS_GATEWAY_URL}"
fi
LLM_MODEL="${ACP_WRITER_LLM_MODEL:-$LLM_MODEL_DEFAULT}"

OPENSHELL_MODE="true"
if [ "$SKIP_OPENSHELL" = true ]; then
    OPENSHELL_MODE="false"
fi

log_step "Deploying acp-writer (namespace=$NAMESPACE, tag=$IMAGE_TAG, openshellMode=$OPENSHELL_MODE)"

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
        acp-writer-bff \
        acp-writer-ui \
        acp-writer-mcp \
        decision-service

    # Prune old builds
    prune_builds "acp-writer"
    prune_builds "decision-service"
else
    log "Skipping builds (--skip-build)"
fi

# --- Step 2: Create OpenShell sandboxes ---
# Sandboxes must be running before the Helm chart deploys the BFF, because the
# BFF's startup hook loads artifacts from MinIO and pushes them to the backend
# sandboxes (llm-reasoning, decision-engine). If sandboxes aren't up yet, those
# registrations silently fail with 404.

if [ "$SKIP_OPENSHELL" = false ]; then
    "$SCRIPT_DIR/openshell/deploy.sh" --config "$CONFIG_PATH" --tag "$IMAGE_TAG"
else
    log "Skipping OpenShell sandboxes (--skip-openshell)"
fi

# --- Step 3: Deploy Helm charts ---

log_step "Deploying Helm charts"

# Decision service
log "Installing decision-service chart (timeout 120s)..."
helm_start=$SECONDS
helm upgrade --install cpg-decision-svc "$SCRIPT_DIR/../decision-service/deploy/chart" \
    -n "$NAMESPACE" \
    --set image.tag="$IMAGE_TAG" \
    --wait --timeout 300s || { log "ERROR: decision-service helm install failed"; exit 1; }
log "  decision-service installed ($(( SECONDS - helm_start ))s)"

# acp-writer pod-split chart
log "Installing acp-writer chart (timeout 120s)..."
helm_start=$SECONDS
helm upgrade --install acp "$SCRIPT_DIR/chart-pods" \
    -n "$NAMESPACE" \
    --set openshellMode="$OPENSHELL_MODE" \
    --set mlflow.trackingUri="$MLFLOW_TRACKING_URI" \
    --set pods.patient-data.tag="$IMAGE_TAG" \
    --set pods.llm-reasoning.tag="$IMAGE_TAG" \
    --set pods.llm-reasoning.env.litellmUrl="$LLM_BASE_URL" \
    --set pods.llm-reasoning.env.llmModel="$LLM_MODEL" \
    --set pods.llm-reasoning.env.llmRequestTimeout="${LLM_REQUEST_TIMEOUT:-600}" \
    --set pods.llm-reasoning.env.embeddingProvider="${EMBEDDING_PROVIDER:-openai}" \
    --set pods.llm-reasoning.env.embeddingModel="${EMBEDDING_MODEL:-text-embedding-3-small}" \
    --set pods.decision-engine.tag="$IMAGE_TAG" \
    --set pods.fhir-generation.tag="$IMAGE_TAG" \
    --set pods.fhir-generation.env.litellmUrl="$LLM_BASE_URL" \
    --set pods.fhir-generation.env.llmModel="$LLM_MODEL" \
    --set pods.fhir-generation.env.llmRequestTimeout="${LLM_REQUEST_TIMEOUT:-600}" \
    --set pods.fhir-server.tag="$IMAGE_TAG" \
    --set pods.bff.tag="$IMAGE_TAG" \
    --set pods.ui.tag="$IMAGE_TAG" \
    --wait --timeout 120s || { log "ERROR: acp-writer helm install failed"; exit 1; }
log "  acp-writer installed ($(( SECONDS - helm_start ))s)"

# --- Step 4: Apply SonataFlow workflow ---

log_step "Applying SonataFlow workflow"
# Props MUST be applied before (or with) the CR: they map CloudEvent channels
# to the /wait-* HTTP endpoints and raise timeouts for long LLM calls.
oc apply -f "$SCRIPT_DIR/orchestrator/acpwriter-props.yaml" -n "$NAMESPACE" 2>/dev/null \
    || log "WARNING: acpwriter-props apply failed"
oc apply -f "$SCRIPT_DIR/orchestrator/acp-writer-workflow.yaml" -n "$NAMESPACE" 2>/dev/null \
    || log "WARNING: SonataFlow workflow apply failed"
# The SonataFlow operator mounts the workflow definition into the running
# `acpwriter` pod via a ConfigMap; a re-apply that only changes the workflow
# body does not always roll the pod, so the old definition keeps serving. Force
# a restart so the new flow (e.g. careplan_review_history threading) takes
# effect. Dev-only: this drops any in-flight workflow instances.
if oc get deployment/acpwriter -n "$NAMESPACE" >/dev/null 2>&1; then
    oc rollout restart deployment/acpwriter -n "$NAMESPACE" 2>/dev/null \
        || log "WARNING: acpwriter rollout restart failed"
    oc rollout status deployment/acpwriter -n "$NAMESPACE" --timeout=120s 2>/dev/null \
        || log "WARNING: acpwriter rollout did not complete in time"

    # A pod created seconds after the CM apply can mount a STALE cached CM; the
    # kubelet swaps in the real content minutes later, and that delayed swap
    # triggers a Quarkus devmode lazy live-reload that wipes all in-memory
    # workflow instances — orphaning any in-flight run (observed 2026-08-28
    # 00:01, run 5af4a6e5a58c). Wait for the projection to match the applied CM
    # by content hash, then poke the lazy reload NOW, while nothing is running.
    WF_FILE=/home/kogito/serverless-workflow-project/src/main/resources/acpwriter.sw.json
    WF_SHA=$(oc get cm acpwriter -n "$NAMESPACE" -o jsonpath='{.data.acpwriter\.sw\.json}' | shasum | cut -d' ' -f1)
    POD_SHA=""
    for _ in $(seq 1 36); do
        POD_SHA=$( (oc exec deployment/acpwriter -n "$NAMESPACE" -- cat "$WF_FILE" 2>/dev/null || true) | shasum | cut -d' ' -f1)
        [ "$POD_SHA" = "$WF_SHA" ] && break
        sleep 5
    done
    if [ "$POD_SHA" = "$WF_SHA" ]; then
        log "Workflow projection settled in pod (sha ${WF_SHA:0:8})"
        # Trigger devmode's request-driven reload deterministically.
        oc exec deployment/acpwriter -n "$NAMESPACE" -- \
            curl -s -o /dev/null -m 10 http://localhost:8080/q/health 2>/dev/null \
            || log "WARNING: reload poke failed (continuing)"
    else
        log "WARNING: pod workflow projection still stale after 3m — first run may be orphaned by a late reload"
    fi
fi

# --- Step 5: Deploy MCP server ---

log_step "Deploying MCP server"
render_template "$SCRIPT_DIR/mcp/acp-writer-mcp.yaml.tmpl" "$REPO_ROOT/deploy/.rendered/acp-writer-mcp.yaml"
oc apply -f "$REPO_ROOT/deploy/.rendered/acp-writer-mcp.yaml" -n "$NAMESPACE" 2>/dev/null \
    || log "WARNING: MCP server deploy failed"
oc apply -f "$SCRIPT_DIR/mcp/registration.yaml" -n "$NAMESPACE" 2>/dev/null \
    || log "WARNING: MCP registration apply failed"

save_deploy_state "acp-writer" "$IMAGE_TAG"

# --- Step 6: Verify ---

log_step "Verifying acp-writer deployment"
"$SCRIPT_DIR/verify.sh" --config "$CONFIG_PATH"

# --- Step 7: Prune old image tags ---

for is in acp-writer-patient-data acp-writer-llm acp-writer-decision acp-writer-fhir-gen acp-writer-fhir-srv acp-writer-bff acp-writer-ui acp-writer-mcp decision-service; do
    prune_image_tags "$is" 5
done

log_step "acp-writer deployment complete"
