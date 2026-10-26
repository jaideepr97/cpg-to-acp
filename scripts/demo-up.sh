#!/usr/bin/env bash
# scripts/demo-up.sh — start the local demo stack (orchestrated compose profile) in podman.
#
# Usage:
#   scripts/demo-up.sh --clean [--model MODEL] [--build]
#   scripts/demo-up.sh --restore [NAME] [--model MODEL] [--build]
#   scripts/demo-up.sh --help
#
#   --clean          Remove all project data and start empty (fresh Medplum, no guidelines, no runs).
#   --restore [NAME] Remove current data, then restore the backup working/backups/NAME
#                    (default: the newest backup) and start. State comes back as it was:
#                    guidelines, run history, patients, care plans.
#   --model MODEL    LLM model id sent through LiteLLM (default: gpt-6-astra).
#   --build          Force an image rebuild (podman compose up --build). Without it, images are
#                    built only when missing, so a code change needs --build to take effect.
#
# Prerequisites: podman machine running; platform/litellm/deploy/.env and mock-EHR/deploy/.env present.
# Take a backup with scripts/demo-backup.sh; stop with scripts/demo-down.sh.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/demo-common.sh"

MODE="" BACKUP_NAME="" MODEL="$DEMO_DEFAULT_MODEL" BUILD_FLAG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --clean) MODE=clean; shift;;
        --restore) MODE=restore; shift; if [ $# -gt 0 ] && [[ "$1" != --* ]]; then BACKUP_NAME="$1"; shift; fi;;
        --model) MODEL="$2"; shift 2;;
        --build) BUILD_FLAG="--build"; shift;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
        *) die "unknown argument: $1 (see --help)";;
    esac
done
[ -n "$MODE" ] || die "choose --clean or --restore (see --help)"

require_podman
cd "$REPO_ROOT"
[ -f platform/litellm/deploy/.env ] || die "platform/litellm/deploy/.env is missing (LiteLLM gateway key)"
[ -f mock-EHR/deploy/.env ] || die "mock-EHR/deploy/.env is missing (Medplum settings)"

if [ "$MODE" = restore ]; then
    if [ -z "$BACKUP_NAME" ]; then
        BACKUP_NAME=$(ls -1 "$BACKUP_ROOT" 2>/dev/null | grep -E '^[0-9]{8}T[0-9]{4,6}' | sort | tail -1 || true)
        [ -n "$BACKUP_NAME" ] || die "no backups under $BACKUP_ROOT; run scripts/demo-backup.sh first"
    fi
    BACKUP_DIR="$BACKUP_ROOT/$BACKUP_NAME"
    if [ ! -f "$BACKUP_DIR/manifest.json" ]; then
        # Backups made by hand before these scripts existed: volume tars plus smart-config.json at the top level.
        [ -f "$BACKUP_DIR/medplum-postgres-data.tar" ] || die "not a demo backup (no manifest.json and no volume archives): $BACKUP_DIR"
        log "note: $BACKUP_NAME has no manifest.json (pre-script backup); restoring from its volume archives"
    fi
    for v in "${DEMO_VOLUMES[@]}"; do
        if [ ! -f "$BACKUP_DIR/$v.tar" ]; then
            # Backups taken before the engine database was persisted lack sonataflow-data; restore without run history.
            [ "$v" = sonataflow-data ] && { log "note: $BACKUP_NAME has no sonataflow-data.tar (older backup); run history will start empty"; continue; }
            die "backup is missing volume archive $v.tar"
        fi
    done
fi

# --- 1. Prerequisite files the compose files mount -------------------------------------------
mkdir -p working/orchestrated
if [ ! -f working/orchestrated/s3-config.json ]; then
    log "Writing the local SeaweedFS S3 identity (dev credentials, matches compose defaults)"
    cat > working/orchestrated/s3-config.json <<'EOF'
{"identities":[{"name":"slice-artifact-store","credentials":[{"accessKey":"slice-access","secretKey":"slice-secret"}],"actions":["Admin","Read","Write","List","Tagging"]}]}
EOF
fi
log "Rendering SonataFlow workflows for compose"
"$(python_with_yaml)" scripts/render-workflows-for-compose.py >/dev/null

# --- 2. Remove whatever is running and its data ---------------------------------------------
# podman compose 1.5 can leave project containers behind on the first teardown; run it twice.
log "Removing the current stack and its volumes"
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
for v in "${DEMO_VOLUMES[@]}"; do podman volume rm -f "$(volume_name "$v")" >/dev/null 2>&1 || true; done
rm -rf .medplum/* acp-writer/ui/public/smart-config.json
mkdir -p .medplum
# The acp-writer UI bind-mounts smart-config.json. If the file does not exist when the stack starts, podman
# creates a directory at that path and the Medplum loader can no longer write the file. Seed a placeholder;
# the loader (clean) or the restore step below replaces it.
printf '{}\n' > acp-writer/ui/public/smart-config.json

# --- 3. Restore data if asked -----------------------------------------------------------------
export LLM_MODEL="$MODEL"
export MEDPLUM_SKIP_LOAD=0
if [ "$MODE" = restore ]; then
    if [ -f "$BACKUP_DIR/manifest.json" ]; then
        log "Restoring backup $BACKUP_NAME ($(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m.get("created_at",""), "git", m.get("git_sha",""))' "$BACKUP_DIR/manifest.json"))"
    else
        log "Restoring backup $BACKUP_NAME"
    fi
    for v in "${DEMO_VOLUMES[@]}"; do
        name=$(volume_name "$v")
        podman volume create "$name" >/dev/null
        [ -f "$BACKUP_DIR/$v.tar" ] || continue
        podman volume import "$name" "$BACKUP_DIR/$v.tar"
        log "  restored volume $name"
    done
    for f in "${DEMO_STATE_FILES[@]}"; do
        if [ -e "$BACKUP_DIR/files/$f" ]; then
            rm -rf "$f"; mkdir -p "$(dirname "$f")"; cp -R "$BACKUP_DIR/files/$f" "$f"
            log "  restored $f"
        fi
    done
    # Pre-script backups carry smart-config.json at the top level and no .medplum/ directory. The SMART
    # config holds the client id and secret the loader registered, which is all the FHIR credentials file
    # needs, so rebuild both from it (values are copied, never printed).
    if [ "$(cat acp-writer/ui/public/smart-config.json 2>/dev/null)" = "{}" ] && [ -f "$BACKUP_DIR/smart-config.json" ]; then
        cp "$BACKUP_DIR/smart-config.json" acp-writer/ui/public/smart-config.json
        log "  restored acp-writer/ui/public/smart-config.json (pre-script layout)"
    fi
    if [ ! -f .medplum/medplum-fhir.env ] && grep -q clientSecret acp-writer/ui/public/smart-config.json 2>/dev/null; then
        python3 - acp-writer/ui/public/smart-config.json .medplum/medplum-fhir.env <<'PYEOF'
import json, sys
cfg = json.load(open(sys.argv[1]))
with open(sys.argv[2], "w") as out:
    out.write(f"FHIR_CLIENT_ID={cfg['clientId']}\nFHIR_CLIENT_SECRET={cfg['clientSecret']}\n")
PYEOF
        log "  rebuilt .medplum/medplum-fhir.env from the SMART config"
    fi
    # The Medplum database is restored, so the loader must not try to create the project again.
    export MEDPLUM_SKIP_LOAD=1
fi

# --- 4. Start ----------------------------------------------------------------------------------
# The engine's Maven cache is an external volume: created once, kept across --clean and --purge.
podman volume exists "$SONATAFLOW_M2_VOLUME" || podman volume create "$SONATAFLOW_M2_VOLUME" >/dev/null
log "Starting the orchestrated stack (model $MODEL)${BUILD_FLAG:+ with image rebuild}"
"${COMPOSE[@]}" up -d $BUILD_FLAG

if [ "$MODE" = clean ]; then
    log "Waiting for the Medplum loader (patients, practitioners, SMART client)"
    loader="${DEMO_PROJECT}_medplum-loader_1"
    start=$SECONDS
    while [ "$(podman inspect -f '{{.State.Status}}' "$loader" 2>/dev/null)" != exited ]; do
        (( SECONDS - start > 600 )) && die "Medplum loader did not finish within 10 minutes; see: podman logs $loader"
        sleep 3
    done
    if [ "$(podman inspect -f '{{.State.ExitCode}}' "$loader")" -ne 0 ]; then
        podman logs --tail 15 "$loader" 2>&1 | sed 's/^/  loader: /'
        die "Medplum loader failed (log above; full log: podman logs $loader)"
    fi
    log "  loader finished"
    # The loader wrote a fresh SMART client id; the UI's nginx reads the file at start.
    podman restart "${DEMO_PROJECT}_acp-writer-ui_1" >/dev/null 2>&1 || true
fi

# --- 5. Wait for health ------------------------------------------------------------------------
log "Waiting for services"
wait_for_http http://localhost:8103/healthcheck "Medplum" 300
wait_for_http http://localhost:8097/q/health "SonataFlow engine" 600 '"status": *"UP"'
wait_for_http http://localhost:8095/health "cpg-ingester BFF" 300 '"minio": *true'
wait_for_http http://localhost:8094/api/v1/status "acp-writer BFF" 300
wait_for_http http://localhost:3003/ "cpg-ingester UI" 120
wait_for_http http://localhost:3001/ "acp-writer UI" 120
wait_for_http http://localhost:3000/ "CareView" 120

if [ "$MODE" = restore ]; then
    log "Restored state check"
    status=$(curl -s http://localhost:8094/api/v1/status || true)
    log "  acp-writer: $(printf '%s' "$status" | python3 -c 'import json,sys; d=json.load(sys.stdin); de=d.get("decisionEngine") or {}; kb=d.get("knowledgeBase") or {}; print("DMN models", de.get("modelsDeployed"), "| knowledge base", {k: v for k, v in kb.items() if isinstance(v, (int, bool))})' 2>/dev/null || printf '%s' "${status:0:160}")"
    log "  acp-writer care plans: $(curl -s http://localhost:8094/api/v1/careplans | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d, list) else len(d.get("careplans", d.get("items", []))))' 2>/dev/null || echo '?')"
    log "  cpg-ingester runs: $(curl -s http://localhost:8095/api/v1/runs | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d, list) else len(d.get("runs", [])))' 2>/dev/null || echo '?')"
    log "  acp-writer runs: $(curl -s http://localhost:8094/api/v1/runs | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d, list) else len(d.get("runs", [])))' 2>/dev/null || echo '?')"
fi
print_urls
