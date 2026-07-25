#!/usr/bin/env bash
# Integration test: cpg-ingester delivery → acp-writer care plan generation
#
# Simulates what the Delivery Agent does: POST metadata, DMN model, and
# recommendations to acp-writer, then generates a care plan from patient data.
#
# Prerequisites:
#   - acp-writer running at ACP_WRITER_URL (default: http://localhost:8082)
#   - LITELLM_URL set if care plan generation is desired (LLM required)
#
# Usage:
#   ./scripts/run-integration-test.sh                    # delivery only
#   LITELLM_URL=http://localhost:4000 ./scripts/run-integration-test.sh  # full E2E

set -euo pipefail

ACP_WRITER_URL="${ACP_WRITER_URL:-http://localhost:8082}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

FIXTURES="$ROOT_DIR/shared/tests/fixtures/sample-recommendations.json"
DMN_FILE="$ROOT_DIR/cpg-ingester/data/golden/treatment-recommendation.dmn"
PATIENT_BUNDLE="$ROOT_DIR/mock-EHR/data/patient-bundle-medication.json"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

passed=0
failed=0
total=0

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

echo "=== Integration Test: cpg-ingester → acp-writer ==="
echo "acp-writer: $ACP_WRITER_URL"
echo ""

# --- Health check ---
echo "1. Health check"
check "acp-writer is reachable" curl -sf "$ACP_WRITER_URL/health"
if [ $failed -gt 0 ]; then
    echo "FATAL: acp-writer not reachable at $ACP_WRITER_URL"
    exit 1
fi

# --- Extract fixtures ---
python3 -c "
import json
data = json.load(open('$FIXTURES'))
json.dump(data['metadata'], open('$TMPDIR/metadata.json', 'w'))
json.dump(data['recommendation_bundle'], open('$TMPDIR/rec_bundle.json', 'w'))
"

# --- Delivery: CPG Metadata ---
echo ""
echo "2. Deliver CPG Metadata"
curl -sf -X POST "$ACP_WRITER_URL/api/v1/guidelines" \
    -H "Content-Type: application/json" \
    -d @"$TMPDIR/metadata.json" \
    -o "$TMPDIR/metadata_response.json"
check "POST /api/v1/guidelines succeeded" test -s "$TMPDIR/metadata_response.json"
check "CPG ID in response" python3 -c "
import json
d = json.load(open('$TMPDIR/metadata_response.json'))
assert d.get('cpg_id') == 'SYN-HTN-2026-001', f'got: {d.get(\"cpg_id\")}'
"

# --- Delivery: DMN Model ---
echo ""
echo "3. Deliver DMN Model"
curl -sf -X POST "$ACP_WRITER_URL/api/v1/decisions/models" \
    -H "Content-Type: application/xml" \
    --data-binary "@$DMN_FILE" \
    -o "$TMPDIR/dmn_response.json"
check "POST /api/v1/decisions/models succeeded" test -s "$TMPDIR/dmn_response.json"
check "DMN model name in response" python3 -c "
import json
d = json.load(open('$TMPDIR/dmn_response.json'))
assert 'Treatment' in d.get('name', ''), f'got: {d.get(\"name\")}'
"

# --- Delivery: Recommendations ---
echo ""
echo "4. Deliver Recommendations"
curl -sf -X POST "$ACP_WRITER_URL/api/v1/knowledge/recommendations/batch" \
    -H "Content-Type: application/json" \
    -d @"$TMPDIR/rec_bundle.json" \
    -o "$TMPDIR/rec_response.json"
check "POST /api/v1/knowledge/recommendations/batch succeeded" test -s "$TMPDIR/rec_response.json"
check "Recommendations ingested" python3 -c "
import json
d = json.load(open('$TMPDIR/rec_response.json'))
assert d.get('status') == 'ingested', f'got: {d.get(\"status\")}'
"
check "Count > 0" python3 -c "
import json
d = json.load(open('$TMPDIR/rec_response.json'))
assert d.get('count', 0) > 0, f'count: {d.get(\"count\")}'
"

# --- Verify: Data stored ---
echo ""
echo "5. Verify data stored"
curl -sf "$ACP_WRITER_URL/api/v1/guidelines" -o "$TMPDIR/guidelines_list.json"
check "Guidelines list not empty" python3 -c "
import json
d = json.load(open('$TMPDIR/guidelines_list.json'))
assert len(d) > 0
"

curl -sf "$ACP_WRITER_URL/api/v1/decisions/models" -o "$TMPDIR/models_list.json"
check "Decision models list not empty" python3 -c "
import json
d = json.load(open('$TMPDIR/models_list.json'))
assert len(d) > 0
"

curl -sf "$ACP_WRITER_URL/api/v1/knowledge/recommendations" -o "$TMPDIR/recs_list.json"
check "Recommendations list not empty" python3 -c "
import json
d = json.load(open('$TMPDIR/recs_list.json'))
assert len(d) > 0
"

# --- Verify: Search works ---
echo ""
echo "6. Verify recommendation search"
curl -sf -X POST "$ACP_WRITER_URL/api/v1/knowledge/search" \
    -H "Content-Type: application/json" \
    -d '{"query": "hypertension treatment medication", "source_cpg": "SYN-HTN-2026-001", "top_k": 5}' \
    -o "$TMPDIR/search_results.json"
check "Search returns results" python3 -c "
import json
d = json.load(open('$TMPDIR/search_results.json'))
assert len(d.get('results', [])) > 0, f'no results returned'
"

# --- Verify: Hybrid search with filters ---
echo ""
echo "7. Verify hybrid search with filters"

# Filter by recommendation type
curl -sf -X POST "$ACP_WRITER_URL/api/v1/knowledge/search" \
    -H "Content-Type: application/json" \
    -d '{"query": "blood pressure treatment", "recommendation_type": "treatment", "top_k": 5}' \
    -o "$TMPDIR/search_type.json"
check "Type filter: treatment returns results" python3 -c "
import json
d = json.load(open('$TMPDIR/search_type.json'))
results = d.get('results', [])
assert len(results) > 0, 'no treatment results'
for r in results:
    assert r['recommendation']['recommendation_type'] == 'treatment', f'got {r[\"recommendation\"][\"recommendation_type\"]}'
"

# Filter by strength
curl -sf -X POST "$ACP_WRITER_URL/api/v1/knowledge/search" \
    -H "Content-Type: application/json" \
    -d '{"query": "hypertension management", "strength_in": ["strong-for"], "top_k": 10}' \
    -o "$TMPDIR/search_strength.json"
check "Strength filter: strong-for returns results" python3 -c "
import json
d = json.load(open('$TMPDIR/search_strength.json'))
results = d.get('results', [])
assert len(results) > 0, 'no strong-for results'
"

# Filter by CPG
curl -sf -X POST "$ACP_WRITER_URL/api/v1/knowledge/search" \
    -H "Content-Type: application/json" \
    -d '{"query": "medication", "source_cpg": "SYN-HTN-2026-001", "top_k": 5}' \
    -o "$TMPDIR/search_cpg.json"
check "CPG filter: SYN-HTN-2026-001 returns results" python3 -c "
import json
d = json.load(open('$TMPDIR/search_cpg.json'))
results = d.get('results', [])
assert len(results) > 0, 'no results for CPG filter'
for r in results:
    assert r['recommendation']['source_cpg'] == 'SYN-HTN-2026-001', f'wrong cpg: {r[\"recommendation\"][\"source_cpg\"]}'
"

# Non-existent CPG returns empty
curl -sf -X POST "$ACP_WRITER_URL/api/v1/knowledge/search" \
    -H "Content-Type: application/json" \
    -d '{"query": "anything", "source_cpg": "NONEXISTENT-CPG", "top_k": 5}' \
    -o "$TMPDIR/search_empty_cpg.json"
check "CPG filter: non-existent CPG returns empty" python3 -c "
import json
d = json.load(open('$TMPDIR/search_empty_cpg.json'))
assert len(d.get('results', [])) == 0, 'should be empty for non-existent CPG'
"

# Lifestyle type filter
curl -sf -X POST "$ACP_WRITER_URL/api/v1/knowledge/search" \
    -H "Content-Type: application/json" \
    -d '{"query": "diet exercise lifestyle", "recommendation_type": "lifestyle", "top_k": 5}' \
    -o "$TMPDIR/search_lifestyle.json"
check "Type filter: lifestyle returns results" python3 -c "
import json
d = json.load(open('$TMPDIR/search_lifestyle.json'))
results = d.get('results', [])
assert len(results) > 0, 'no lifestyle results'
for r in results:
    assert r['recommendation']['recommendation_type'] == 'lifestyle', f'got {r[\"recommendation\"][\"recommendation_type\"]}'
"

# Search results have excerpts
check "Search results include excerpts" python3 -c "
import json
d = json.load(open('$TMPDIR/search_cpg.json'))
results = d.get('results', [])
has_excerpt = any(r.get('excerpt') for r in results)
assert has_excerpt, 'no excerpts in search results'
"

# --- Multi-CPG: Deliver second CPG (diabetes) ---
DIABETES_FIXTURES="$ROOT_DIR/tests/integration/fixtures/diabetes-cpg.json"
if [ -f "$DIABETES_FIXTURES" ]; then
    echo ""
    echo "8. Deliver second CPG (diabetes — overlapping scope)"

    python3 -c "
import json
data = json.load(open('$DIABETES_FIXTURES'))
json.dump(data['metadata'], open('$TMPDIR/dm2_metadata.json', 'w'))
json.dump(data['recommendation_bundle'], open('$TMPDIR/dm2_rec_bundle.json', 'w'))
"

    curl -sf -X POST "$ACP_WRITER_URL/api/v1/guidelines" \
        -H "Content-Type: application/json" \
        -d @"$TMPDIR/dm2_metadata.json" \
        -o "$TMPDIR/dm2_metadata_response.json"
    check "POST diabetes CPG metadata succeeded" test -s "$TMPDIR/dm2_metadata_response.json"

    curl -sf -X POST "$ACP_WRITER_URL/api/v1/knowledge/recommendations/batch" \
        -H "Content-Type: application/json" \
        -d @"$TMPDIR/dm2_rec_bundle.json" \
        -o "$TMPDIR/dm2_rec_response.json"
    check "POST diabetes recommendations succeeded" test -s "$TMPDIR/dm2_rec_response.json"

    echo ""
    echo "9. Verify multi-CPG search"

    # Both CPGs should return results for overlapping query
    curl -sf -X POST "$ACP_WRITER_URL/api/v1/knowledge/search" \
        -H "Content-Type: application/json" \
        -d '{"query": "ACE inhibitor blood pressure hypertension diabetes", "top_k": 10}' \
        -o "$TMPDIR/search_multi.json"
    check "Multi-CPG search returns results" python3 -c "
import json
d = json.load(open('$TMPDIR/search_multi.json'))
results = d.get('results', [])
assert len(results) > 0, 'no results'
"

    check "Results from both CPGs" python3 -c "
import json
d = json.load(open('$TMPDIR/search_multi.json'))
cpgs = set(r['recommendation']['source_cpg'] for r in d.get('results', []))
assert 'SYN-HTN-2026-001' in cpgs, f'missing HTN CPG, got: {cpgs}'
assert 'SYN-DM2-2026-001' in cpgs, f'missing DM2 CPG, got: {cpgs}'
"

    # CPG-specific filter still isolates
    curl -sf -X POST "$ACP_WRITER_URL/api/v1/knowledge/search" \
        -H "Content-Type: application/json" \
        -d '{"query": "medication treatment", "source_cpg": "SYN-DM2-2026-001", "top_k": 5}' \
        -o "$TMPDIR/search_dm2_only.json"
    check "DM2-only filter returns only DM2 results" python3 -c "
import json
d = json.load(open('$TMPDIR/search_dm2_only.json'))
results = d.get('results', [])
assert len(results) > 0, 'no results'
for r in results:
    assert r['recommendation']['source_cpg'] == 'SYN-DM2-2026-001', f'wrong cpg: {r[\"recommendation\"][\"source_cpg\"]}'
"

    # Two guidelines registered
    curl -sf "$ACP_WRITER_URL/api/v1/guidelines" -o "$TMPDIR/guidelines_multi.json"
    check "Two guidelines registered" python3 -c "
import json
d = json.load(open('$TMPDIR/guidelines_multi.json'))
assert len(d) >= 2, f'expected >= 2 guidelines, got {len(d)}'
"
fi

# --- Care Plan Generation (requires LLM) ---
if [ -n "${LITELLM_URL:-}" ]; then
    echo ""
    echo "10. Generate Care Plan (LLM required — may take 1-2 minutes)"
    curl -sf -X POST "$ACP_WRITER_URL/api/v1/careplans" \
        -H "Content-Type: application/fhir+json" \
        --data-binary "@$PATIENT_BUNDLE" \
        --max-time 300 \
        -o "$TMPDIR/careplan_response.json" || true
    if [ -s "$TMPDIR/careplan_response.json" ]; then
        check "Response is FHIR Bundle" python3 -c "
import json
d = json.load(open('$TMPDIR/careplan_response.json'))
assert d.get('resourceType') == 'Bundle', f'got: {d.get(\"resourceType\")}'
"
        check "Bundle has entries" python3 -c "
import json
d = json.load(open('$TMPDIR/careplan_response.json'))
assert len(d.get('entry', [])) > 0
"
        check "Contains CarePlan resource" python3 -c "
import json
d = json.load(open('$TMPDIR/careplan_response.json'))
types = [e['resource']['resourceType'] for e in d.get('entry', [])]
assert 'CarePlan' in types, f'resource types: {types}'
"
    else
        echo "  ✗ Care plan generation failed or timed out"
        failed=$((failed + 1))
        total=$((total + 1))
    fi
else
    echo ""
    echo "10. Skipping care plan generation (set LITELLM_URL to enable)"
fi

# --- Summary ---
echo ""
echo "=== Results: $passed/$total passed, $failed failed ==="
if [ $failed -gt 0 ]; then
    exit 1
fi
