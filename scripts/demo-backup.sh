#!/usr/bin/env bash
# scripts/demo-backup.sh — snapshot the local demo stack's state so demo-up.sh --restore can bring it back.
#
# Usage:
#   scripts/demo-backup.sh [NAME] [--keep-stopped]
#
#   NAME            Backup name (default: UTC timestamp like 20261026T1530). Written to working/backups/NAME/.
#   --keep-stopped  Leave the stack stopped afterwards (default: start it again once the snapshot is taken).
#
# The stack is stopped while the volumes are exported so the databases are consistent; it is started again
# afterwards. Captured: the artifact store (guidelines, published artifacts), Medplum (patients, care plans),
# automation records, publication jobs, and the Medplum-written config files. Workflow run history is not
# captured: the dev-mode engine keeps it in memory.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/demo-common.sh"

NAME="" KEEP_STOPPED=0
while [ $# -gt 0 ]; do
    case "$1" in
        --keep-stopped) KEEP_STOPPED=1; shift;;
        -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
        --*) die "unknown argument: $1";;
        *) NAME="$1"; shift;;
    esac
done
NAME="${NAME:-$(date -u +%Y%m%dT%H%M)}"
[[ "$NAME" =~ ^[A-Za-z0-9._-]+$ ]] || die "backup name may contain only letters, digits, dot, dash, underscore"

require_podman
cd "$REPO_ROOT"
BACKUP_DIR="$BACKUP_ROOT/$NAME"
[ ! -e "$BACKUP_DIR" ] || die "backup already exists: $BACKUP_DIR"

for v in "${DEMO_VOLUMES[@]}"; do
    podman volume exists "$(volume_name "$v")" || die "volume $(volume_name "$v") does not exist; is the stack up? (scripts/demo-up.sh)"
done

# Record the model the running stack uses, without touching any other environment value.
MODEL=$(podman inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "${DEMO_PROJECT}_acp-llm-reasoning_1" 2>/dev/null | sed -n 's/^LLM_MODEL=//p' | head -1 || true)

log "Stopping the stack for a consistent snapshot"
"${COMPOSE[@]}" stop >/dev/null 2>&1 || die "could not stop the stack"

mkdir -p "$BACKUP_DIR/files"
for v in "${DEMO_VOLUMES[@]}"; do
    name=$(volume_name "$v")
    podman volume export "$name" --output "$BACKUP_DIR/$v.tar"
    log "  exported $name ($(du -h "$BACKUP_DIR/$v.tar" | cut -f1))"
done
for f in "${DEMO_STATE_FILES[@]}"; do
    if [ -e "$f" ]; then
        mkdir -p "$BACKUP_DIR/files/$(dirname "$f")"
        cp -R "$f" "$BACKUP_DIR/files/$f"
        log "  copied $f"
    fi
done
python3 - "$BACKUP_DIR/manifest.json" "$NAME" "${MODEL:-}" <<'EOF'
import json, subprocess, sys, datetime
path, name, model = sys.argv[1:4]
def git(*args):
    try: return subprocess.check_output(["git", *args], text=True).strip()
    except Exception: return ""
json.dump({
    "name": name,
    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "git_sha": git("rev-parse", "--short", "HEAD"),
    "git_branch": git("branch", "--show-current"),
    "model": model,
    "profile": "orchestrated",
}, open(path, "w"), indent=2)
EOF
log "Backup written: $BACKUP_DIR ($(du -sh "$BACKUP_DIR" | cut -f1))"

if [ "$KEEP_STOPPED" -eq 1 ]; then
    log "Stack left stopped (scripts/demo-up.sh --restore $NAME brings it back; podman compose ... start resumes it)"
    exit 0
fi
log "Starting the stack again"
"${COMPOSE[@]}" start >/dev/null 2>&1 || die "could not restart the stack"
wait_for_http http://localhost:8097/q/health "SonataFlow engine" 600 '"status": *"UP"'
wait_for_http http://localhost:8095/health "cpg-ingester BFF" 300 '"minio": *true'
wait_for_http http://localhost:8094/api/v1/status "acp-writer BFF" 300
log "Done. Restore later with: scripts/demo-up.sh --restore $NAME"
