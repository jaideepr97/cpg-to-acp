#!/usr/bin/env bash
# One-time setup for deploying the mock-EHR to OpenShift.
#
# This script creates the resources that are NOT managed by Helm:
#   1. ImageStreams for custom-built images
#   2. BuildConfigs for building those images from Git
#   3. ImageStreams + image imports for public Docker Hub images
#      (pushed from local to avoid Docker Hub rate limits)
#
# Run this ONCE before the first `helm install` of the mock-EHR chart.
# After this, `deploy/install.sh` handles Helm deployments.
#
# Prerequisites:
#   - Logged into OpenShift (`oc login`)
#   - podman installed (for pulling/pushing public images)
#   - The public images available locally or pullable from Docker Hub
#
# Usage:
#   bash mock-EHR/deploy/setup-openshift.sh [--namespace NAMESPACE] [--branch BRANCH] [--tag TAG]

set -euo pipefail

NAMESPACE="${NAMESPACE:-sschifma-cpg-to-acp}"
GIT_REPO="https://github.com/samschifman/cpg-to-acp.git"
GIT_BRANCH="${GIT_BRANCH:-main}"
IMAGE_TAG="${IMAGE_TAG:-phase4}"
MEDPLUM_VERSION="5.1.27"

log() { echo "[setup-openshift] $*"; }

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NAMESPACE="$2"; shift 2;;
    --branch) GIT_BRANCH="$2"; shift 2;;
    --tag) IMAGE_TAG="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

log "Namespace:  $NAMESPACE"
log "Git branch: $GIT_BRANCH"
log "Image tag:  $IMAGE_TAG"
log ""

oc project "$NAMESPACE" 2>/dev/null || oc new-project "$NAMESPACE"

REGISTRY=$(oc get route image-registry -n openshift-image-registry -o jsonpath='{.spec.host}' 2>/dev/null)
if [ -z "$REGISTRY" ]; then
  log "ERROR: No external registry route found. Expose the registry first:"
  log "  oc patch configs.imageregistry.operator.openshift.io/cluster --type merge -p '{\"spec\":{\"defaultRoute\":true}}'"
  exit 1
fi
log "Registry: $REGISTRY"

# --- Step 1: Create ImageStreams ---

log ""
log "=== Creating ImageStreams ==="
for is in mock-ehr-app medplum-loader postgres-16 redis-7 medplum-server-upstream medplum-app-upstream; do
  oc create imagestream "$is" -n "$NAMESPACE" 2>/dev/null && log "  Created $is" || log "  $is already exists"
done

# --- Step 2: Create BuildConfigs ---

log ""
log "=== Creating BuildConfigs ==="

create_bc() {
  local name="$1" context="$2" containerfile="$3"
  oc apply -f - <<EOF
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: $name
  namespace: $NAMESPACE
spec:
  source:
    type: Git
    git:
      uri: $GIT_REPO
      ref: $GIT_BRANCH
    contextDir: $context
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: $containerfile
  output:
    to:
      kind: ImageStreamTag
      name: $name:$IMAGE_TAG
  resources:
    limits:
      cpu: "1"
      memory: 2Gi
  failedBuildsHistoryLimit: 3
  successfulBuildsHistoryLimit: 3
EOF
  log "  $name: contextDir=$context containerfile=$containerfile -> $name:$IMAGE_TAG"
}

create_bc "mock-ehr-app"    "mock-EHR/ui"          "Containerfile"
create_bc "medplum-loader"  "mock-EHR"             "deploy/Containerfile.loader"

# --- Step 3: Push public images to internal registry ---
# Docker Hub rate-limits pulls from the cluster. We pull amd64 images
# locally and push them to the internal registry.

log ""
log "=== Pushing public images to internal registry ==="
log "  (Pulling amd64 images locally and pushing to $REGISTRY)"

TOKEN=$(oc whoami -t)
podman login "$REGISTRY" -u unused -p "$TOKEN" --tls-verify=false 2>/dev/null || {
  log "ERROR: Failed to login to registry. Check your oc session."
  exit 1
}

push_image() {
  local src="$1" dest_is="$2" dest_tag="$3"
  local dest="$REGISTRY/$NAMESPACE/$dest_is:$dest_tag"
  local start_time=$SECONDS
  log "  Pulling $src ..."
  podman pull --platform linux/amd64 "$src" 2>/dev/null
  local pull_time=$(( SECONDS - start_time ))
  log "  Pulled in ${pull_time}s. Pushing -> $dest_is:$dest_tag ..."
  podman tag "$src" "$dest"
  podman push "$dest" --tls-verify=false 2>/dev/null
  local total_time=$(( SECONDS - start_time ))
  log "  ✓ $dest_is:$dest_tag done (${total_time}s)"
}

push_image "docker.io/library/postgres:16"                    "postgres-16"              "16"
push_image "docker.io/library/redis:7"                        "redis-7"                  "7"
push_image "docker.io/medplum/medplum-server:$MEDPLUM_VERSION" "medplum-server-upstream"  "$MEDPLUM_VERSION"
push_image "docker.io/medplum/medplum-app:$MEDPLUM_VERSION"    "medplum-app-upstream"     "$MEDPLUM_VERSION"

# --- Step 4: Build custom images ---

log ""
log "=== Building custom images ==="

for bc in mock-ehr-app medplum-loader; do
  log "  Starting build: $bc"
  oc start-build "$bc" -n "$NAMESPACE" 2>&1 | head -1
done

log "Waiting for builds (polling every 30s)..."
for bc in mock-ehr-app medplum-loader; do
  local_start=$SECONDS
  for i in $(seq 1 60); do
    phase=$(oc get builds -n "$NAMESPACE" -l "openshift.io/build-config.name=$bc" -o jsonpath='{.items[-1].status.phase}' 2>/dev/null)
    elapsed=$(( SECONDS - local_start ))
    if [ "$phase" = "Complete" ]; then log "  ✓ $bc: Complete (${elapsed}s)"; break; fi
    if [ "$phase" = "Failed" ]; then log "  ✗ $bc: FAILED (${elapsed}s)"; break; fi
    if [ $((i % 3)) -eq 0 ]; then log "  $bc: $phase (${elapsed}s)"; fi
    sleep 10
  done
done

# --- Done ---

log ""
log "=== Setup complete ==="
log ""
log "Next steps:"
log "  1. Deploy the Helm chart:"
log "     helm upgrade --install cpg-mock-ehr ./mock-EHR/deploy/chart --namespace $NAMESPACE"
log ""
log "  2. After Medplum server is healthy, run the data loader manually:"
log "     oc run medplum-loader-init \\"
log "       --image=$REGISTRY/$NAMESPACE/medplum-loader:$IMAGE_TAG \\"
log "       --restart=Never \\"
log "       --env='MEDPLUM_BASE_URL=http://cpg-mock-ehr-medplum-server:8103' \\"
log "       --env='DATA_DIR=/data' \\"
log "       -n $NAMESPACE"
log ""
log "  3. SMART credentials are handled automatically: the loader job registers"
log "     the SMART app in Medplum and writes the credentials to the"
log "     'smart-client-credentials' K8s Secret, which the acp-writer UI mounts."
log "     If the loader ran before the acp-writer UI was up, restart it:"
log "     oc rollout restart deployment/acp-ui -n $NAMESPACE"
