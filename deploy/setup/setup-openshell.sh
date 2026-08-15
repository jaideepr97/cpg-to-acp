#!/usr/bin/env bash
# deploy/setup/setup-openshell.sh — Provision OpenShell + SonataFlow in a namespace
#
# Creates all prerequisite resources for OpenShell sandboxes and SonataFlow
# workflows. Idempotent — safe to run repeatedly. Requires cluster-admin
# (SCC binding + ClusterRole for token review).
#
# Usage:
#   ./deploy/setup/setup-openshell.sh [--config <cluster.env>]
#
# If your platform team pre-provisions OpenShell, skip this script.
# The README documents every resource it creates so they can provision
# equivalently.

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
            echo "Usage: setup-openshell.sh [--config <cluster.env>]"
            echo ""
            echo "Provisions OpenShell gateway + SonataFlow platform in the namespace."
            echo "Requires cluster-admin. Run once per namespace."
            exit 0;;
        *) shift;;
    esac
done

load_config "$CONFIG_PATH"
preflight

log_step "Provisioning OpenShell + SonataFlow in $NAMESPACE"

# --- ServiceAccounts ---

log "Creating ServiceAccounts..."
oc create sa openshell -n "$NAMESPACE" 2>/dev/null && log "  Created openshell" || log "  openshell exists"
oc create sa openshell-sandbox -n "$NAMESPACE" 2>/dev/null && log "  Created openshell-sandbox" || log "  openshell-sandbox exists"

# --- Roles ---

log "Creating Roles..."
oc apply -n "$NAMESPACE" -f - <<'EOF'
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: openshell-gateway
rules:
- apiGroups: ["agents.x-k8s.io"]
  resources: ["sandboxes", "sandboxes/status"]
  verbs: ["create", "delete", "get", "list", "patch", "update", "watch"]
- apiGroups: [""]
  resources: ["pods", "pods/log", "pods/exec", "services", "events", "persistentvolumeclaims"]
  verbs: ["create", "delete", "get", "list", "patch", "update", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: openshell-sandbox
rules:
- apiGroups: ["agents.x-k8s.io"]
  resources: ["sandboxes", "sandboxes/status"]
  verbs: ["create", "delete", "get", "list", "patch", "update", "watch"]
- apiGroups: [""]
  resources: ["pods", "pods/log", "pods/exec", "events"]
  verbs: ["get", "list", "watch", "create", "delete"]
EOF

# --- RoleBindings ---

log "Creating RoleBindings..."
oc apply -n "$NAMESPACE" -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: openshell-gateway
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: openshell-gateway
subjects:
- kind: ServiceAccount
  name: openshell
  namespace: $NAMESPACE
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: openshell-sandbox
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: openshell-sandbox
subjects:
- kind: ServiceAccount
  name: openshell-sandbox
  namespace: $NAMESPACE
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: openshell-sandbox-scc
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:openshift:scc:privileged
subjects:
- kind: ServiceAccount
  name: openshell-sandbox
  namespace: $NAMESPACE
EOF

# --- ClusterRole + ClusterRoleBinding for token review ---

log "Creating ClusterRole + ClusterRoleBinding for token review..."
oc apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ${NAMESPACE}-openshell-tokenreview
rules:
- apiGroups: ["authentication.k8s.io"]
  resources: ["tokenreviews"]
  verbs: ["create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ${NAMESPACE}-openshell-tokenreview
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: ${NAMESPACE}-openshell-tokenreview
subjects:
- kind: ServiceAccount
  name: openshell
  namespace: $NAMESPACE
EOF

# --- JWT keys (generate fresh if not present) ---

if oc get secret sandbox-jwt -n "$NAMESPACE" &>/dev/null; then
    log "sandbox-jwt secret exists — skipping key generation"
else
    log "Generating Ed25519 JWT keys..."
    TMPDIR=$(mktemp -d)
    openssl genpkey -algorithm ed25519 -out "$TMPDIR/signing.pem" 2>/dev/null
    openssl pkey -in "$TMPDIR/signing.pem" -pubout -out "$TMPDIR/public.pem" 2>/dev/null
    openssl rand -hex 16 > "$TMPDIR/kid"

    oc create secret generic sandbox-jwt \
        --from-file=signing.pem="$TMPDIR/signing.pem" \
        --from-file=public.pem="$TMPDIR/public.pem" \
        --from-file=kid="$TMPDIR/kid" \
        -n "$NAMESPACE"
    log "  sandbox-jwt secret created"
    rm -rf "$TMPDIR"
fi

# --- ConfigMap (from checked-in template — never truncated) ---

log "Creating openshell-config ConfigMap..."
RENDERED_CONFIG=$(envsubst < "$REPO_ROOT/deploy/openshell/gateway.toml.tmpl")
oc create configmap openshell-config \
    --from-literal="gateway.toml=$RENDERED_CONFIG" \
    -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -

# --- Service (headless for StatefulSet) ---

log "Creating openshell Service..."
oc apply -n "$NAMESPACE" -f - <<'EOF'
apiVersion: v1
kind: Service
metadata:
  name: openshell
  labels:
    app.kubernetes.io/name: openshell
spec:
  clusterIP: None
  selector:
    app.kubernetes.io/name: openshell
  ports:
  - name: grpc
    port: 8080
    targetPort: 8080
  - name: metrics
    port: 9090
    targetPort: 9090
EOF

# --- StatefulSet ---

log "Creating openshell StatefulSet..."
oc apply -n "$NAMESPACE" -f - <<'EOF'
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: openshell
  labels:
    app.kubernetes.io/name: openshell
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: openshell
  serviceName: openshell
  template:
    metadata:
      labels:
        app.kubernetes.io/name: openshell
    spec:
      serviceAccountName: openshell
      containers:
      - name: openshell-gateway
        image: ghcr.io/nvidia/openshell/gateway:0.0.86
        args: ["--config", "/etc/openshell/gateway.toml", "--db-url", "sqlite:/var/openshell/openshell.db"]
        ports:
        - name: grpc
          containerPort: 8080
        - name: health
          containerPort: 8081
        - name: metrics
          containerPort: 9090
        startupProbe:
          httpGet:
            path: /healthz
            port: health
          failureThreshold: 30
          periodSeconds: 2
        readinessProbe:
          httpGet:
            path: /readyz
            port: health
          initialDelaySeconds: 1
          periodSeconds: 2
        livenessProbe:
          httpGet:
            path: /healthz
            port: health
          initialDelaySeconds: 2
          periodSeconds: 5
        securityContext:
          allowPrivilegeEscalation: false
          runAsNonRoot: true
          capabilities:
            drop: ["ALL"]
        volumeMounts:
        - name: openshell-data
          mountPath: /var/openshell
        - name: gateway-config
          mountPath: /etc/openshell
        - name: sandbox-jwt
          mountPath: /etc/openshell-jwt
      volumes:
      - name: gateway-config
        configMap:
          name: openshell-config
      - name: sandbox-jwt
        secret:
          secretName: sandbox-jwt
  volumeClaimTemplates:
  - metadata:
      name: openshell-data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: gp3-csi
      resources:
        requests:
          storage: 1Gi
EOF

# --- Wait for OpenShell gateway ---

log "Waiting for openshell-0..."
wait_for_pod_ready "openshell-0" 60

# --- SonataFlow Platform ---

log "Creating SonataFlowPlatform CR..."
oc apply -n "$NAMESPACE" -f - <<'EOF'
apiVersion: sonataflow.org/v1alpha08
kind: SonataFlowPlatform
metadata:
  name: sonataflow-platform
spec:
  services:
    dataIndex:
      enabled: false
    jobService:
      enabled: false
EOF

log_step "OpenShell + SonataFlow provisioning complete"
log "Gateway: openshell-0"
log "To verify: oc get pod openshell-0 -n $NAMESPACE"
