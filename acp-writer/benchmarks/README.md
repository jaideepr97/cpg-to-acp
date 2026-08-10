# Clinical QA Benchmark

Measures how well acp-writer answers clinical questions about patient data from FHIR IPS bundles.

## Quick Start

```bash
cd acp-writer

# Run the smoke suite against the current implementation
.venv/bin/python -m acp_writer.benchmark run --suite smoke --backend current --no-mlflow

# Verbose output (per-case results)
.venv/bin/python -m acp_writer.benchmark run --suite smoke --backend current --no-mlflow -v

# List available suites and backends
.venv/bin/python -m acp_writer.benchmark list
```

## Directory Structure

```
benchmarks/
  suites/         # Test case JSON files (one per suite)
    smoke.json    # 50-question smoke suite
  bundles/        # FHIR IPS bundles used by test cases
    htn-temporal-01.json     # HTN patient, 8 BP readings over 6 months
    ckd-declining-01.json    # CKD patient, declining eGFR series
    edge-missing-dates.json  # Observations with missing/partial dates
    edge-coded-values.json   # Observations with valueCodeableConcept
    complex-patient-01.json  # 5+ conditions, 10+ meds, multi-year history
```

## Test Case Format

Each suite is a JSON array of test case objects:

```json
{
  "id": "smoke-temporal-007",
  "question": "Was a basic metabolic panel obtained within 2 weeks of starting lisinopril?",
  "structured_intent": {
    "function": "cross_resource_temporal",
    "params": {
      "anchor_resource": "MedicationRequest",
      "anchor_code": "http://www.nlm.nih.gov/research/umls/rxnorm|314076",
      "target_code": "http://loinc.org|51990-0",
      "window": "P14D"
    }
  },
  "bundle": "bundles/complex-patient-01.json",
  "reference_date": "2026-06-01",
  "expected": {"kind": "boolean", "value": true},
  "expected_provenance": ["Observation/obs-bmp-01"],
  "category": "temporal",
  "level": 4
}
```

### Fields

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Unique identifier |
| `question` | Yes | Natural language clinical question |
| `structured_intent` | No | Machine-readable query plan (function + params) |
| `bundle` | Yes | Relative path to the IPS bundle file |
| `reference_date` | Yes | ISO date string — "now" for temporal queries (no wall-clock dependency) |
| `expected` | Yes | `{"kind": "<type>", "value": <answer>}` |
| `expected_provenance` | No | FHIR references that should appear in the answer's provenance |
| `category` | Yes | One of: lookup, boolean, threshold, temporal, insufficient_data |
| `level` | Yes | Complexity level (1-6) |

### Expected Kinds

- `number` — numeric value (scored with configurable tolerance)
- `count` — integer count (exact match)
- `boolean` — true/false
- `code` — string code value (exact match)
- `insufficient_data` — correct answer is "I don't know"

## Adding Test Cases

1. Create or reuse a bundle in `bundles/`
2. Add test cases to an existing suite or create a new suite JSON file in `suites/`
3. **Verify every expected answer by hand** against the bundle data
4. Ensure all bundles have `id` fields on every resource (required for provenance tracking)

## Adding Backends

1. Create a new file in `acp_writer/benchmark/backends/`
2. Implement the `QABackend` protocol (see `protocol.py`)
3. Register it in `backends/__init__.py`

## Scoring

- **Correct**: value matches expected (exact for boolean/code/count, tolerance for number)
- **Hallucination**: backend returns a concrete value when `insufficient_data` was expected (tracked separately — worse than a miss)
- **Provenance**: set match (order-insensitive) on FHIR references
- **Error**: backend raised an exception or returned an error message
