#!/usr/bin/env bash
# deploy/teardown-all.sh — Tear down all CPG-to-ACP components
#
# Usage:
#   ./deploy/teardown-all.sh [--config <path>]
#   ./deploy/teardown-all.sh --infra        # also removes shared infrastructure
#   ./deploy/teardown-all.sh --full-wipe    # also removes ImageStreams + Secrets

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
INFRA=false
FULL_WIPE=false
SKIP_CONFIRM=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; shift 2;;
        --infra) INFRA=true; shift;;
        --full-wipe)
            FULL_WIPE=true; INFRA=true; shift;;
        --yes) SKIP_CONFIRM=true; shift;;
        -h|--help)
            echo "Usage: deploy/teardown-all.sh [--config <path>] [--infra] [--full-wipe] [--yes]"
            echo ""
            echo "  (default)     Remove components only (sandboxes, Helm, SonataFlow, builds)"
            echo "  --infra       Also remove shared infrastructure (MinIO, router, MCP gateway)"
            echo "  --full-wipe   Also remove ImageStreams AND K8s Secrets (confirmation required)"
            echo "  --yes         Skip confirmation prompt (for automation)"
            exit 0;;
        *) shift;;
    esac
done

load_config "$CONFIG_PATH"
preflight

if [ "$FULL_WIPE" = true ] && [ "$SKIP_CONFIRM" = false ]; then
    echo "⚠ --full-wipe will delete:"
    echo "  - All component sandboxes, Helm releases, SonataFlow CRs, BuildConfigs, builds"
    echo "  - Shared infrastructure (MinIO, router, MCP gateway)"
    echo "  - ImageStreams (all built images)"
    echo "  - K8s Secrets: llm-credentials, minio-credentials, fhir-client-credentials, medplum-user-credentials"
    echo ""
    echo "  Type 'wipe' to confirm:"
    read -r confirm
    if [ "$confirm" != "wipe" ]; then
        echo "Aborted."
        exit 1
    fi
fi

log_step "Tearing down all CPG-to-ACP components (namespace=$NAMESPACE)"

# Components (reverse order of deploy)
for component in cpg-ingester acp-writer mock-EHR; do
    script="$REPO_ROOT/$component/deploy/teardown.sh"
    if [ -f "$script" ]; then
        log_step "Tearing down $component"
        wipe_arg=""
        if [ "$FULL_WIPE" = true ]; then
            wipe_arg="--full-wipe"
            [ "$SKIP_CONFIRM" = true ] && wipe_arg="$wipe_arg --yes"
        fi
        "$script" --config "$CONFIG_PATH" $wipe_arg || log "WARNING: $component teardown had errors"
    fi
done

# Shared infrastructure
if [ "$INFRA" = true ]; then
    log_step "Removing shared infrastructure"

    log "Removing shared MCP Gateway resources..."
    render_template "$REPO_ROOT/deploy/mcp-gateway/gateway.yaml.tmpl" "$REPO_ROOT/deploy/.rendered/mcp-gateway.yaml"
    oc delete -f "$REPO_ROOT/deploy/.rendered/mcp-gateway.yaml" -n "$NAMESPACE" 2>/dev/null || true
    oc delete -f "$REPO_ROOT/deploy/mcp-gateway/virtual-servers.yaml" -n "$NAMESPACE" 2>/dev/null || true
    # Clean up operator-managed secret left behind when gateway CRs are deleted
    oc delete secret mcp-gateway-config -n "$NAMESPACE" 2>/dev/null || true

    log "Removing openshell-router..."
    oc delete -f "$REPO_ROOT/deploy/openshell-router/deploy.yaml" -n "$NAMESPACE" 2>/dev/null || true
    oc delete configmap openshell-router-config -n "$NAMESPACE" 2>/dev/null || true

    log "Removing MinIO..."
    oc delete -f "$REPO_ROOT/deploy/platform/minio.yaml" -n "$NAMESPACE" 2>/dev/null || true
fi

if [ "$FULL_WIPE" = true ]; then
    log_step "Removing K8s Secrets (--full-wipe)"
    for secret in llm-credentials minio-credentials fhir-client-credentials medplum-user-credentials smart-client-credentials; do
        oc delete secret "$secret" -n "$NAMESPACE" 2>/dev/null && log "  Deleted $secret" || true
    done

    log_step "Removing cluster-scoped OpenShell RBAC (--full-wipe)"
    oc delete clusterrolebinding "${NAMESPACE}-openshell-tokenreview" 2>/dev/null \
        && log "  Deleted ClusterRoleBinding ${NAMESPACE}-openshell-tokenreview" || true
    oc delete clusterrole "${NAMESPACE}-openshell-tokenreview" 2>/dev/null \
        && log "  Deleted ClusterRole ${NAMESPACE}-openshell-tokenreview" || true
fi

# Check for orphans
remaining=$(oc get pods -n "$NAMESPACE" --no-headers 2>/dev/null | grep -v "openshell-0\|sonataflow-platform" | wc -l | tr -d ' ')
if [ "$remaining" -gt 0 ]; then
    log "WARNING: $remaining pod(s) still running (expected: openshell-0 + SonataFlow platform only)"
    oc get pods -n "$NAMESPACE" --no-headers 2>/dev/null | grep -v "openshell-0\|sonataflow-platform"
fi

log_step "Teardown complete"
