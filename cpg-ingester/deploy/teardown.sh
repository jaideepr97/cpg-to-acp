#!/usr/bin/env bash
# cpg-ingester/deploy/teardown.sh — Remove cpg-ingester deployment

set -euo pipefail
[ -n "${ZSH_VERSION:-}" ] && setopt SH_WORD_SPLIT

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
FULL_WIPE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; shift 2;;
        --full-wipe)
            echo "⚠ --full-wipe will delete cpg-ingester ImageStreams."
            echo "  Type 'wipe' to confirm:"
            read -r confirm
            [ "$confirm" != "wipe" ] && echo "Aborted." && exit 1
            FULL_WIPE=true; shift;;
        -h|--help)
            echo "Usage: cpg-ingester/deploy/teardown.sh [--config <path>] [--full-wipe]"
            exit 0;;
        *) shift;;
    esac
done

load_config "$CONFIG_PATH"
preflight

log_step "Tearing down cpg-ingester (namespace=$NAMESPACE)"

if command -v openshell &>/dev/null; then
    ensure_openshell_portforward
    "$SCRIPT_DIR/openshell/deploy.sh" teardown --config "$CONFIG_PATH" || true
fi

for dep in cpg-ing-ingestion cpg-ing-llm-analysis cpg-ing-assembly cpg-ing-delivery; do
    oc scale deployment "$dep" --replicas=0 -n "$NAMESPACE" 2>/dev/null || true
done

helm uninstall cpg-ing -n "$NAMESPACE" 2>/dev/null || log "  cpg-ing not installed"

oc delete -f "$SCRIPT_DIR/orchestrator/cpg-ingester-workflow.yaml" -n "$NAMESPACE" 2>/dev/null || true

for bc in cpg-ingester-ingestion cpg-ingester-llm cpg-ingester-assembly cpg-ingester-delivery cpg-ingester-bff cpg-ingester-ui; do
    oc delete bc "$bc" -n "$NAMESPACE" 2>/dev/null || true
done
prune_builds "cpg-ingester"

if [ "$FULL_WIPE" = true ]; then
    for is in cpg-ingester-ingestion cpg-ingester-llm cpg-ingester-assembly cpg-ingester-delivery cpg-ingester-bff cpg-ingester-ui; do
        oc delete is "$is" -n "$NAMESPACE" 2>/dev/null || true
    done
fi

log_step "cpg-ingester teardown complete"
