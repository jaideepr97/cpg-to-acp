#!/usr/bin/env bash
# deploy/lib.sh — Minimal shared helpers for the deploy framework.
#
# Changes here are cross-team changes. Keep it small and stable.
# Never put component-specific knowledge in this file.
#
# Source this file: source "$(dirname "$0")/../deploy/lib.sh"
#                   (or adjust the path for your script's location)

# Fail on errors, undefined vars, pipe failures
set -euo pipefail

# --- Configuration loading ---

load_config() {
    local config_path="${1:-deploy/config/cluster.env}"
    if [ ! -f "$config_path" ]; then
        echo "ERROR: Config file not found: $config_path"
        echo "  Copy deploy/config/cluster.env.template to deploy/config/cluster.env and fill in values."
        exit 1
    fi
    # shellcheck disable=SC1090
    source "$config_path"

    # Compute derived values
    export LLM_BASE_URL="${MAAS_GATEWAY_URL}/${MAAS_ROUTE_SEGMENT}"
    export IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo 'latest')}"
    # Extract MLflow hostname for use in OpenShell policy templates
    export MLFLOW_HOST
    MLFLOW_HOST=$(echo "${MLFLOW_TRACKING_URI:-}" | sed 's|https\?://||' | sed 's|/.*||')
}

# --- Preflight validation ---

preflight() {
    # Call this first in every entry-point script.
    # Validates prerequisites, failing with a one-line fix per problem.
    local errors=0

    if ! oc whoami &>/dev/null; then
        echo "ERROR: Not logged into OpenShift. Run: oc login <cluster-url>"
        errors=$((errors + 1))
    fi

    if [ -z "${NAMESPACE:-}" ]; then
        echo "ERROR: NAMESPACE not set. Source deploy/config/cluster.env or pass --config."
        errors=$((errors + 1))
    else
        local current_project
        current_project=$(oc project -q 2>/dev/null || echo "")
        if [ "$current_project" != "$NAMESPACE" ]; then
            echo "WARNING: Current project '$current_project' != configured NAMESPACE '$NAMESPACE'"
            echo "  Switching to $NAMESPACE..."
            oc project "$NAMESPACE" 2>/dev/null || {
                echo "ERROR: Cannot switch to namespace $NAMESPACE"
                errors=$((errors + 1))
            }
        fi
    fi

    for var in MAAS_GATEWAY_URL MAAS_ROUTE_SEGMENT LLM_MODEL_DEFAULT GIT_REPO; do
        if [ -z "${!var:-}" ]; then
            echo "ERROR: Required config variable $var is empty. Check deploy/config/cluster.env."
            errors=$((errors + 1))
        fi
    done

    for tool in oc helm envsubst python3; do
        if ! command -v "$tool" &>/dev/null; then
            echo "ERROR: Required tool '$tool' not found on PATH."
            errors=$((errors + 1))
        fi
    done

    if [ $errors -gt 0 ]; then
        echo ""
        echo "$errors preflight error(s). Fix the above and retry."
        exit 1
    fi
}

preflight_openshell() {
    # Additional check for scripts that need the openshell CLI.
    if ! command -v openshell &>/dev/null; then
        echo "ERROR: 'openshell' CLI not found on PATH."
        echo "  Install from: https://docs.openshell.dev/install"
        exit 1
    fi
    ensure_openshell_portforward
}

# --- OpenShell port-forward management ---

ensure_openshell_portforward() {
    # The openshell CLI needs localhost:18080 → openshell-0:8080.
    # Idempotent: reuse if running, start if not, retry on race.
    if curl -s --max-time 2 http://localhost:18080/ &>/dev/null; then
        return 0
    fi

    # Kill stale forwards
    pkill -f "port-forward.*openshell.*18080" 2>/dev/null || true
    sleep 1

    oc port-forward pod/openshell-0 18080:8080 -n "$NAMESPACE" &>/dev/null &
    local pf_pid=$!
    sleep 3

    if ! curl -s --max-time 2 http://localhost:18080/ &>/dev/null; then
        echo "ERROR: Failed to establish openshell port-forward (PID $pf_pid)"
        echo "  Check: oc get pod openshell-0 -n $NAMESPACE"
        exit 1
    fi
}

# --- Secret reading ---

read_secret() {
    # Read a key from a K8s Secret into stdout (for command substitution).
    #
    # Usage: local val; val=$(read_secret <secret-name> <key>)
    #
    # SECURITY: NEVER echo, log, or tee the return value.
    # This helper enforces set +x for its body to prevent trace leaks.
    # Callers must never run under set -x while holding the result.
    local secret_name="$1"
    local key="$2"

    # Suppress trace output while handling secret material
    { set +x; } 2>/dev/null

    local value
    value=$(oc get secret "$secret_name" -n "$NAMESPACE" -o jsonpath="{.data.$key}" 2>/dev/null | base64 -d)

    if [ -z "$value" ]; then
        echo "ERROR: Could not read key '$key' from secret '$secret_name' in namespace '$NAMESPACE'" >&2
        exit 1
    fi

    printf '%s' "$value"
}

read_secret_optional() {
    # Like read_secret but returns empty string if the secret or key is absent.
    # Use for credentials that may legitimately not exist (e.g. FHIR client in dev mode).
    #
    # SECURITY: same rules as read_secret — NEVER echo, log, or tee.
    local secret_name="$1"
    local key="$2"

    { set +x; } 2>/dev/null

    local value
    value=$(oc get secret "$secret_name" -n "$NAMESPACE" -o jsonpath="{.data.$key}" 2>/dev/null | base64 -d 2>/dev/null || echo "")

    printf '%s' "$value"
}

# --- Template rendering ---

render_template() {
    # Render a .tmpl file with envsubst, writing to deploy/.rendered/
    # Usage: render_template <input.yaml.tmpl> <output.yaml>
    local input="$1"
    local output="$2"

    mkdir -p "$(dirname "$output")"
    envsubst < "$input" > "$output"
}

render_templates_dir() {
    # Render all .tmpl files in a directory
    # Usage: render_templates_dir <input-dir> <output-dir>
    local input_dir="$1"
    local output_dir="$2"

    mkdir -p "$output_dir"
    for tmpl in "$input_dir"/*.tmpl; do
        [ -f "$tmpl" ] || continue
        local basename
        basename=$(basename "$tmpl" .tmpl)
        envsubst < "$tmpl" > "$output_dir/$basename"
    done
}

# --- Pod lifecycle helpers ---

wait_for_pod_ready() {
    # Wait for a pod to reach Running + Ready state.
    # Usage: wait_for_pod_ready <pod-name> [timeout-seconds]
    local pod_name="$1"
    local timeout="${2:-90}"

    for i in $(seq 1 "$timeout"); do
        local phase
        phase=$(oc get pod "$pod_name" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
        if [ "$phase" = "Running" ]; then
            local ready
            ready=$(oc get pod "$pod_name" -n "$NAMESPACE" -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null || echo "false")
            if [ "$ready" = "true" ]; then
                return 0
            fi
        fi
        sleep 1
    done

    echo "ERROR: Pod $pod_name not ready after ${timeout}s (phase: ${phase:-unknown})"
    return 1
}

label_pod() {
    # Apply K8s labels to a pod. Call after wait_for_pod_ready.
    # Usage: label_pod <pod-name> <app-name> <instance>
    local pod_name="$1"
    local app_name="$2"
    local instance="$3"

    oc label pod "$pod_name" -n "$NAMESPACE" \
        "app.kubernetes.io/name=$app_name" \
        "app.kubernetes.io/instance=$instance" \
        --overwrite 2>/dev/null
}

# --- Build helpers ---

start_build_and_wait() {
    # Start a build and wait for completion. Returns 0 on success.
    # Usage: start_build_and_wait <buildconfig-name>
    local bc_name="$1"

    local build_name
    build_name=$(oc start-build "$bc_name" -n "$NAMESPACE" -o name 2>/dev/null)

    if [ -z "$build_name" ]; then
        echo "ERROR: Failed to start build for $bc_name"
        return 1
    fi

    echo "  Started: $build_name"
    oc wait "$build_name" -n "$NAMESPACE" --for=jsonpath='{.status.phase}'=Complete --timeout=600s 2>/dev/null
}

start_builds_parallel() {
    # Start multiple builds in parallel, then wait for all.
    # Usage: start_builds_parallel bc1 bc2 bc3 ...
    local build_names=()
    local failed=0

    for bc in "$@"; do
        local build_name
        build_name=$(oc start-build "$bc" -n "$NAMESPACE" -o name 2>/dev/null || echo "")
        if [ -n "$build_name" ]; then
            echo "  Started: $build_name"
            build_names+=("$build_name")
        else
            echo "  ERROR: Failed to start build for $bc"
            failed=$((failed + 1))
        fi
    done

    echo "  Waiting for ${#build_names[@]} builds..."
    for build_name in "${build_names[@]}"; do
        if ! oc wait "$build_name" -n "$NAMESPACE" --for=jsonpath='{.status.phase}'=Complete --timeout=600s 2>/dev/null; then
            echo "  FAILED: $build_name"
            oc logs "$build_name" -n "$NAMESPACE" --tail=20 2>/dev/null || true
            failed=$((failed + 1))
        else
            echo "  Complete: $build_name"
        fi
    done

    if [ $failed -gt 0 ]; then
        echo "  $failed build(s) failed"
        return 1
    fi
    return 0
}

# --- Pruning ---

prune_builds() {
    # Delete completed/failed build pods for a component prefix.
    # Usage: prune_builds <prefix>  (e.g., "acp-writer")
    local prefix="$1"
    oc get builds -n "$NAMESPACE" --no-headers | \
        grep "^${prefix}" | \
        grep -E "Complete|Failed|Cancelled" | \
        awk '{print $1}' | \
        xargs -r oc delete build -n "$NAMESPACE" 2>/dev/null || true
}

prune_image_tags() {
    # Keep the last N SHA tags on an ImageStream, delete older ones.
    # Sorted by creation timestamp (newest first). Never deletes the current IMAGE_TAG.
    # Usage: prune_image_tags <imagestream> [keep-count]
    local is_name="$1"
    local keep="${2:-5}"

    # Get SHA tags sorted by creation timestamp (newest first)
    local sorted_sha_tags
    sorted_sha_tags=$(oc get is "$is_name" -n "$NAMESPACE" -o json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    tags = []
    for t in data.get('status', {}).get('tags', []):
        name = t.get('tag', '')
        # SHA tags are 7-char hex
        if len(name) == 7 and all(c in '0123456789abcdef' for c in name):
            items = t.get('items', [])
            created = items[0].get('created', '') if items else ''
            tags.append((created, name))
    # Sort by creation timestamp, newest first
    tags.sort(reverse=True)
    for _, name in tags:
        print(name)
except:
    pass
" 2>/dev/null || echo "")

    if [ -z "$sorted_sha_tags" ]; then
        return 0
    fi

    local count=0
    for tag in $sorted_sha_tags; do
        count=$((count + 1))
        # Never delete the currently-deployed tag
        if [ "$tag" = "${IMAGE_TAG:-}" ]; then
            continue
        fi
        if [ $count -gt "$keep" ]; then
            echo "  Pruning $is_name:$tag"
            oc tag -d "$is_name:$tag" -n "$NAMESPACE" 2>/dev/null || true
        fi
    done
}

# --- Logging ---

log() { echo "[deploy] $*"; }
log_step() { echo ""; echo "=== $* ==="; }
