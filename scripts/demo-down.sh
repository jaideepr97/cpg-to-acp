#!/usr/bin/env bash
# scripts/demo-down.sh — stop the local demo stack.
#
# Usage:
#   scripts/demo-down.sh            Stop the containers; keep all data (volumes and config files).
#   scripts/demo-down.sh --purge    Stop and delete all project data. Take a backup first if you want it back.
#
# A stopped stack is resumed with demo-up.sh --restore (from a backup) or, to continue exactly where it was
# without a backup, with:  podman compose -f compose.yml -f compose.orchestrated.yml --profile orchestrated -p cpg-to-acp start
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/demo-common.sh"

PURGE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --purge) PURGE=1; shift;;
        -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
        *) die "unknown argument: $1";;
    esac
done

require_podman
cd "$REPO_ROOT"

if [ "$PURGE" -eq 1 ]; then
    log "Removing the stack and all of its data"
    "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    for v in "${DEMO_VOLUMES[@]}"; do podman volume rm -f "$(volume_name "$v")" >/dev/null 2>&1 || true; done
    rm -rf .medplum/* acp-writer/ui/public/smart-config.json
    log "Done. Nothing is running and no project data remains."
else
    log "Stopping the stack (data is kept)"
    "${COMPOSE[@]}" stop >/dev/null 2>&1 || die "could not stop the stack"
    log "Done. Volumes and config files are intact."
fi
