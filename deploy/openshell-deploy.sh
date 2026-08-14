#!/usr/bin/env bash
set -euo pipefail

# Portability: macOS ships bash 3.2 (no `declare -A`), so this script is often
# run under zsh. zsh does NOT word-split unquoted variables the way bash does,
# which silently breaks `for x in $list` and `-- $command`. Enable sh-style
# splitting when running under zsh so both shells behave identically.
[ -n "${ZSH_VERSION:-}" ] && setopt SH_WORD_SPLIT

REGISTRY="image-registry.openshift-image-registry.svc:5000"
NAMESPACE="sschifma-cpg-to-acp"
IMAGE_TAG="${IMAGE_TAG:-phase3}"
POLICY_DIR="$(cd "$(dirname "$0")/openshell-policies" && pwd)"
MLFLOW_URI="https://mlflow-redhat-ods-applications.apps.rosa.agentic-mcp.jolf.p3.openshiftapps.com"
LITELLM_URL="http://maas-default-gateway-openshift-default.openshift-ingress.svc.cluster.local:80/gpt-5-6"
LLM_MODEL="gpt-5.6-terra"
LLM_API_KEY="${LLM_API_KEY:?Set LLM_API_KEY environment variable}"
MINIO_URL="http://minio:9000"
MINIO_ACCESS="${MINIO_ACCESS:?Set MINIO_ACCESS environment variable}"
MINIO_SECRET="${MINIO_SECRET:?Set MINIO_SECRET environment variable}"

declare -A SANDBOX_PIDS

# Killing the CLI attach processes is safe: the sandbox supervisor (PID 1
# in each pod) keeps the command running and the gateway route alive after
# the CLI disconnects (verified on-cluster 2026-08-14).
cleanup() {
    echo "Cleaning up CLI attach processes (sandboxes keep running)..."
    for pid in "${SANDBOX_PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT

create_sandbox() {
    local name="$1"
    local image="$2"
    local policy="$3"
    local k8s_name_label="$4"
    local k8s_instance_label="$5"
    local command="$6"
    shift 6
    local env_args=("$@")

    echo "Creating sandbox: $name"

    local args=(
        --name "$name"
        --from "${REGISTRY}/${NAMESPACE}/${image}:${IMAGE_TAG}"
        --policy "${POLICY_DIR}/${policy}"
    )
    for e in "${env_args[@]}"; do
        args+=(--env "$e")
    done

    # `sh -c "$command"` passes the command as ONE quoted string — immune to
    # the bash/zsh word-splitting difference that broke `-- $command`.
    openshell sandbox create "${args[@]}" -- sh -c "$command" &
    SANDBOX_PIDS[$name]=$!

    echo "  Waiting for pod..."
    for i in $(seq 1 90); do
        local pod_phase
        pod_phase=$(oc get pod "$name" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
        if [ "$pod_phase" = "Running" ]; then
            local ready
            ready=$(oc get pod "$name" -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null || echo "false")
            if [ "$ready" = "true" ]; then
                echo "  Pod ready after ${i}s"
                break
            fi
        fi
        sleep 1
    done

    echo "  Adding K8s labels..."
    oc label pod "$name" \
        "app.kubernetes.io/name=${k8s_name_label}" \
        "app.kubernetes.io/instance=${k8s_instance_label}" \
        --overwrite 2>/dev/null

    echo "  Exposing HTTP service..."
    openshell service expose "$name" 8080 http 2>/dev/null || true

    echo "  Done: $name"
}

delete_existing_sandboxes() {
    echo "=== Cleaning up existing sandboxes ==="
    local sandboxes
    sandboxes=$(openshell sandbox list --output json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for sb in data:
        print(sb.get('name', ''))
except:
    pass
" 2>/dev/null || true)

    for sb in $sandboxes; do
        if [ -n "$sb" ]; then
            echo "  Deleting sandbox: $sb"
            openshell sandbox delete "$sb" 2>/dev/null || true
        fi
    done
}

scale_down_helm_pods() {
    echo "=== Scaling down Helm-deployed pods ==="
    local deployments=(
        cpg-ing-ingestion cpg-ing-llm-analysis cpg-ing-assembly cpg-ing-delivery
        acp-patient-data acp-llm-reasoning acp-decision-engine acp-fhir-generation acp-fhir-server
    )
    for dep in "${deployments[@]}"; do
        echo "  Scaling down: $dep"
        oc scale deployment "$dep" --replicas=0 2>/dev/null || true
    done

    echo "  Waiting for pods to terminate..."
    for dep in "${deployments[@]}"; do
        oc rollout status deployment/"$dep" --timeout=60s 2>/dev/null || true
    done
}

restore_helm_pods() {
    echo "=== Restoring Helm-deployed pods ==="
    local deployments=(
        cpg-ing-ingestion cpg-ing-llm-analysis cpg-ing-assembly cpg-ing-delivery
        acp-patient-data acp-llm-reasoning acp-decision-engine acp-fhir-generation acp-fhir-server
    )
    for dep in "${deployments[@]}"; do
        echo "  Scaling up: $dep"
        oc scale deployment "$dep" --replicas=1 2>/dev/null || true
    done
}

verify_services() {
    echo "=== Verifying service routing ==="
    local services=(
        cpg-ing-ingestion cpg-ing-llm-analysis cpg-ing-assembly cpg-ing-delivery
        acp-patient-data acp-llm-reasoning acp-decision-engine acp-fhir-generation acp-fhir-server
    )
    local all_ok=true
    for svc in "${services[@]}"; do
        local endpoints
        endpoints=$(oc get endpoints "$svc" -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null || echo "")
        if [ -n "$endpoints" ]; then
            echo "  OK: $svc -> $endpoints"
        else
            echo "  FAIL: $svc has no endpoints"
            all_ok=false
        fi
    done
    if $all_ok; then
        echo "All services have endpoints."
    else
        echo "WARNING: Some services have no endpoints!"
    fi
}

deploy_sandboxes() {
    echo "=== Creating OpenShell sandboxes ==="

    common_env=(
        "MLFLOW_TRACKING_URI=${MLFLOW_URI}"
        "ARTIFACT_STORE_URL=${MINIO_URL}"
        "ARTIFACT_STORE_ACCESS_KEY=${MINIO_ACCESS}"
        "ARTIFACT_STORE_SECRET_KEY=${MINIO_SECRET}"
    )

    # cpg-ingester: Ingestion
    create_sandbox "sb-ingestion" "cpg-ingester-ingestion" "cpg-ingester-ingestion.yaml" \
        "cpg-ingester-ingestion" "cpg-ing" \
        "uvicorn cpg_ingester.services.ingestion:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "LOG_LEVEL=DEBUG" \
        "DOCLING_LOG_LEVEL=DEBUG" \
        "PYTHONUNBUFFERED=1" \
        "HF_HUB_OFFLINE=1" \
        "DOCLING_ARTIFACTS_PATH=/app/.cache/docling/models"

    # cpg-ingester: LLM Analysis
    create_sandbox "sb-llm-analysis" "cpg-ingester-llm" "cpg-ingester-llm.yaml" \
        "cpg-ingester-llm-analysis" "cpg-ing" \
        "uvicorn cpg_ingester.services.llm_analysis:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src" \
        "LITELLM_URL=${LITELLM_URL}" \
        "LLM_MODEL=${LLM_MODEL}" \
        "LLM_API_KEY=${LLM_API_KEY}"

    # cpg-ingester: Assembly
    create_sandbox "sb-assembly" "cpg-ingester-assembly" "cpg-ingester-assembly.yaml" \
        "cpg-ingester-assembly" "cpg-ing" \
        "uvicorn cpg_ingester.services.assembly_svc:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src"

    # cpg-ingester: Delivery
    create_sandbox "sb-delivery" "cpg-ingester-delivery" "cpg-ingester-delivery.yaml" \
        "cpg-ingester-delivery" "cpg-ing" \
        "uvicorn cpg_ingester.services.delivery_svc:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src" \
        "ACP_WRITER_URL=http://acp-writer-api:8080"

    # acp-writer: Patient Data
    create_sandbox "sb-patient-data" "acp-writer-patient-data" "acp-writer-patient-data.yaml" \
        "acp-writer-patient-data" "acp" \
        "uvicorn acp_writer.services.patient_data:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src"

    # acp-writer: LLM Reasoning (hosts DMN input resolution + evaluation loop)
    create_sandbox "sb-llm-reasoning" "acp-writer-llm" "acp-writer-llm.yaml" \
        "acp-writer-llm-reasoning" "acp" \
        "uvicorn acp_writer.services.llm_reasoning:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src" \
        "LITELLM_URL=${LITELLM_URL}" \
        "LLM_MODEL=${LLM_MODEL}" \
        "LLM_API_KEY=${LLM_API_KEY}" \
        "DECISION_ENGINE_URL=http://acp-decision-engine:8080"

    # acp-writer: Decision Engine (thin Kogito wrapper — deliberately NO LLM credentials)
    # DMN input resolution runs in the LLM-reasoning pod; this pod only evaluates
    # pre-resolved inputs. Do not add LITELLM_URL/LLM_API_KEY here.
    create_sandbox "sb-decision-engine" "acp-writer-decision" "acp-writer-decision.yaml" \
        "acp-writer-decision-engine" "acp" \
        "uvicorn acp_writer.services.decision_engine:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src" \
        "KOGITO_URL=http://cpg-decision-svc-decision-service.${NAMESPACE}.svc.cluster.local:8081"

    # acp-writer: FHIR Generation
    create_sandbox "sb-fhir-generation" "acp-writer-fhir-gen" "acp-writer-fhir-gen.yaml" \
        "acp-writer-fhir-generation" "acp" \
        "uvicorn acp_writer.services.fhir_generation:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src" \
        "LITELLM_URL=${LITELLM_URL}" \
        "LLM_MODEL=${LLM_MODEL}" \
        "LLM_API_KEY=${LLM_API_KEY}"

    # acp-writer: FHIR Server
    create_sandbox "sb-fhir-server" "acp-writer-fhir-srv" "acp-writer-fhir-srv.yaml" \
        "acp-writer-fhir-server" "acp" \
        "uvicorn acp_writer.services.fhir_server:app --host 0.0.0.0 --port 8080" \
        "${common_env[@]}" \
        "PYTHONPATH=/app/src" \
        "FHIR_SERVER_URL=http://cpg-mock-ehr-medplum-server:8103/fhir/R4" \
        "FHIR_CLIENT_ID=${FHIR_CLIENT_ID:-}" \
        "FHIR_CLIENT_SECRET=${FHIR_CLIENT_SECRET:-}"
}

case "${1:-deploy}" in
    deploy)
        delete_existing_sandboxes
        scale_down_helm_pods
        deploy_sandboxes
        verify_services
        echo ""
        echo "=== OpenShell deployment complete ==="
        echo "Sandbox pods are running with security policies enforced."
        echo "Run 'openshell sandbox list' to see all sandboxes."
        echo "Run '$0 teardown' to restore Helm-deployed pods."
        ;;
    teardown)
        delete_existing_sandboxes
        restore_helm_pods
        echo "Restored Helm-deployed pods."
        ;;
    verify)
        verify_services
        ;;
    *)
        echo "Usage: $0 {deploy|teardown|verify}"
        exit 1
        ;;
esac
