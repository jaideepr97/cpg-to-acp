#!/usr/bin/env bash
# mock-EHR/deploy/teardown.sh — Remove mock-EHR deployment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
while [[ $# -gt 0 ]]; do
    case "$1" in --config) CONFIG_PATH="$2"; shift 2;; -h|--help) echo "Usage: mock-EHR/deploy/teardown.sh [--config <path>]"; exit 0;; *) shift;; esac
done

load_config "$CONFIG_PATH"
preflight

log_step "Tearing down mock-EHR (namespace=$NAMESPACE)"

# Helm release
helm uninstall cpg-mock-ehr -n "$NAMESPACE" 2>/dev/null || log "  cpg-mock-ehr not installed"

# Loader Job (may survive helm uninstall if in error state)
oc delete jobs -l app.kubernetes.io/instance=cpg-mock-ehr -n "$NAMESPACE" 2>/dev/null || true

# MCP server
log "Removing MCP server..."
oc delete -f "$SCRIPT_DIR/mcp/registration.yaml" -n "$NAMESPACE" 2>/dev/null || true
render_template "$SCRIPT_DIR/mcp/mock-ehr-mcp.yaml.tmpl" "$REPO_ROOT/deploy/.rendered/mock-ehr-mcp.yaml"
oc delete -f "$REPO_ROOT/deploy/.rendered/mock-ehr-mcp.yaml" -n "$NAMESPACE" 2>/dev/null || true

# BuildConfigs
log "Removing BuildConfigs..."
for bc in mock-ehr-app medplum-loader; do
    oc delete bc "$bc" -n "$NAMESPACE" 2>/dev/null || true
done
prune_builds "mock-ehr"

log_step "mock-EHR teardown complete"
