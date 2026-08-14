#!/usr/bin/env bash
# deploy/verify-all.sh — Full deployment verification + secret-leak scan
#
# Usage:
#   ./deploy/verify-all.sh [--config <path>]
#   ./deploy/verify-all.sh --e2e   # adds functional QA round trip + terminology probe
#
# Runs:
#   1. Per-component verify.sh (pods, images, supervision, routed health)
#   2. Shared checks (MinIO, MaaS, SonataFlow)
#   3. S7 secret-leak scan (mandatory — exits non-zero on any leak)
#   4. Orphan check
#   5. [--e2e] QA round trip + terminology egress probe

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck disable=SC1091
source "$REPO_ROOT/deploy/lib.sh"

CONFIG_PATH="$REPO_ROOT/deploy/config/cluster.env"
E2E=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; shift 2;;
        --e2e) E2E=true; shift;;
        -h|--help)
            echo "Usage: deploy/verify-all.sh [--config <path>] [--e2e]"
            echo ""
            echo "  (default)   Component checks + shared infra + secret-leak scan"
            echo "  --e2e       Also run QA round trip and terminology egress probe"
            exit 0;;
        *) shift;;
    esac
done

load_config "$CONFIG_PATH"
preflight

ERRORS=0

# --- 1. Per-component verification ---

for component in mock-EHR acp-writer cpg-ingester; do
    script="$REPO_ROOT/$component/deploy/verify.sh"
    if [ -f "$script" ]; then
        "$script" --config "$CONFIG_PATH" || {
            log "FAIL: $component verification failed"
            ERRORS=$((ERRORS + 1))
        }
    else
        log "SKIP: $script not found"
    fi
done

# --- 2. Shared infrastructure checks ---

log_step "Shared infrastructure checks"

# MinIO
minio_code=$(oc exec deployment/minio -n "$NAMESPACE" -- \
    curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    http://localhost:9000/minio/health/live 2>/dev/null || echo "000")
if [ "$minio_code" = "200" ]; then
    echo "  ✓ MinIO: HTTP 200"
else
    echo "  ✗ MinIO: HTTP $minio_code"
    ERRORS=$((ERRORS + 1))
fi

# MaaS (one test call through the gateway).
# SECURITY: the API key is piped over stdin — it must NEVER appear in the
# oc exec argument list (argv is visible in the pod's process list and is
# recorded in the K8s API server audit log of the exec request).
maas_code=$(read_secret llm-credentials LLM_API_KEY | \
    oc exec -i deployment/openshell-router -n "$NAMESPACE" -- sh -c '
        curl -s -o /dev/null -w "%{http_code}" --max-time 15 \
            -X POST "$1/v1/chat/completions" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $(cat)" \
            -d "{\"model\":\"$2\",\"messages\":[{\"role\":\"user\",\"content\":\"test\"}]}"
    ' _ "${MAAS_GATEWAY_URL}/${MAAS_ROUTE_SEGMENT}" "$LLM_MODEL_DEFAULT" \
    2>/dev/null || echo "000")
if [ "$maas_code" = "200" ]; then
    echo "  ✓ MaaS LLM call: HTTP 200"
else
    echo "  ✗ MaaS LLM call: HTTP $maas_code"
    ERRORS=$((ERRORS + 1))
fi

# SonataFlow pods
for sf_pod in sonataflow-platform-data-index-service sonataflow-platform-jobs-service; do
    ready=$(oc get deployment "$sf_pod" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [ "${ready:-0}" -ge 1 ]; then
        echo "  ✓ $sf_pod: ready"
    else
        echo "  ✗ $sf_pod: not ready"
        ERRORS=$((ERRORS + 1))
    fi
done

# --- 3. S7 Secret-leak scan (mandatory) ---

log_step "S7 Secret-leak scan"

{ set +x; } 2>/dev/null
LEAK_FOUND=false

# Read secret prefixes to scan for (never print the full values)
LLM_KEY_PREFIX=$(read_secret llm-credentials LLM_API_KEY | head -c 10)
MINIO_PASS=$(read_secret minio-credentials ARTIFACT_STORE_SECRET_KEY | head -c 10)

# Scan all pod specs for secret values in plain text
POD_SPECS=$(oc get pods -n "$NAMESPACE" -o yaml 2>/dev/null)

for prefix_label in "LLM_API_KEY:$LLM_KEY_PREFIX" "MINIO_SECRET:$MINIO_PASS"; do
    label="${prefix_label%%:*}"
    prefix="${prefix_label##*:}"
    if [ -z "$prefix" ]; then
        continue
    fi
    # Search for the prefix in pod specs (env values, not secretKeyRef names)
    hits=$(echo "$POD_SPECS" | grep -n "value:.*${prefix}" 2>/dev/null | grep -v "secretKeyRef" | head -5)
    if [ -n "$hits" ]; then
        echo "  ✗ LEAK: $label prefix found in pod specs:"
        echo "$hits" | sed 's/'"$prefix"'.*/[REDACTED]/g'
        LEAK_FOUND=true
    fi
done

if [ "$LEAK_FOUND" = true ]; then
    echo ""
    echo "  SECRET LEAK DETECTED in pod specs. Secrets should use secretKeyRef, not plain values."
    ERRORS=$((ERRORS + 1))
else
    echo "  ✓ No secret leaks found in pod specs"
fi

# --- 4. Orphan check ---

log_step "Orphan check"

EXPECTED_PREFIXES="sb-|cpg-mock-ehr|cpg-decision-svc|acp-ui|cpg-ing-ui|cpg-ing-bff|minio|openshell|sonataflow|mcp-gateway|cpg-gateway|acpwriter|cpgingester|mock-ehr-mcp"
orphans=$(oc get pods -n "$NAMESPACE" --no-headers 2>/dev/null | grep -v -E "$EXPECTED_PREFIXES" | grep -v "Completed\|Error" | head -10)
if [ -n "$orphans" ]; then
    echo "  ⚠ Unexpected pods found:"
    echo "$orphans"
else
    echo "  ✓ No orphaned pods"
fi

# --- 5. E2E functional verification (optional) ---

if [ "$E2E" = true ]; then
    log_step "E2E functional verification"

    # QA round trip: deploy test DMN + execute via routed path
    echo "  QA round trip:"
    DMN_FILE="$REPO_ROOT/cpg-ingester/data/golden/treatment-recommendation.dmn"
    PATIENT_FILE="$REPO_ROOT/mock-EHR/data/patient-bundle-medication.json"

    if [ -f "$DMN_FILE" ] && [ -f "$PATIENT_FILE" ]; then
        # Deploy DMN via routed path
        oc cp "$DMN_FILE" sb-llm-reasoning:/tmp/test-dmn.dmn -n "$NAMESPACE" 2>/dev/null
        deploy_code=$(oc exec sb-llm-reasoning -n "$NAMESPACE" -- \
            curl -s -o /dev/null -w "%{http_code}" --max-time 15 \
            -X POST "http://acp-decision-engine:8080/api/v1/decisions/models" \
            -H "Content-Type: application/xml" \
            -d @/tmp/test-dmn.dmn 2>/dev/null || echo "000")

        if [ "$deploy_code" = "201" ] || [ "$deploy_code" = "200" ]; then
            echo "    ✓ DMN model deployed: HTTP $deploy_code"
        else
            echo "    ✗ DMN model deploy failed: HTTP $deploy_code"
            ERRORS=$((ERRORS + 1))
        fi

        # Execute via execute-dmn
        oc cp "$PATIENT_FILE" sb-llm-reasoning:/tmp/test-patient.json -n "$NAMESPACE" 2>/dev/null
        oc exec sb-llm-reasoning -n "$NAMESPACE" -- python3 -c "
import json
with open('/tmp/test-patient.json') as f:
    bundle = json.load(f)
payload = {
    'ips_bundle': bundle,
    'applicable_dmn_models': [{'id':'treatment-recommendation','name':'Treatment Recommendation',
        'inputs':[{'name':'Systolic BP','type':'number'},{'name':'Has Diabetes','type':'boolean'},
                  {'name':'Has Kidney Disease','type':'boolean'}],
        'outputs':[{'name':'Action','type':'string'}]}],
    'dmn_dependency_graph': [['treatment-recommendation']],
}
with open('/tmp/test-execute-payload.json', 'w') as f:
    json.dump(payload, f)
" 2>/dev/null

        result=$(oc exec sb-llm-reasoning -n "$NAMESPACE" -- \
            curl -s --max-time 120 \
            -X POST "http://acp-llm-reasoning:8080/api/v1/execute-dmn" \
            -H "Content-Type: application/json" \
            -d @/tmp/test-execute-payload.json 2>/dev/null || echo "{}")

        if echo "$result" | python3 -c "
import sys, json
d = json.load(sys.stdin)
r = d.get('dmn_results', [{}])[0]
assert 'input_resolution' in r, 'no input_resolution'
assert r.get('error') is None or r.get('error') == '', 'has error: ' + str(r.get('error'))
has_match_basis = any(v.get('match_basis') for v in r.get('input_resolution', {}).values())
assert has_match_basis, 'no match_basis in audit'
print('PASS')
" 2>/dev/null; then
            echo "    ✓ QA round trip: decision result with match_basis audit"
        else
            echo "    ✗ QA round trip failed"
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo "    ⚠ Test fixtures not found — skipping QA round trip"
    fi

    # Terminology egress probe
    echo "  Terminology egress:"
    term_code=$(oc exec sb-llm-reasoning -n "$NAMESPACE" -- \
        curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        "https://tx.fhir.org/r4/ValueSet/\$expand?url=http://snomed.info/sct?fhir_vs&filter=test&count=1" \
        2>/dev/null || echo "000")
    if [ "$term_code" = "200" ]; then
        echo "    ✓ Terminology egress (tx.fhir.org): HTTP 200"
    else
        echo "    ⚠ Terminology egress blocked or unavailable: HTTP $term_code"
        echo "      Pipeline degrades gracefully but terminology resolution is limited."
    fi
fi

# --- Summary ---

echo ""
if [ $ERRORS -eq 0 ]; then
    log "ALL VERIFICATION CHECKS PASSED"
else
    log "$ERRORS CHECK(S) FAILED"
    exit 1
fi
