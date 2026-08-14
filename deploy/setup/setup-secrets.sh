#!/usr/bin/env bash
# deploy/setup/setup-secrets.sh — Create K8s Secrets from local secrets.env
#
# Creates (or updates) the required K8s Secrets for the CPG-to-ACP deployment.
# Secrets are the on-cluster source of truth — the local file can be deleted
# after running this script.
#
# Usage:
#   ./deploy/setup/setup-secrets.sh --from-env deploy/config/secrets.env
#   ./deploy/setup/setup-secrets.sh --interactive
#   ./deploy/setup/setup-secrets.sh --help
#
# Prerequisites:
#   - oc login completed
#   - deploy/config/cluster.env configured (for NAMESPACE)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck disable=SC1091
source "$REPO_ROOT/deploy/lib.sh"

MODE=""
ENV_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from-env)
            MODE="file"
            ENV_FILE="$2"
            shift 2
            ;;
        --interactive)
            MODE="interactive"
            shift
            ;;
        --config)
            load_config "$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: setup-secrets.sh [--from-env <path>|--interactive] [--config <cluster.env>]"
            echo ""
            echo "Options:"
            echo "  --from-env <path>   Read secrets from a local .env file"
            echo "  --interactive       Prompt for each secret value"
            echo "  --config <path>     Path to cluster.env (default: deploy/config/cluster.env)"
            echo ""
            echo "Creates/updates K8s Secrets:"
            echo "  llm-credentials           LLM_API_KEY (OpenAI API key)"
            echo "  minio-credentials         MinIO root and artifact-store credentials"
            echo "  fhir-client-credentials   FHIR server (Medplum) client credentials"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1. Use --help for usage."
            exit 1
            ;;
    esac
done

if [ -z "$MODE" ]; then
    echo "ERROR: Specify --from-env <path> or --interactive"
    echo "  Run with --help for usage."
    exit 1
fi

# Load cluster config if not already loaded
if [ -z "${NAMESPACE:-}" ]; then
    load_config "$REPO_ROOT/deploy/config/cluster.env"
fi

preflight

# --- Read secret values ---

if [ "$MODE" = "file" ]; then
    if [ ! -f "$ENV_FILE" ]; then
        echo "ERROR: Secrets file not found: $ENV_FILE"
        echo "  Copy deploy/config/secrets.env.template to $ENV_FILE and fill in values."
        exit 1
    fi
    # Source the secrets file (suppressing trace)
    { set +x; } 2>/dev/null
    # shellcheck disable=SC1090
    source "$ENV_FILE"
elif [ "$MODE" = "interactive" ]; then
    { set +x; } 2>/dev/null
    echo "Enter secret values (input is hidden):"
    echo ""
    read -r -s -p "OpenAI API key (OPENAI_API_KEY): " OPENAI_API_KEY; echo ""
    read -r -s -p "MinIO root user [minioadmin]: " MINIO_ROOT_USER; echo ""
    MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
    read -r -s -p "MinIO root password: " MINIO_ROOT_PASSWORD; echo ""
    read -r -s -p "FHIR client ID (blank to skip): " FHIR_CLIENT_ID; echo ""
    read -r -s -p "FHIR client secret (blank to skip): " FHIR_CLIENT_SECRET; echo ""
fi

# --- Validate required values ---

if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "ERROR: OPENAI_API_KEY is required."
    exit 1
fi

if [ -z "${MINIO_ROOT_PASSWORD:-}" ]; then
    echo "ERROR: MINIO_ROOT_PASSWORD is required."
    exit 1
fi

# --- Create/update K8s Secrets ---

log_step "Creating K8s Secrets in namespace $NAMESPACE"

# LLM credentials
log "Creating llm-credentials..."
oc apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: llm-credentials
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/part-of: cpg-to-acp
    app.kubernetes.io/managed-by: deploy-framework
type: Opaque
stringData:
  LLM_API_KEY: "$OPENAI_API_KEY"
EOF

# MinIO credentials
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
ARTIFACT_STORE_ACCESS_KEY="${MINIO_ROOT_USER}"
ARTIFACT_STORE_SECRET_KEY="${MINIO_ROOT_PASSWORD}"

log "Creating minio-credentials..."
oc apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: minio-credentials
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/part-of: cpg-to-acp
    app.kubernetes.io/managed-by: deploy-framework
type: Opaque
stringData:
  MINIO_ROOT_USER: "$MINIO_ROOT_USER"
  MINIO_ROOT_PASSWORD: "$MINIO_ROOT_PASSWORD"
  ARTIFACT_STORE_ACCESS_KEY: "$ARTIFACT_STORE_ACCESS_KEY"
  ARTIFACT_STORE_SECRET_KEY: "$ARTIFACT_STORE_SECRET_KEY"
EOF

# FHIR client credentials (optional)
if [ -n "${FHIR_CLIENT_ID:-}" ] && [ -n "${FHIR_CLIENT_SECRET:-}" ]; then
    log "Creating fhir-client-credentials..."
    oc apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: fhir-client-credentials
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/part-of: cpg-to-acp
    app.kubernetes.io/managed-by: deploy-framework
type: Opaque
stringData:
  FHIR_CLIENT_ID: "$FHIR_CLIENT_ID"
  FHIR_CLIENT_SECRET: "$FHIR_CLIENT_SECRET"
EOF
else
    log "Skipping fhir-client-credentials (no values provided)"
fi

# --- Clear variables ---
unset OPENAI_API_KEY MINIO_ROOT_USER MINIO_ROOT_PASSWORD FHIR_CLIENT_ID FHIR_CLIENT_SECRET
unset ARTIFACT_STORE_ACCESS_KEY ARTIFACT_STORE_SECRET_KEY

echo ""
log "Secrets created in namespace $NAMESPACE."
log "Verify: oc get secrets -n $NAMESPACE -l app.kubernetes.io/managed-by=deploy-framework"
log ""
log "The secrets.env file can now be deleted from disk (the K8s Secrets are the source of truth)."
