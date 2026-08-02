#!/bin/bash
set -e

NAMESPACE="${NAMESPACE:-sschifma-cpg-to-acp}"
RELEASE_PREFIX="${RELEASE_PREFIX:-cpg}"

# Prerequisites:
#   - Run mock-EHR/deploy/setup-openshift.sh first (creates ImageStreams, BuildConfigs, pushes images)
#   - All images must be built and available in the internal registry

echo "=== CPG-to-ACP OpenShift Deployment ==="
echo "Namespace:      $NAMESPACE"
echo "Release prefix: $RELEASE_PREFIX"
echo ""

oc project "$NAMESPACE" 2>/dev/null || oc new-project "$NAMESPACE"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Installing decision-service ==="
helm upgrade --install "${RELEASE_PREFIX}-decision-svc" \
  "$REPO_ROOT/acp-writer/decision-service/deploy/chart" \
  --namespace "$NAMESPACE" \
  "$@"

echo "=== Installing acp-writer ==="
helm upgrade --install "${RELEASE_PREFIX}-acp-writer" \
  "$REPO_ROOT/acp-writer/deploy/chart" \
  --namespace "$NAMESPACE" \
  --set decisionService.url="http://${RELEASE_PREFIX}-decision-svc-decision-service:8081" \
  "$@"

echo "=== Installing mock-EHR (Medplum) ==="
helm upgrade --install "${RELEASE_PREFIX}-mock-ehr" \
  "$REPO_ROOT/mock-EHR/deploy/chart" \
  --namespace "$NAMESPACE" \
  "$@"

echo "=== Installing LiteLLM ==="
helm upgrade --install "${RELEASE_PREFIX}-litellm" \
  "$REPO_ROOT/platform/litellm/deploy/chart" \
  --namespace "$NAMESPACE" \
  "$@"

echo ""
echo "=== Deployment complete ==="
echo ""
oc get pods -n "$NAMESPACE"
echo ""
oc get routes -n "$NAMESPACE"
