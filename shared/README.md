# Shared Resources

Cross-component contracts and utilities. Used sparingly to prevent coupling between components.

## cpg-contracts

Python package defining the data types that form the API contract between components. Both cpg-ingester and acp-writer depend on this package; neither depends on the other.

Contract version: `1.0` (see `CONTRACT_VERSION` in `cpg_contracts.guidelines`)

### Contract Types

| Module | Types | Boundary |
|---|---|---|
| `cpg_contracts.guidelines` | `CPGMetadata`, `GradingSystem`, `CONTRACT_VERSION` | cpg-ingester → acp-writer (guideline registration) |
| `cpg_contracts.decisions` | `DecisionModelSummary`, `DecisionVariable`, `DecisionCategory`, `DecisionEvaluationRequest`, `DecisionEvaluationResponse` | cpg-ingester → acp-writer (DMN deployment and evaluation) |
| `cpg_contracts.recommendations` | `Recommendation`, `RecommendationBundle`, `RecommendationSummary`, `CertaintyGrade`, `CrossReference`, enums (`RecommendationStrength`, `EvidenceQuality`, `RecommendationType`, `RecommendationProvenance`, `CrossReferenceRelationship`) | cpg-ingester → acp-writer (knowledge ingestion) |
| `cpg_contracts.search` | `RecommendationSearchRequest`, `RecommendationSearchResult`, `RecommendationSearchResponse` | acp-writer internal (knowledge retrieval) |
| `cpg_contracts.fhir` | `PatientSummary` | mock-EHR → acp-writer (patient data) |
| `cpg_contracts.automation` | BPMN automation IR, compiler, catalog and validation contracts | cpg-ingester → acp-writer → automation |

### Installation

```bash
pip install -e shared/
```

Or as a dependency in another component's `pyproject.toml`:
```toml
dependencies = [
    "cpg-contracts @ file:///${PROJECT_ROOT}/shared",
]
```

### MinIO credentials in OpenShell sandboxes

The artifact-store client uses `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
when both are present. In an OpenShell sandbox these are provider-supplied
placeholders; the MinIO endpoint policy must enable proxy-side SigV4 signing
(`signing_service: s3`, `signing_region: us-east-1`). The client sends ordinary
boto3 `GetObject`/`PutObject` requests so the proxy can re-sign them. It never
generates presigned URLs with sandbox placeholders.

Regular deployments such as the BFF continue to use
`ARTIFACT_STORE_ACCESS_KEY` and `ARTIFACT_STORE_SECRET_KEY` directly. Both AWS
variables must be present together, or artifact-store initialization fails.
