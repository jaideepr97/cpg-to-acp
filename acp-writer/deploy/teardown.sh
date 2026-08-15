#!/usr/bin/env bash
# acp-writer/deploy/teardown.sh — Remove acp-writer deployment
#
# Removes sandboxes, Helm releases, SonataFlow CRs, and build artifacts.
# Preserves K8s Secrets and ImageStreams by default.
#
# Usage:
#   ./acp-writer/deploy/teardown.sh [--config <path>]
#   ./acp-writer/deploy/teardown.sh --full-wipe  # also removes ImageStreams

set -euo pipefail
[ -n "${ZSH_VERSION:-}" ] && setopt SH_WORD_SPLIT

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck disable=SC1091
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
FULL_WIPE=false
SKIP_CONFIRM=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; shift 2;;
        --full-wipe) FULL_WIPE=true; shift;;
        --yes) SKIP_CONFIRM=true; shift;;
        -h|--help)
            echo "Usage: acp-writer/deploy/teardown.sh [--config <path>] [--full-wipe] [--yes]"
            echo ""
            echo "Removes: sandboxes, Helm releases, SonataFlow CRs, BuildConfigs, build pods."
            echo "Preserves: K8s Secrets, ImageStreams (unless --full-wipe)."
            echo "  --yes    Skip confirmation prompt (for automation)"
            exit 0;;
        *) shift;;
    esac
done

if [ "$FULL_WIPE" = true ] && [ "$SKIP_CONFIRM" = false ]; then
    echo "⚠ --full-wipe will delete acp-writer ImageStreams (all built images)."
    echo "  Type 'wipe' to confirm:"
    read -r confirm
    [ "$confirm" != "wipe" ] && echo "Aborted." && exit 1
fi

load_config "$CONFIG_PATH"
preflight

log_step "Tearing down acp-writer (namespace=$NAMESPACE)"

# OpenShell sandboxes
if command -v openshell &>/dev/null; then
    ensure_openshell_portforward
    "$SCRIPT_DIR/openshell/deploy.sh" teardown --config "$CONFIG_PATH" || true
fi

# Helm releases
log "Removing Helm releases..."
helm uninstall acp -n "$NAMESPACE" 2>/dev/null || log "  acp not installed"
helm uninstall cpg-decision-svc -n "$NAMESPACE" 2>/dev/null || log "  cpg-decision-svc not installed"

# MCP server
log "Removing MCP server..."
oc delete -f "$SCRIPT_DIR/mcp/registration.yaml" -n "$NAMESPACE" 2>/dev/null || true
render_template "$SCRIPT_DIR/mcp/acp-writer-mcp.yaml.tmpl" "$REPO_ROOT/deploy/.rendered/acp-writer-mcp.yaml"
oc delete -f "$REPO_ROOT/deploy/.rendered/acp-writer-mcp.yaml" -n "$NAMESPACE" 2>/dev/null || true

# SonataFlow
log "Removing SonataFlow workflow..."
oc delete -f "$SCRIPT_DIR/orchestrator/acp-writer-workflow.yaml" -n "$NAMESPACE" 2>/dev/null || true
oc delete -f "$SCRIPT_DIR/orchestrator/acpwriter-props.yaml" -n "$NAMESPACE" 2>/dev/null || true

# BuildConfigs and build pods
log "Removing BuildConfigs and build pods..."
for bc in acp-writer-patient-data acp-writer-llm acp-writer-decision acp-writer-fhir-gen acp-writer-fhir-srv acp-writer-ui acp-writer-mcp decision-service; do
    oc delete bc "$bc" -n "$NAMESPACE" 2>/dev/null || true
done
prune_builds "acp-writer"
prune_builds "decision-service"

# ImageStreams (only with --full-wipe)
if [ "$FULL_WIPE" = true ]; then
    log "Removing ImageStreams (--full-wipe)..."
    for is in acp-writer-patient-data acp-writer-llm acp-writer-decision acp-writer-fhir-gen acp-writer-fhir-srv acp-writer-ui acp-writer-mcp decision-service; do
        oc delete is "$is" -n "$NAMESPACE" 2>/dev/null || true
    done
fi

log_step "acp-writer teardown complete"
