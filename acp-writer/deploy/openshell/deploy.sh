#!/usr/bin/env bash
# acp-writer/deploy/openshell/deploy.sh — Create acp-writer OpenShell sandboxes
#
# Creates 5 sandboxes: patient-data, llm-reasoning, decision-engine,
# fhir-generation, fhir-server. Each runs supervised under OpenShell
# with its own security policy.
#
# Usage:
#   ./acp-writer/deploy/openshell/deploy.sh [--config <cluster.env>] [--tag <sha>]
#   ./acp-writer/deploy/openshell/deploy.sh teardown
#
# Prerequisites:
#   - deploy/config/cluster.env configured
#   - K8s Secrets created (setup-secrets.sh)
#   - OpenShell controller running + port-forward (lib.sh handles this)

set -euo pipefail
[ -n "${ZSH_VERSION:-}" ] && setopt SH_WORD_SPLIT

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPONENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$COMPONENT_DIR/../.." && pwd)"

# shellcheck disable=SC1091
source "$REPO_ROOT/deploy/lib.sh"

# Parse args
ACTION="deploy"
CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
TAG_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        deploy|teardown) ACTION="$1"; shift;;
        --config) CONFIG_PATH="$2"; shift 2;;
        --tag) TAG_OVERRIDE="$2"; shift 2;;
        -h|--help)
            echo "Usage: acp-writer/deploy/openshell/deploy.sh [deploy|teardown] [--config <path>] [--tag <sha>]"
            exit 0;;
        *) shift;;
    esac
done

load_config "$CONFIG_PATH"
[ -n "$TAG_OVERRIDE" ] && IMAGE_TAG="$TAG_OVERRIDE"

preflight
preflight_openshell

IMAGE_REGISTRY="quay.io/cpgtoacp"

# Render policy templates with namespace and MLflow host
RENDERED_POLICY_DIR="$REPO_ROOT/deploy/.rendered/acp-writer-policies"
render_templates_dir "$SCRIPT_DIR/policies" "$RENDERED_POLICY_DIR"
POLICY_DIR="$RENDERED_POLICY_DIR"

LLM_BASE_URL="${MAAS_GATEWAY_URL}/${MAAS_ROUTE_SEGMENT}"
LLM_MODEL="${ACP_WRITER_LLM_MODEL:-$LLM_MODEL_DEFAULT}"

# Read secrets from K8s Secrets (never from env vars or files)
{ set +x; } 2>/dev/null
LLM_API_KEY=$(read_secret llm-credentials LLM_API_KEY)
MINIO_ACCESS=$(read_secret minio-credentials ARTIFACT_STORE_ACCESS_KEY)
MINIO_SECRET=$(read_secret minio-credentials ARTIFACT_STORE_SECRET_KEY)
FHIR_CLIENT_ID=$(read_secret_optional fhir-client-credentials FHIR_CLIENT_ID)
FHIR_CLIENT_SECRET=$(read_secret_optional fhir-client-credentials FHIR_CLIENT_SECRET)

SANDBOXES=(sb-patient-data sb-llm-reasoning sb-decision-engine sb-fhir-generation sb-fhir-server)

common_env=(
    "MLFLOW_TRACKING_URI=${MLFLOW_TRACKING_URI}"
    "ARTIFACT_STORE_URL=http://minio:9000"
    "ARTIFACT_STORE_ACCESS_KEY=${MINIO_ACCESS}"
    "ARTIFACT_STORE_SECRET_KEY=${MINIO_SECRET}"
)

teardown_sandboxes() {
    log_step "Tearing down acp-writer sandboxes"
    for sb in "${SANDBOXES[@]}"; do
        log "Deleting $sb..."
        openshell sandbox delete "$sb" 2>/dev/null || true
    done
}

deploy_sandboxes() {
    log_step "Creating acp-writer OpenShell sandboxes (IMAGE_TAG=$IMAGE_TAG)"

    create_acp_sandbox() {
        local name="$1" image="$2" policy="$3" k8s_name="$4" command="$5"
        shift 5
        local env_args=("$@")

        log "Creating $name from ${image}:${IMAGE_TAG}..."
        local args=(
            --name "$name"
            --from "${IMAGE_REGISTRY}/${image}:${IMAGE_TAG}"
            --policy "${POLICY_DIR}/${policy}"
        )
        for e in "${env_args[@]}"; do
            args+=(--env "$e")
        done

        openshell sandbox create "${args[@]}" -- sh -c "$command" &
        local pid=$!
        sleep 2

        wait_for_pod_ready "$name" 90 || true
        label_pod "$name" "$k8s_name" "acp"
        openshell service expose "$name" 8080 http 2>/dev/null || true
        log "Done: $name"
    }

    # Patient Data
    create_acp_sandbox "sb-patient-data" "acp-writer-patient-data" "acp-writer-patient-data.yaml" \
        "acp-writer-patient-data" \
        "uvicorn acp_writer.services.patient_data:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src"

    # LLM Reasoning (hosts DMN input resolution + evaluation loop)
    create_acp_sandbox "sb-llm-reasoning" "acp-writer-llm" "acp-writer-llm.yaml" \
        "acp-writer-llm-reasoning" \
        "uvicorn acp_writer.services.llm_reasoning:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src" \
        "LITELLM_URL=${LLM_BASE_URL}" \
        "LLM_MODEL=${LLM_MODEL}" \
        "LLM_API_KEY=${LLM_API_KEY}" \
        "DECISION_ENGINE_URL=http://acp-decision-engine:8080"

    # Decision Engine (thin Kogito wrapper — deliberately NO LLM credentials)
    create_acp_sandbox "sb-decision-engine" "acp-writer-decision" "acp-writer-decision.yaml" \
        "acp-writer-decision-engine" \
        "uvicorn acp_writer.services.decision_engine:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src" \
        "KOGITO_URL=http://cpg-decision-svc-decision-service.${NAMESPACE}.svc.cluster.local:8081"

    # FHIR Generation
    create_acp_sandbox "sb-fhir-generation" "acp-writer-fhir-gen" "acp-writer-fhir-gen.yaml" \
        "acp-writer-fhir-generation" \
        "uvicorn acp_writer.services.fhir_generation:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src" \
        "LITELLM_URL=${LLM_BASE_URL}" \
        "LLM_MODEL=${LLM_MODEL}" \
        "LLM_API_KEY=${LLM_API_KEY}"

    # FHIR Server
    create_acp_sandbox "sb-fhir-server" "acp-writer-fhir-srv" "acp-writer-fhir-srv.yaml" \
        "acp-writer-fhir-server" \
        "uvicorn acp_writer.services.fhir_server:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src" \
        "FHIR_SERVER_URL=http://cpg-mock-ehr-medplum-server.${NAMESPACE}.svc.cluster.local:8103/fhir/R4" \
        "FHIR_CLIENT_ID=${FHIR_CLIENT_ID:-}" \
        "FHIR_CLIENT_SECRET=${FHIR_CLIENT_SECRET:-}"

    # Wait for background sandbox-create processes to settle
    sleep 5
}

case "$ACTION" in
    deploy)
        teardown_sandboxes
        deploy_sandboxes
        log_step "acp-writer OpenShell deployment complete"
        ;;
    teardown)
        teardown_sandboxes
        log_step "acp-writer sandboxes removed"
        ;;
    *)
        echo "Unknown action: $ACTION. Use deploy or teardown."
        exit 1
        ;;
esac
