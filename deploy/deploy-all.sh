#!/usr/bin/env bash
# deploy/deploy-all.sh — Deploy all CPG-to-ACP components to OpenShift
#
# Thin wrapper: sets up namespace infrastructure, then deploys each
# component in sequence. Each component owns its own deploy.sh.
#
# Usage:
#   ./deploy/deploy-all.sh [--skip-build] [--skip-openshell] [--tag <sha>] [--config <path>]
#   ./deploy/deploy-all.sh --help
#
# Deploy order (recommendation, not a hard dependency — see README):
#   1. Namespace infrastructure (MinIO, router, MCP gateway)
#   2. mock-EHR (FHIR server, needed by acp-writer's fhir-server pod at request time)
#   3. acp-writer (needed by cpg-ingester's delivery pod at request time)
#   4. cpg-ingester
#
# Any order MUST work at startup. If a component fails to start because
# a sibling is absent, that is a bug in the component (fix the component,
# don't encode the dependency into this loop).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck disable=SC1091
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
PASS_THROUGH_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; PASS_THROUGH_ARGS+=("$1" "$2"); shift 2;;
        -h|--help)
            echo "Usage: deploy/deploy-all.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-build      Skip image builds for all components"
            echo "  --skip-openshell  Skip OpenShell sandbox creation for all components"
            echo "  --tag <sha>       Override image tag for all components"
            echo "  --config <path>   Path to cluster.env"
            echo ""
            echo "Deploys: namespace infrastructure → mock-EHR → acp-writer → cpg-ingester"
            exit 0;;
        *) PASS_THROUGH_ARGS+=("$1"); shift;;
    esac
done

load_config "$CONFIG_PATH"
preflight

log_step "Deploying all CPG-to-ACP components (namespace=$NAMESPACE)"

# Step 1: Namespace infrastructure
log_step "Setting up namespace infrastructure"
"$SCRIPT_DIR/setup/setup-namespace.sh" --config "$CONFIG_PATH"

# Step 2-4: Components
for component in mock-EHR acp-writer cpg-ingester; do
    script="$REPO_ROOT/$component/deploy/deploy.sh"
    if [ -f "$script" ]; then
        log_step "Deploying $component"
        "$script" "${PASS_THROUGH_ARGS[@]}" || {
            log "ERROR: $component deployment failed. Later components not deployed."
            log "  Fix and re-run: $component/deploy/deploy.sh ${PASS_THROUGH_ARGS[*]}"
            exit 1
        }
    else
        log "WARNING: $script not found — skipping $component"
    fi
done

log_step "All components deployed successfully"
