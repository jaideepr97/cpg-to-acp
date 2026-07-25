#!/usr/bin/env bash
# End-to-end verification: full CPG-to-ACP pipeline on OpenShift
#
# Tests the pod-per-security-profile deployment with MCP Gateway governance
# and OpenShell sandbox enforcement.
#
# Prerequisites:
#   - Logged into OpenShift: oc whoami
#   - Namespace: sschifma-cpg-to-acp (or set NAMESPACE)
#
# Usage:
#   ./scripts/run-e2e-openshift.sh

set -euo pipefail

NAMESPACE="${NAMESPACE:-sschifma-cpg-to-acp}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

GATEWAY_URL="$(oc get route cpg-gateway -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")"
ACP_UI_URL="$(oc get route acp-ui -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")"

FIXTURES="$ROOT_DIR/shared/tests/fixtures/sample-recommendations.json"
DMN_FILE="$ROOT_DIR/cpg-ingester/data/golden/treatment-recommendation.dmn"
DIABETES_FIXTURES="$ROOT_DIR/tests/integration/fixtures/diabetes-cpg.json"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

passed=0
failed=0
total=0
SESSION_ID=""

check() {
    total=$((total + 1))
    local desc="$1"
    shift
    if "$@" > /dev/null 2>&1; then
        echo "  ✓ $desc"
        passed=$((passed + 1))
    else
        echo "  ✗ $desc"
        failed=$((failed + 1))
    fi
}

mcp_call() {
    local method="$1"
    local params="$2"
    local id="${3:-$((RANDOM % 10000))}"
    curl -sf -X POST "https://${GATEWAY_URL}/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -H "Mcp-Session-Id: ${SESSION_ID}" \
        -d "{\"jsonrpc\":\"2.0\",\"id\":${id},\"method\":\"${method}\",\"params\":${params}}"
}

mcp_tool_call() {
    local tool_name="$1"
    local arguments="$2"
    mcp_call "tools/call" "{\"name\":\"${tool_name}\",\"arguments\":${arguments}}"
}

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  CPG-to-ACP End-to-End Verification — OpenShift            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Namespace:   $NAMESPACE"
echo "MCP Gateway: https://${GATEWAY_URL:-NOT FOUND}"
echo "ACP UI:      https://${ACP_UI_URL:-NOT FOUND}"
echo ""

# ═══════════════════════════════════════════════════════════════════
# 1. Prerequisites — pod health
# ═══════════════════════════════════════════════════════════════════
echo "1. Pod health checks"

PODS=(
    "cpg-ing-ingestion:8080"
    "cpg-ing-llm-analysis:8080"
    "cpg-ing-assembly:8080"
    "cpg-ing-delivery:8080"
    "cpg-ing-ui:8090"
    "acp-patient-data:8080"
    "acp-llm-reasoning:8080"
    "acp-decision-engine:8080"
    "acp-fhir-generation:8080"
    "acp-fhir-server:8080"
    "acp-ui:8082"
)

for pod_port in "${PODS[@]}"; do
    pod="${pod_port%%:*}"
    port="${pod_port##*:}"
    check "$pod healthy" \
        oc exec "deploy/$pod" -n "$NAMESPACE" -- \
        curl -sf "http://localhost:${port}/health"
done

echo ""
echo "2. Infrastructure services"
check "HAPI FHIR reachable" \
    oc exec deploy/acp-writer-mcp -n "$NAMESPACE" -- \
    python3 -c "import urllib.request; urllib.request.urlopen('http://cpg-mock-ehr-hapi-fhir:8080/fhir/metadata', timeout=10)"

check "Kogito decision engine reachable" \
    oc exec deploy/acp-writer-mcp -n "$NAMESPACE" -- \
    python3 -c "import urllib.request; urllib.request.urlopen('http://cpg-decision-svc-decision-service:8081/q/health/ready', timeout=10)"

check "MCP Gateway reachable" \
    curl -sf "https://${GATEWAY_URL}/mcp" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"e2e-test","version":"1.0"}}}'

check "OpenShell gateway running" \
    bash -c "oc get pod openshell-0 -n $NAMESPACE -o jsonpath='{.status.phase}' | grep -q Running"

SANDBOX_COUNT=$(oc get sandboxes.agents.x-k8s.io -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
check "OpenShell sandboxes: 11 active" test "$SANDBOX_COUNT" -eq 11

check "MCP acp-writer-mcp-server Ready" \
    bash -c "oc get mcpserverregistrations acp-writer-mcp-server -n $NAMESPACE -o jsonpath='{.status.conditions[0].status}' | grep -q True"

check "MCP mock-ehr-mcp-server Ready" \
    bash -c "oc get mcpserverregistrations mock-ehr-mcp-server -n $NAMESPACE -o jsonpath='{.status.conditions[0].status}' | grep -q True"

# ═══════════════════════════════════════════════════════════════════
# 3. MCP Gateway — tool discovery
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "3. MCP Gateway tool discovery"

SESSION_ID=$(curl -sD - -X POST "https://${GATEWAY_URL}/mcp" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"e2e-test","version":"1.0"}}}' \
    2>/dev/null | grep -i 'mcp-session-id' | head -1 | sed 's/.*: //' | tr -d '\r')

check "MCP session initialized" test -n "$SESSION_ID"

mcp_call "tools/list" "{}" 2 > "$TMPDIR/tools_list.json"
check "tools/list returns 12 tools" python3 -c "
import json
data = json.load(open('$TMPDIR/tools_list.json'))
tools = data.get('result', {}).get('tools', [])
assert len(tools) == 12, f'expected 12, got {len(tools)}'
"

check "All acp_ tools present (8)" python3 -c "
import json
data = json.load(open('$TMPDIR/tools_list.json'))
names = [t['name'] for t in data['result']['tools']]
acp = [n for n in names if n.startswith('acp_')]
assert len(acp) == 8, f'expected 8 acp_ tools, got {len(acp)}: {acp}'
"

check "All ehr_ tools present (4)" python3 -c "
import json
data = json.load(open('$TMPDIR/tools_list.json'))
names = [t['name'] for t in data['result']['tools']]
ehr = [n for n in names if n.startswith('ehr_')]
assert len(ehr) == 4, f'expected 4 ehr_ tools, got {len(ehr)}: {ehr}'
"

VS_COUNT=$(oc get mcpvirtualservers -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
check "3 virtual servers defined" test "$VS_COUNT" -eq 3

# ═══════════════════════════════════════════════════════════════════
# 4. CPG delivery through MCP Gateway
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "4. CPG delivery through MCP Gateway"

python3 -c "
import json
data = json.load(open('$FIXTURES'))
json.dump(data['metadata'], open('$TMPDIR/metadata.json', 'w'))
json.dump(data['recommendation_bundle'], open('$TMPDIR/rec_bundle.json', 'w'))
"

METADATA=$(cat "$TMPDIR/metadata.json")
mcp_tool_call "acp_register_guideline" "{\"metadata\": $METADATA}" > "$TMPDIR/gw_register.json"
check "register_guideline via gateway" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_register.json'))
assert not data['result'].get('isError', False), f'error: {data}'
"

DMN_XML=$(cat "$DMN_FILE" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")
mcp_tool_call "acp_deploy_decision_model" "{\"dmn_xml\": $DMN_XML}" > "$TMPDIR/gw_deploy.json"
check "deploy_decision_model via gateway" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_deploy.json'))
assert not data['result'].get('isError', False), f'error: {data}'
"

REC_BUNDLE=$(cat "$TMPDIR/rec_bundle.json")
mcp_tool_call "acp_ingest_recommendation_batch" "{\"bundle\": $REC_BUNDLE}" > "$TMPDIR/gw_ingest.json"
check "ingest_recommendation_batch via gateway" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_ingest.json'))
content = json.loads(data['result']['content'][0]['text'])
assert content.get('status') == 'ingested', f'got: {content}'
"

mcp_tool_call "acp_list_decision_models" "{}" > "$TMPDIR/gw_models.json"
check "list_decision_models returns deployed model" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_models.json'))
models = json.loads(data['result']['content'][0]['text'])
assert len(models) > 0, 'no models deployed'
"

mcp_tool_call "acp_search_recommendations" "{\"query\": \"hypertension blood pressure treatment\", \"top_k\": 5}" > "$TMPDIR/gw_search.json"
check "search_recommendations returns results" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_search.json'))
results = json.loads(data['result']['content'][0]['text'])
assert len(results.get('results', [])) > 0, 'no search results'
"

# ═══════════════════════════════════════════════════════════════════
# 5. Multi-CPG delivery
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "5. Multi-CPG delivery (diabetes — overlapping scope)"

if [ -f "$DIABETES_FIXTURES" ]; then
    python3 -c "
import json
data = json.load(open('$DIABETES_FIXTURES'))
json.dump(data['metadata'], open('$TMPDIR/dm2_metadata.json', 'w'))
json.dump(data['recommendation_bundle'], open('$TMPDIR/dm2_rec_bundle.json', 'w'))
"

    DM2_METADATA=$(cat "$TMPDIR/dm2_metadata.json")
    mcp_tool_call "acp_register_guideline" "{\"metadata\": $DM2_METADATA}" > "$TMPDIR/gw_dm2_register.json"
    check "Register diabetes CPG via gateway" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_dm2_register.json'))
assert not data['result'].get('isError', False)
"

    DM2_REC_BUNDLE=$(cat "$TMPDIR/dm2_rec_bundle.json")
    mcp_tool_call "acp_ingest_recommendation_batch" "{\"bundle\": $DM2_REC_BUNDLE}" > "$TMPDIR/gw_dm2_ingest.json"
    check "Ingest diabetes recommendations via gateway" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_dm2_ingest.json'))
content = json.loads(data['result']['content'][0]['text'])
assert content.get('status') == 'ingested'
"

    mcp_tool_call "acp_search_recommendations" "{\"query\": \"ACE inhibitor blood pressure diabetes\", \"top_k\": 10}" > "$TMPDIR/gw_multi_search.json"
    check "Multi-CPG search returns results from both CPGs" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_multi_search.json'))
results = json.loads(data['result']['content'][0]['text'])
cpgs = set(r['recommendation']['source_cpg'] for r in results.get('results', []))
assert 'SYN-HTN-2026-001' in cpgs, f'missing HTN CPG, got: {cpgs}'
assert 'SYN-DM2-2026-001' in cpgs, f'missing DM2 CPG, got: {cpgs}'
"

    mcp_tool_call "acp_search_recommendations" "{\"query\": \"medication\", \"source_cpg\": \"SYN-DM2-2026-001\", \"top_k\": 5}" > "$TMPDIR/gw_dm2_only.json"
    check "CPG filter isolates diabetes-only results" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_dm2_only.json'))
results = json.loads(data['result']['content'][0]['text'])
for r in results.get('results', []):
    assert r['recommendation']['source_cpg'] == 'SYN-DM2-2026-001', f'wrong cpg: {r[\"recommendation\"][\"source_cpg\"]}'
"
else
    echo "  (skipped — diabetes fixtures not found)"
fi

# ═══════════════════════════════════════════════════════════════════
# 6. Patient data through MCP Gateway
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "6. Patient data through MCP Gateway"

mcp_tool_call "ehr_list_patients" "{}" > "$TMPDIR/gw_patients.json"
check "ehr_list_patients returns patients" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_patients.json'))
patients = json.loads(data['result']['content'][0]['text'])
assert len(patients) > 0, 'no patients returned'
"

check "James Reynolds in patient list" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_patients.json'))
patients = json.loads(data['result']['content'][0]['text'])
names = [p.get('name', '') for p in patients]
assert any('Reynolds' in n for n in names), f'Reynolds not found in: {names}'
"

PATIENT_ID=$(python3 -c "
import json
data = json.load(open('$TMPDIR/gw_patients.json'))
patients = json.loads(data['result']['content'][0]['text'])
for p in patients:
    if 'Reynolds' in p.get('name', ''):
        print(p['id'])
        break
" 2>/dev/null)

if [ -n "$PATIENT_ID" ]; then
    mcp_tool_call "ehr_get_patient_summary" "{\"patient_id\": \"$PATIENT_ID\"}" > "$TMPDIR/gw_patient_summary.json"
    check "ehr_get_patient_summary returns clinical data" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_patient_summary.json'))
summary = json.loads(data['result']['content'][0]['text'])
assert summary.get('patient_id') == '$PATIENT_ID'
assert len(summary.get('conditions', [])) > 0, 'no conditions'
"

    mcp_tool_call "ehr_get_patient_conditions" "{\"patient_id\": \"$PATIENT_ID\"}" > "$TMPDIR/gw_conditions.json"
    check "ehr_get_patient_conditions returns conditions" python3 -c "
import json
data = json.load(open('$TMPDIR/gw_conditions.json'))
conditions = json.loads(data['result']['content'][0]['text'])
assert len(conditions) > 0, 'no conditions'
"
fi

# ═══════════════════════════════════════════════════════════════════
# 7. OpenShell governance
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "7. OpenShell governance"

check "OpenShell OCSF audit events present" \
    bash -c "oc logs openshell-0 -n $NAMESPACE --tail=100 2>/dev/null | grep -q 'GetSandbox\|GetSandboxConfig\|GetInferenceBundle'"

check "All 11 sandboxes Ready" python3 -c "
import subprocess, json
result = subprocess.run(
    ['oc', 'get', 'sandboxes.agents.x-k8s.io', '-n', '$NAMESPACE', '-o', 'json'],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
names = sorted([item['metadata']['name'] for item in data.get('items', [])])
expected = sorted([
    'acp-writer-decision', 'acp-writer-fhir-gen', 'acp-writer-fhir-srv',
    'acp-writer-llm', 'acp-writer-patient-data', 'acp-writer-ui',
    'cpg-ingester-assembly', 'cpg-ingester-delivery', 'cpg-ingester-ingestion',
    'cpg-ingester-llm', 'cpg-ingester-ui'
])
assert names == expected, f'expected {expected}, got {names}'
"

# ═══════════════════════════════════════════════════════════════════
# 8. Pipeline execution — real LLM, FHIR generation, server lifecycle
# ═══════════════════════════════════════════════════════════════════
if [ "${RUN_PIPELINE:-}" = "1" ]; then
    echo ""
    echo "8. Pipeline execution (LLM via MaaS — may take 2-3 minutes)"

    PATIENT_BUNDLE="$ROOT_DIR/mock-EHR/data/patient-bundle-medication.json"
    PATIENT_JSON=$(cat "$PATIENT_BUNDLE")

    # Helper: call a pod-split service from inside the cluster.
    # Payload must be a valid JSON string (passed directly, not as a Python literal).
    pod_call() {
        local service_url="$1"
        local payload="$2"
        local timeout="${3:-120}"
        local method="${4:-POST}"
        local payload_b64
        payload_b64=$(echo -n "$payload" | base64)
        oc exec deploy/acp-writer-mcp -n "$NAMESPACE" --request-timeout="${timeout}s" -- python3 -c "
import urllib.request, json, sys, base64
payload = base64.b64decode('${payload_b64}')
req = urllib.request.Request(
    '${service_url}',
    data=payload,
    headers={'Content-Type': 'application/json'},
    method='${method}'
)
try:
    resp = urllib.request.urlopen(req, timeout=${timeout})
    sys.stdout.write(resp.read().decode())
except urllib.error.HTTPError as e:
    sys.stderr.write(f'HTTP {e.code}: {e.read().decode()[:500]}')
    sys.exit(1)
except Exception as e:
    sys.stderr.write(str(e))
    sys.exit(1)
" 2>/dev/null
    }

    # --- Step 1: Scan patient ---
    echo "  8a. Scan patient (patient-data pod)"
    pod_call "http://acp-patient-data:8080/api/v1/scan" \
        "{\"ips_bundle\": ${PATIENT_JSON}}" > "$TMPDIR/pipe_scan.json"
    check "scan: returns patient_reference" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_scan.json'))
assert d.get('patient_reference'), f'no patient_reference: {list(d.keys())}'
"
    check "scan: condition_codes include hypertension" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_scan.json'))
codes = [c.get('code','') for c in d.get('condition_codes', [])]
assert '59621000' in codes, f'hypertension SNOMED 59621000 not found in: {codes}'
"

    # Extract scan fields for downstream steps
    SCAN_RESULT=$(cat "$TMPDIR/pipe_scan.json")

    # --- Pre-load CPG artifacts into pod-split services ---
    # Load guidelines + recommendations into LLM Reasoning pod and
    # DMN model into Decision Engine pod via their management endpoints.
    echo "  8b. Load CPG artifacts into pod-split services"

    python3 -c "
import json
data = json.load(open('$FIXTURES'))
json.dump(data['metadata'], open('$TMPDIR/pipe_metadata.json', 'w'))
json.dump(data['recommendation_bundle'], open('$TMPDIR/pipe_rec_bundle.json', 'w'))
"

    PIPE_METADATA=$(cat "$TMPDIR/pipe_metadata.json")
    pod_call "http://acp-llm-reasoning:8080/api/v1/guidelines" \
        "$PIPE_METADATA" > "$TMPDIR/pipe_reg.json"
    check "Load guideline into llm-reasoning pod" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_reg.json'))
assert d.get('cpg_id'), f'no cpg_id: {d}'
"

    PIPE_REC_BUNDLE=$(cat "$TMPDIR/pipe_rec_bundle.json")
    pod_call "http://acp-llm-reasoning:8080/api/v1/knowledge/recommendations/batch" \
        "$PIPE_REC_BUNDLE" > "$TMPDIR/pipe_ingest.json"
    check "Load recommendations into llm-reasoning pod" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_ingest.json'))
assert d.get('status') == 'ingested', f'got: {d}'
"

    DMN_XML_ESCAPED=$(cat "$DMN_FILE" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")
    oc exec deploy/acp-writer-mcp -n "$NAMESPACE" -- python3 -c "
import urllib.request, sys
dmn_xml = ${DMN_XML_ESCAPED}
req = urllib.request.Request(
    'http://acp-decision-engine:8080/api/v1/decisions/models',
    data=dmn_xml.encode(),
    headers={'Content-Type': 'application/xml'},
    method='POST'
)
resp = urllib.request.urlopen(req, timeout=30)
sys.stdout.write(resp.read().decode())
" 2>/dev/null > "$TMPDIR/pipe_dmn.json"
    check "Deploy DMN model into decision-engine pod" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_dmn.json'))
assert d.get('id'), f'no model id: {d}'
"

    # --- Step 2: Resolve guidelines ---
    echo "  8c. Resolve guidelines (llm-reasoning pod — calls LLM)"
    RESOLVE_INPUT=$(python3 -c "
import json
scan = json.load(open('$TMPDIR/pipe_scan.json'))
print(json.dumps({'condition_codes': scan.get('condition_codes', [])}))
")
    pod_call "http://acp-llm-reasoning:8080/api/v1/resolve" \
        "$RESOLVE_INPUT" 120 > "$TMPDIR/pipe_resolve.json"
    check "resolve: returns applicable_cpgs" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_resolve.json'))
cpgs = d.get('applicable_cpgs', [])
assert len(cpgs) > 0, f'no applicable CPGs found (is guideline loaded?): {list(d.keys())}'
"

    # --- Step 3: Retrieve recommendations ---
    echo "  8d. Retrieve recommendations (llm-reasoning pod)"
    RETRIEVE_INPUT=$(python3 -c "
import json
scan = json.load(open('$TMPDIR/pipe_scan.json'))
resolve = json.load(open('$TMPDIR/pipe_resolve.json'))
print(json.dumps({
    'condition_codes': scan.get('condition_codes', []),
    'dmn_results': [],
    'applicable_cpgs': resolve.get('applicable_cpgs', [])
}))
")
    pod_call "http://acp-llm-reasoning:8080/api/v1/retrieve" \
        "$RETRIEVE_INPUT" 60 > "$TMPDIR/pipe_retrieve.json"
    check "retrieve: returns recommendations" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_retrieve.json'))
recs = d.get('recommendations', [])
assert len(recs) > 0, f'no recommendations retrieved'
"

    # --- Step 4: Compose plan (LLM call via MaaS) ---
    echo "  8e. Compose plan (llm-reasoning pod — calls LLM)"
    COMPOSE_INPUT=$(python3 -c "
import json
scan = json.load(open('$TMPDIR/pipe_scan.json'))
resolve = json.load(open('$TMPDIR/pipe_resolve.json'))
retrieve = json.load(open('$TMPDIR/pipe_retrieve.json'))
payload = {
    'patient_reference': scan.get('patient_reference', ''),
    'patient_demographics': scan.get('patient_demographics', {}),
    'condition_codes': scan.get('condition_codes', []),
    'medication_codes': scan.get('medication_codes', []),
    'allergy_codes': scan.get('allergy_codes', []),
    'dmn_results': [],
    'recommendations': retrieve.get('recommendations', []),
    'applicable_cpgs': resolve.get('applicable_cpgs', [])
}
print(json.dumps(payload))
")
    pod_call "http://acp-llm-reasoning:8080/api/v1/compose" \
        "$COMPOSE_INPUT" 600 > "$TMPDIR/pipe_compose.json" || true
    check "compose: returns planning_brief (LLM was called)" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_compose.json'))
brief = d.get('planning_brief', {})
assert brief, f'empty planning_brief — LLM may not have responded'
"

    # --- Step 5: Generate FHIR bundle ---
    echo "  8f. Generate FHIR bundle (fhir-generation pod)"
    GENERATE_INPUT=$(python3 -c "
import json
scan = json.load(open('$TMPDIR/pipe_scan.json'))
compose = json.load(open('$TMPDIR/pipe_compose.json'))
payload = {
    'planning_brief': compose.get('planning_brief', {}),
    'patient_demographics': scan.get('patient_demographics', {}),
    'fhir_review_feedback': ''
}
print(json.dumps(payload))
")
    pod_call "http://acp-fhir-generation:8080/api/v1/generate-bundle" \
        "$GENERATE_INPUT" 600 > "$TMPDIR/pipe_generate.json" || true
    check "generate-bundle: returns FHIR Bundle" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_generate.json'))
bundle = d.get('fhir_bundle', {})
assert bundle.get('resourceType') == 'Bundle', f'not a Bundle: {bundle.get(\"resourceType\")}'
"
    check "generate-bundle: Bundle has entries" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_generate.json'))
entries = d.get('fhir_bundle', {}).get('entry', [])
assert len(entries) > 0, 'Bundle has no entries'
"

    # --- Step 6: Write to FHIR server ---
    echo "  8g. Write to FHIR server (fhir-server pod → HAPI FHIR)"
    WRITE_INPUT=$(python3 -c "
import json
scan = json.load(open('$TMPDIR/pipe_scan.json'))
gen = json.load(open('$TMPDIR/pipe_generate.json'))
payload = {
    'fhir_bundle': gen.get('fhir_bundle', {}),
    'patient_reference': scan.get('patient_reference', '')
}
print(json.dumps(payload))
")
    pod_call "http://acp-fhir-server:8080/api/v1/write" \
        "$WRITE_INPUT" > "$TMPDIR/pipe_write.json"
    check "write: returns careplan_id" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_write.json'))
assert d.get('careplan_id'), f'no careplan_id: {list(d.keys())}'
"
    check "write: delivery_status is delivered or stored_locally" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_write.json'))
status = d.get('delivery_status', '')
assert status in ('delivered', 'stored_locally'), f'unexpected status: {status}'
"

    CAREPLAN_ID=$(python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_write.json'))
print(d.get('careplan_id', ''))
")

    # --- Step 7: Approve care plan ---
    echo "  8h. Care plan lifecycle (fhir-server pod)"
    if [ -n "$CAREPLAN_ID" ]; then
        pod_call "http://acp-fhir-server:8080/api/v1/careplans/${CAREPLAN_ID}/status" \
            "{\"status\": \"active\", \"clinician\": \"Dr. E2E Test\"}" 120 PUT > "$TMPDIR/pipe_approve.json" \
            || true
        check "approve: status changed to active" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_approve.json'))
assert d.get('status') == 'active', f'expected active, got: {d.get(\"status\")}'
"
    fi

    # --- Step 8: Generate + reject a second care plan ---
    echo "  8i. Second care plan — reject lifecycle"
    pod_call "http://acp-fhir-server:8080/api/v1/write" \
        "$WRITE_INPUT" > "$TMPDIR/pipe_write2.json"
    CAREPLAN2_ID=$(python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_write2.json'))
print(d.get('careplan_id', ''))
")
    if [ -n "$CAREPLAN2_ID" ]; then
        pod_call "http://acp-fhir-server:8080/api/v1/careplans/${CAREPLAN2_ID}/status" \
            "{\"status\": \"entered-in-error\", \"reason\": \"E2E test rejection\"}" 120 PUT > "$TMPDIR/pipe_reject.json" \
            || true
        check "reject: status changed to entered-in-error" python3 -c "
import json
d = json.load(open('$TMPDIR/pipe_reject.json'))
assert d.get('status') == 'entered-in-error', f'expected entered-in-error, got: {d.get(\"status\")}'
"
    fi

    echo ""
    echo "  Pipeline summary:"
    echo "    Patient: $(python3 -c "import json; d=json.load(open('$TMPDIR/pipe_scan.json')); print(d.get('patient_demographics',{}).get('name','?'))")"
    echo "    Conditions: $(python3 -c "import json; d=json.load(open('$TMPDIR/pipe_scan.json')); print(len(d.get('condition_codes',[])))")"
    echo "    Bundle entries: $(python3 -c "import json; d=json.load(open('$TMPDIR/pipe_generate.json')); print(len(d.get('fhir_bundle',{}).get('entry',[])))")"
    echo "    Care plan 1: $CAREPLAN_ID → approved"
    echo "    Care plan 2: ${CAREPLAN2_ID:-?} → entered-in-error"

else
    echo ""
    echo "8. Pipeline execution (skipped — set RUN_PIPELINE=1 to enable)"
    echo "   Requires MaaS LLM inference. Takes 2-3 minutes."
fi

# ═══════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Results: $passed/$total passed, $failed failed"
echo "╚══════════════════════════════════════════════════════════════╝"

if [ $failed -gt 0 ]; then
    exit 1
fi
