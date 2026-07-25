# Spike: SonataFlow for Pod-Split Pipeline Orchestration

**Date:** 2026-07-21
**Status:** In progress
**Branch:** `feature/phase3.3-integration-governance`

## Decision

**SonataFlow selected** for cross-pod orchestration (Apache KIE, same ecosystem as Kogito/Drools). This spike is about how to use it, not whether to use it.

## What is SonataFlow?

SonataFlow is the Apache KIE implementation of the [CNCF Serverless Workflow specification v0.8](https://serverlessworkflow.io/). It provides a declarative YAML/JSON DSL for defining workflows that orchestrate service calls, with an operator for deployment on Kubernetes/OpenShift.

### Available on our cluster

| Operator | Version | Source | Notes |
|---|---|---|---|
| `logic-operator-rhel8` | v1.36.1 | Red Hat Operators | Supported, labeled "Alpha" |
| `sonataflow-operator` | v10.0.0 | Community Operators | Upstream Apache KIE |

Both use the same API (`sonataflow.org/v1alpha08`) and require `AllNamespaces` install mode (cluster-wide). **Recommendation: Use the Red Hat operator** for consistency with the platform story.

### RHDH Orchestrator

The RHDH (Red Hat Developer Hub) Orchestrator is a UI plugin for managing SonataFlow workflows — it's not a separate orchestration engine. It uses SonataFlow under the hood. Not required for our use case; we drive workflows via REST API.

## Key Findings

### 1. Sequential REST calls — supported via operation states

Functions are defined as OpenAPI-based (with spec file) or custom REST (no spec needed). State transfer uses jq expressions:

```yaml
functions:
  - name: scanPatient
    type: custom
    operation: rest:post:/api/v1/scan
states:
  - name: ScanPatient
    type: operation
    actions:
      - functionRef:
          refName: scanPatient
          arguments:
            ips_bundle: "${ .ips_bundle }"
            HEADER_X-MLflow-Run-ID: "${ .mlflow_run_id }"
    transition: NextStep
```

Base URLs configured via `application.properties`:
```properties
kogito.sw.functions.scanPatient.host=${PATIENT_DATA_URL:http://patient-data:8080}
```

### 2. Review-loop pattern — supported via switch + inject states

No built-in loop construct — implemented manually with a counter in the workflow data model:

```yaml
states:
  - name: InitReviewCounter
    type: inject
    data:
      reviewCount: 0
      maxReviews: 4
    transition: Compose

  - name: Compose
    type: operation
    actions:
      - functionRef:
          refName: composePlan
          arguments:
            input: "${ .patientData }"
            feedback: "${ .reviewFeedback }"
    transition: Review

  - name: Review
    type: operation
    actions:
      - functionRef:
          refName: reviewBrief
          arguments:
            draft: "${ .composerOutput }"
    transition: IncrementAndCheck

  - name: IncrementAndCheck
    type: inject
    data: {}
    stateDataFilter:
      output: "${ . + {reviewCount: (.reviewCount + 1)} }"
    transition: CheckVerdict

  - name: CheckVerdict
    type: switch
    dataConditions:
      - name: Approved
        condition: '${ .reviewOutput.verdict == "APPROVE" }'
        transition: NextPhase
      - name: MaxReached
        condition: "${ .reviewCount >= .maxReviews }"
        transition: NextPhase
    defaultCondition:
      transition: Compose
```

### 3. State transfer — embedded JSON, no size limit

The workflow maintains a single JSON data model. Data flows through `actionDataFilter` (per-action) and `stateDataFilter` (per-state) using jq expressions. **No specification-defined size limit** — practical limits are JVM heap and persistence backend (PostgreSQL supports ~1GB per jsonb value). A 50KB FHIR Bundle is not a concern.

Use `actionDataFilter.results` and `toStateData` to trim unnecessary data between states rather than carrying the full payload everywhere.

### 4. Direct REST, not CloudEvents

For our synchronous request-response pipeline, **direct REST invocation is the right choice**:
- No Knative Eventing or broker infrastructure required
- Results return synchronously in the HTTP response
- Simpler configuration and debugging

CloudEvents would only be needed for async patterns (e.g., human review with long wait). Our clinician review is currently a separate flow (approve/reject via UI), not inline in the pipeline.

### 5. MLflow trace propagation — supported via HEADER_ prefix

Custom REST functions support the `HEADER_<name>` pattern in arguments:

```yaml
arguments:
  patientData: "${ .patientBundle }"
  HEADER_X-MLflow-Run-ID: "${ .mlflow_run_id }"
```

This adds `X-MLflow-Run-ID` as an HTTP header on the outgoing request. The workflow receives the run ID in its initial request body and propagates it to all downstream calls.

### 6. Deployment model

**CRDs created by the operator:**

| CRD | Scope | Purpose |
|---|---|---|
| `SonataFlow` | Namespaced | Workflow definition and deployment |
| `SonataFlowBuild` | Namespaced | Workflow image builds |
| `SonataFlowPlatform` | Namespaced | Per-namespace config (builds, persistence) |
| `SonataFlowClusterPlatform` | Cluster | Cluster-wide platform config |

**Minimal SonataFlowPlatform for our namespace:**

```yaml
apiVersion: sonataflow.org/v1alpha08
kind: SonataFlowPlatform
metadata:
  name: sonataflow-platform
  namespace: sschifma-cpg-to-acp
spec:
  services:
    dataIndex:
      enabled: false
    jobService:
      enabled: false
```

On OpenShift, the operator auto-configures builds using BuildConfig and the internal registry — no external registry needed.

## Prototype: acp-writer Pipeline as SonataFlow Workflow

### Pod groups → REST services

| Pod Group | Endpoint | Input | Output |
|---|---|---|---|
| Patient Data | `POST /api/v1/scan` | IPS Bundle | patient_reference, demographics, conditions, medications, allergies |
| LLM Reasoning | `POST /api/v1/resolve` | conditions, applicable_cpgs | applicable_cpgs, dmn_models, dependency_graph |
| Decision Engine | `POST /api/v1/execute` | dmn_models, ips_bundle | dmn_results |
| LLM Reasoning | `POST /api/v1/retrieve` | conditions, dmn_results, cpgs | recommendations |
| LLM Reasoning | `POST /api/v1/compose` | all phase 1 data + feedback | planning_brief |
| LLM Reasoning | `POST /api/v1/review-brief` | planning_brief, recommendations | verdict, feedback |
| FHIR Generation | `POST /api/v1/generate-bundle` | planning_brief, demographics | fhir_bundle |
| FHIR Generation | `POST /api/v1/validate` | fhir_bundle | terminology_issues, syntax_errors |
| LLM Reasoning | `POST /api/v1/review-fhir` | fhir_bundle, issues, errors | verdict, feedback |
| FHIR Server | `POST /api/v1/write` | fhir_bundle, patient_reference | careplan_id, delivery_status |

### Pipeline topology in SonataFlow

```
ScanPatient → ResolveGuidelines → ExecuteDMN → RetrieveRecommendations →
  InitBriefReview → ComposePlan → ReviewBrief → CheckBriefVerdict →
    (REVISE → ComposePlan) | (APPROVE → GenerateBundle) →
  InitFHIRReview → ValidateBundle → ReviewFHIR → CheckFHIRVerdict →
    (REVISE → GenerateBundle) | (APPROVE → WriteFHIR) →
  Done
```

### Key design decisions

1. **LLM Reasoning pod handles multiple workflow steps** — Guideline Resolver, Recommendation Retriever, Plan Composer, Brief Reviewer, and FHIR Semantic Reviewer all run in the same pod (they share the LLM and vector store). The SonataFlow workflow calls different endpoints on the same service.

2. **FHIR Generation pod combines bundle generation and validation** — the `POST /api/v1/validate` endpoint runs both Terminology Validator and FHIR Syntax Validator in parallel (using the existing LangGraph fan-out within the pod).

3. **Review loops are orchestrator-level** — the SonataFlow workflow handles the review loop (compose → review → check → loop back), not in-process LangGraph. Each call to compose/review is a REST request.

4. **State trim at each step** — use `actionDataFilter` to avoid carrying the full IPS Bundle through all 15+ states. Extract what's needed, discard the rest.

## Hands-On Findings

### Operator installation

Installed `logic-operator-rhel8` v1.36.1 (Red Hat, Alpha channel). Requires manual InstallPlan approval (cluster policy). Operator deploys to `openshift-operators` namespace. CRDs registered: `sonataflows`, `sonataflowbuilds`, `sonataflowplatforms`, `sonataflowclusterplatforms`.

### SonataFlowPlatform

Created successfully in `sschifma-cpg-to-acp` with minimal config (dataIndex and jobService disabled). Ready immediately. On OpenShift, builds use internal registry automatically.

### Hello-world workflow — lessons learned

1. **Workflow names cannot contain hyphens** — the code generator creates Java identifiers from the name. Use lowercase alphanumeric names (e.g., `hellorest` not `hello-rest`).

2. **Custom REST functions: use full URLs in the operation field** — the `kogito.sw.functions.<name>.host` property has camelCase mapping issues with environment variables. Putting the full URL in the operation works reliably:
   ```yaml
   functions:
     - name: getfhirmetadata
       type: custom
       operation: rest:get:http://cpg-mock-ehr-hapi-fhir:8080/fhir/metadata
   ```

3. **Dev mode managed-props are overwritten** — the operator manages `<name>-managed-props` ConfigMap and overwrites user changes on reconciliation. Use `podTemplate.container.env` for custom configuration, or embed config in the workflow itself.

4. **Dev profile** uses `application-dev.properties`. The auto-created `<name>-managed-props` ConfigMap contains dev-profile settings.

5. **Successful test:** Workflow called HAPI FHIR's metadata endpoint and returned filtered results via jq expression:
   ```json
   {"id": "...", "workflowdata": {"fhirServer": {"fhirVersion": "8.10.0", "serverName": "HAPI FHIR Server"}, "status": "completed"}}
   ```

### Review-loop pattern — verified

Tested with a real REST mock reviewer service. Workflow calls reviewer, checks verdict via switch state, loops back on REVISE, exits on APPROVE or max iterations.

**Test result:** Reviewer returned REVISE on call 1, APPROVE on call 2. Workflow looped once and exited with `status: "approved"`, `revisionCount: 2`. Max iteration guard also verified separately (3 loops then exit).

**Verified workflow structure:**
```yaml
states:
  - name: InitCounter
    type: inject
    data: { revisionCount: 0, maxRevisions: 4, feedback: "" }
    transition: Compose

  - name: Compose
    type: inject          # would be operation state calling real compose service
    data: {}
    stateDataFilter:
      output: "${ . + {currentDraft: (\"draft-v\" + (.revisionCount | tostring))} }"
    transition: Review

  - name: Review
    type: operation
    actions:
      - functionRef:
          refName: callreviewer
          arguments:
            draft: "${ .currentDraft }"
            feedback: "${ .feedback }"
        actionDataFilter:
          results: "${ {verdict: .verdict, feedback: .feedback} }"
          toStateData: "${ .reviewResult }"
    transition: IncrementAndCheck

  - name: IncrementAndCheck
    type: inject
    data: {}
    stateDataFilter:
      output: "${ . + {revisionCount: (.revisionCount + 1), feedback: .reviewResult.feedback} }"
    transition: CheckVerdict

  - name: CheckVerdict
    type: switch
    dataConditions:
      - name: Approved
        condition: '${ .reviewResult.verdict == "APPROVE" }'
        transition: Approved
      - name: MaxReached
        condition: "${ .revisionCount >= .maxRevisions }"
        transition: MaxRevisionsReached
    defaultCondition:
      transition: Compose          # LOOP BACK
```

### For pod-split deployment

For production workflows (not dev mode), base URLs should be configurable via environment variables. Use lowercase function names and provide URLs via env vars:
```yaml
spec:
  podTemplate:
    container:
      env:
        - name: PATIENT_DATA_URL
          value: "http://patient-data:8080"
        - name: LLM_REASONING_URL
          value: "http://llm-reasoning:8080"
```

Then reference in function operations:
```yaml
functions:
  - name: scanpatient
    type: custom
    operation: rest:post:${PATIENT_DATA_URL}/api/v1/scan
```

## Status

All critical patterns verified on OpenShift. SonataFlow is ready for use in Steps 10-11 (pod split).

### What's verified

| Pattern | Result |
|---|---|
| Sequential REST calls | Verified — hello-world called HAPI FHIR metadata |
| Review-loop with counter | Verified — conditional exit on APPROVE, max iteration guard |
| State transfer via jq | Verified — data flows between states, jq expressions work |
| Custom REST functions | Verified — full URL in operation field works reliably |
| Direct REST (not CloudEvents) | Verified — synchronous request-response works |
| MLflow header propagation | Designed — HEADER_ prefix pattern (not tested, will verify during pod split) |

### What's deferred to pod-split implementation (Steps 10-11)

- Full acp-writer pipeline topology as a SonataFlow workflow
- Production mode deployment (build from source instead of dev mode)
- State trimming between steps (actionDataFilter optimization)
- MLflow HEADER_ prefix verification with real tracing
- Environment variable URL injection (`${VAR_NAME}`) for service discovery

## Next Steps

- [x] Install the `logic-operator-rhel8` operator
- [x] Create SonataFlowPlatform in `sschifma-cpg-to-acp`
- [x] Build hello-world workflow (REST call verified)
- [x] Build review-loop workflow (conditional exit + max iterations verified)
- [x] Document deployment model, patterns, state management
- Deferred to Steps 10-11: Full pipeline prototype (will build during pod split when real services exist)

## References

- [CNCF Serverless Workflow Spec v0.8](https://github.com/serverlessworkflow/specification/blob/0.8.x/specification.md)
- [SonataFlow Documentation](https://sonataflow.org/serverlessworkflow/latest/index.html)
- [SonataFlow Custom Functions](https://sonataflow.org/serverlessworkflow/latest/core/custom-functions-support.html) — HEADER_ prefix for custom headers
- [SonataFlow Operator Installation](https://sonataflow.org/serverlessworkflow/latest/cloud/operator/install-serverless-operator.html)
- [Red Hat OpenShift Serverless Logic](https://docs.redhat.com/en/documentation/red_hat_openshift_serverless/1.33/html/serverless_logic/getting-started)
