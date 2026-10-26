#!/usr/bin/env bash
# Shared settings for the local demo stack scripts (demo-up.sh, demo-backup.sh, demo-down.sh).
# Sourced, not executed.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_PROJECT="${DEMO_PROJECT:-cpg-to-acp}"
DEMO_DEFAULT_MODEL="gpt-6-astra"
BACKUP_ROOT="$REPO_ROOT/working/backups"

# The orchestrated profile: SonataFlow dev-mode plus one pod per security profile.
COMPOSE=(podman compose -f "$REPO_ROOT/compose.yml" -f "$REPO_ROOT/compose.orchestrated.yml" --profile orchestrated -p "$DEMO_PROJECT")

# Named volumes that hold demo state. podman compose prefixes them with the project name.
DEMO_VOLUMES=(
    orchestrated-artifact-store-data   # uploaded CPGs, published artifacts, PHI bundles
    medplum-postgres-data              # patients, CarePlans, SMART client
    automation-data                    # automation service records
    acp-job-data                       # approval/publication jobs (also rebuilds the writer's care-plan list)
)

# Bind-mounted files the Medplum loader writes; they must match the Medplum database they were created with.
DEMO_STATE_FILES=(
    .medplum
    acp-writer/ui/public/smart-config.json
)

log()  { printf '[demo] %s\n' "$*"; }
die()  { printf '[demo] ERROR: %s\n' "$*" >&2; exit 1; }

require_podman() {
    command -v podman >/dev/null 2>&1 || die "podman is not installed"
    podman info >/dev/null 2>&1 || die "podman is not reachable; run: podman machine start"
}

volume_name() { printf '%s_%s' "$DEMO_PROJECT" "$1"; }

# The workflow renderer needs PyYAML; prefer a repo virtualenv that has it over the system python.
python_with_yaml() {
    local candidate
    for candidate in "$REPO_ROOT/cpg-ingester/.venv/bin/python" "$REPO_ROOT/acp-writer/.venv/bin/python" python3; do
        if "$candidate" -c 'import yaml' >/dev/null 2>&1; then printf '%s' "$candidate"; return 0; fi
    done
    die "no python with PyYAML found (tried the component virtualenvs and python3); pip install pyyaml"
}

# wait_for_http <url> <label> [timeout-seconds] [grep-pattern]
wait_for_http() {
    local url="$1" label="$2" timeout="${3:-180}" pattern="${4:-}" start=$SECONDS body
    while :; do
        body=$(curl -s --max-time 5 "$url" 2>/dev/null || true)
        if [ -n "$body" ] && { [ -z "$pattern" ] || grep -qE "$pattern" <<<"$body"; }; then
            log "  ready: $label"
            return 0
        fi
        if (( SECONDS - start > timeout )); then
            die "timed out after ${timeout}s waiting for $label ($url)"
        fi
        sleep 3
    done
}

print_urls() {
    cat <<EOF
[demo] Stack is up (model: ${LLM_MODEL:-$DEMO_DEFAULT_MODEL})
  CareView (mock EHR, launches a care plan)  http://localhost:3000
  acp-writer UI                              http://localhost:3001
  Medplum                                    http://localhost:3002
  cpg-ingester UI (upload guidelines)        http://localhost:3003
  SonataFlow dev UI                          http://localhost:8097/q/dev-ui
  MLflow                                     http://localhost:5000
EOF
}
