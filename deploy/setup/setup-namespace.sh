#!/usr/bin/env bash
# deploy/setup/setup-namespace.sh — Set up shared namespace infrastructure
#
# Creates: MinIO, openshell-router (from component fragments), MCP gateway.
# Idempotent — safe to run repeatedly.
#
# Usage:
#   ./deploy/setup/setup-namespace.sh [--config <path>]
#
# Prerequisites:
#   - oc login completed
#   - deploy/config/cluster.env configured
#   - K8s Secrets created (setup-secrets.sh)
#   - OpenShell controller running in the namespace
#   - SonataFlow platform CRs deployed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck disable=SC1091
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; shift 2;;
        -h|--help)
            echo "Usage: setup-namespace.sh [--config <cluster.env>]"
            echo ""
            echo "Sets up shared infrastructure: MinIO, openshell-router, MCP gateway."
            exit 0;;
        *) shift;;
    esac
done

load_config "$CONFIG_PATH"
preflight

log_step "Setting up namespace infrastructure ($NAMESPACE)"

# --- MinIO ---

log "Deploying MinIO..."
# Render the MinIO manifest (it references the minio-credentials secret)
oc apply -f "$REPO_ROOT/deploy/platform/minio.yaml" -n "$NAMESPACE" 2>/dev/null
wait_for_pod_ready "$(oc get pods -n "$NAMESPACE" -l app=minio -o name 2>/dev/null | head -1 | sed 's|pod/||')" 60 || log "WARNING: MinIO not ready"

# --- Openshell Router ---

log "Generating openshell-router ConfigMap from component fragments..."
RENDERED_DIR="$REPO_ROOT/deploy/.rendered"
mkdir -p "$RENDERED_DIR"

# Generate nginx config by concatenating component fragments
{
    echo 'worker_processes 1;'
    echo 'events { worker_connections 128; }'
    echo ''
    echo 'http {'
    echo '    server_names_hash_bucket_size 128;'
    echo '    proxy_read_timeout 600s;'
    echo '    proxy_send_timeout 600s;'
    echo '    proxy_connect_timeout 10s;'
    echo '    client_max_body_size 50m;'
    echo ''

    # Concatenate component fragments (rendered with envsubst)
    for fragment in \
        "$REPO_ROOT/acp-writer/deploy/openshell/router-fragment.conf.tmpl" \
        "$REPO_ROOT/cpg-ingester/deploy/openshell/router-fragment.conf.tmpl"; do
        if [ -f "$fragment" ]; then
            envsubst < "$fragment"
            echo ""
        fi
    done

    # Default server: health probe endpoint + 404 fallback for unmatched hostnames
    echo '    server {'
    echo '        listen 8080 default_server;'
    echo '        location /health {'
    echo '            return 200 '\''{"status":"UP","service":"openshell-router"}'\'';'
    echo '            add_header Content-Type application/json;'
    echo '        }'
    echo '        location / {'
    echo '            return 404 '\''{"error":"no matching sandbox for this hostname"}'\'';'
    echo '            add_header Content-Type application/json;'
    echo '        }'
    echo '    }'

    echo '}'
} > "$RENDERED_DIR/openshell-router-nginx.conf"

# Validate nginx config before applying.
# On a fresh namespace the router pod doesn't exist yet — nginx -t needs a pod
# to run in, so skip validation there (the post-restart probe below still runs).
ROUTER_POD=$(oc get pods -n "$NAMESPACE" -l app=openshell-router \
    --field-selector=status.phase=Running -o name 2>/dev/null | head -1 | sed 's|pod/||')
if [ -n "$ROUTER_POD" ]; then
    log "Validating nginx config (nginx -t in $ROUTER_POD)..."
    oc cp "$RENDERED_DIR/openshell-router-nginx.conf" \
        "${ROUTER_POD}:/tmp/candidate-nginx.conf" -n "$NAMESPACE"

    validation_result=$(oc exec "$ROUTER_POD" -n "$NAMESPACE" -- \
        nginx -t -c /tmp/candidate-nginx.conf 2>&1 || echo "VALIDATION_FAILED")
    if echo "$validation_result" | grep -q "VALIDATION_FAILED\|emerg\|error"; then
        echo "ERROR: Generated nginx config is invalid:"
        echo "$validation_result"
        echo ""
        echo "Check the router fragments in <component>/deploy/openshell/router-fragment.conf.tmpl"
        exit 1
    fi
    log "  nginx -t passed"
else
    log "  Router not running yet (fresh namespace) — skipping nginx -t; endpoint probe below verifies after startup"
fi

# Apply as ConfigMap
oc create configmap openshell-router-config \
    --from-file=nginx.conf="$RENDERED_DIR/openshell-router-nginx.conf" \
    -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f - 2>/dev/null

# Deploy the router if not present
oc apply -f "$REPO_ROOT/deploy/openshell-router/deploy.yaml" -n "$NAMESPACE" 2>/dev/null

# Restart to pick up new config
oc rollout restart deployment/openshell-router -n "$NAMESPACE" 2>/dev/null || true
log "Waiting for router restart..."
oc rollout status deployment/openshell-router -n "$NAMESPACE" --timeout=60s 2>/dev/null || true

# Probe every generated server_name
log "Verifying router endpoints..."
ROUTER_ERRORS=0
for fragment in \
    "$REPO_ROOT/acp-writer/deploy/openshell/router-fragment.conf.tmpl" \
    "$REPO_ROOT/cpg-ingester/deploy/openshell/router-fragment.conf.tmpl"; do
    [ -f "$fragment" ] || continue
    fragment_name=$(basename "$(dirname "$(dirname "$fragment")")")
    server_names=$(grep "server_name " "$fragment" | awk '{print $2}' | grep -v '\.')
    for svc in $server_names; do
        code=$(oc exec deployment/openshell-router -n "$NAMESPACE" -- \
            curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
            -H "Host: ${svc}" \
            http://localhost:8080/health 2>/dev/null || echo "000")
        if [ "$code" = "200" ]; then
            echo "  ✓ $svc: HTTP 200"
        else
            echo "  ✗ $svc: HTTP $code (fragment: $fragment_name)"
            ROUTER_ERRORS=$((ROUTER_ERRORS + 1))
        fi
    done
done
if [ $ROUTER_ERRORS -gt 0 ]; then
    log "WARNING: $ROUTER_ERRORS router endpoint(s) unreachable (sandboxes may not be created yet)"
fi

# --- MCP Gateway ---

log "Deploying MCP Gateway (shared resources only)..."
# Render the gateway template (has namespace + cluster domain refs)
render_template "$REPO_ROOT/deploy/mcp-gateway/gateway.yaml.tmpl" "$RENDERED_DIR/mcp-gateway.yaml"
oc apply -f "$RENDERED_DIR/mcp-gateway.yaml" -n "$NAMESPACE" 2>/dev/null || log "  WARNING: failed to apply gateway"
# Virtual servers are cross-component, no templating needed
oc apply -f "$REPO_ROOT/deploy/mcp-gateway/virtual-servers.yaml" -n "$NAMESPACE" 2>/dev/null || log "  WARNING: failed to apply virtual-servers"

# --- Quota check ---

log "Checking namespace resource quotas..."
quota_count=$(oc get resourcequota -n "$NAMESPACE" -o json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    items = data.get('items', [])
    if not items:
        print('none')
    else:
        for q in items:
            name = q.get('metadata', {}).get('name', '?')
            hard = q.get('spec', {}).get('hard', {})
            for resource, limit in sorted(hard.items()):
                print(f'  {name}: {resource} = {limit}')
except:
    print('none')
" 2>/dev/null || echo "none")

if [ "$quota_count" != "none" ]; then
    log "  Namespace ResourceQuota(s) detected:"
    echo "$quota_count"
    log "  Full deployment needs ~6.5 CPU / ~12Gi memory."
    log "  If quotas are insufficient, some pods will fail to schedule."
else
    log "  No ResourceQuota found (no resource limits enforced)"
fi

log_step "Namespace infrastructure setup complete"
