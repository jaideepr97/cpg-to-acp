# Spike B: UI ↔ Backend Interaction Pattern

**Phase:** 4 | **Status:** Complete | **Date:** 2026-07-23

## Problem

The backend uses SonataFlow with async callbacks for LLM-heavy steps. A pipeline run takes 3-10 minutes (Docling parsing + multiple LLM calls + FHIR generation). The UI **must not** make blocking calls — it needs to trigger work, show progress, and display results as they arrive.

Additionally, the system includes human-in-the-loop review steps (clinician approves/rejects care plans, reviews recommendations). These need to pause the pipeline and wait for human input.

## Decision

**Polling with SonataFlow workflow REST API + direct service calls for human actions.**

The UI does NOT talk to SonataFlow via CloudEvents or callbacks. Instead:

1. **Trigger:** UI POSTs to the SonataFlow workflow endpoint to start a pipeline run
2. **Poll:** UI polls the workflow instance for status and intermediate results
3. **Display:** As each async step completes (its data appears in the workflow state), the UI updates
4. **Human action:** For approve/reject, the UI calls the service endpoints directly (e.g., PUT to fhir-server for care plan status)

```
┌──────────┐          ┌───────────┐          ┌──────────────┐
│   UI     │          │ SonataFlow │          │  Pod Services│
│ (React)  │          │ Workflow   │          │  (FastAPI)   │
└────┬─────┘          └─────┬─────┘          └──────┬───────┘
     │                      │                       │
     │ POST /cpgingester    │                       │
     │ {pdf_ref: "..."}     │                       │
     │─────────────────────>│                       │
     │      201 {id: "..."}│                        │
     │<─────────────────────│                       │
     │                      │ POST /parse-async     │
     │                      │──────────────────────>│
     │                      │      200 accepted     │
     │                      │<──────────────────────│
     │                      │                       │
     │ GET /cpgingester/{id}│                       │ (parsing...)
     │─────────────────────>│                       │
     │  {status: "accepted"}│                       │
     │<─────────────────────│                       │
     │                      │                       │
     │         ...polling...│                       │
     │                      │   CloudEvent callback │
     │                      │<──────────────────────│
     │                      │                       │
     │ GET /cpgingester/{id}│                       │
     │─────────────────────>│                       │
     │  {parseResult: {...}}│                       │
     │<─────────────────────│                       │
     │                      │                       │
     │  (UI shows parse     │                       │
     │   results to user)   │                       │
```

## Why Polling (Not WebSockets or SSE)

| Option | Pros | Cons |
|---|---|---|
| **Polling** | Simplest. Works through all proxies/load balancers. Stateless — refreshing the page resumes from last state. SonataFlow already has a REST API for querying workflow instances. | Latency between updates (poll interval). Wasted requests when nothing changed. |
| **WebSockets** | Real-time updates. No wasted requests. | Requires WebSocket support in all proxy layers (API gateway, OpenShift Route). Stateful connections — page refresh loses context. Need a new WebSocket service. |
| **SSE (Server-Sent Events)** | Real-time, simpler than WebSockets. Works through most proxies. | Need a new SSE endpoint. SonataFlow doesn't have one natively. |

**Polling wins** because:
1. SonataFlow already exposes `GET /cpgingester/{id}` and `GET /acpwriter/{id}` — zero backend work needed
2. The pipeline runs for minutes — polling every 5-10 seconds is fine (not real-time chat)
3. Stateless — user can close the browser and come back, the workflow is still running
4. No proxy/networking concerns (WebSockets through OpenShift Routes need special configuration)

### Optimization: Adaptive Polling

Start polling at 2-second intervals. After 30 seconds with no state change, slow to 10 seconds. After 2 minutes, slow to 30 seconds. Reset to fast polling when state changes.

## Human-in-the-Loop Pattern

Human review is part of the core workflow, not an afterthought. Both pipelines have steps where the workflow must **pause and wait for human input** before continuing.

### cpg-ingester review points

1. **After item identification** — the user reviews and edits the manifest of decisions and recommendations before DMN/recommendation generation begins. If the classification is wrong, everything downstream is wrong. This is a quality gate.

2. **After generation, before delivery** — the user reviews the extracted DMN tables and recommendations before they're sent to acp-writer. Final approval before artifacts enter the system.

### acp-writer review points

3. **After care plan written** — the clinician reviews the generated care plan and approves or rejects it. This changes the FHIR status (draft → active or entered-in-error).

### Implementation: SonataFlow Callback states driven by the UI

Human review uses the **same Callback state pattern** as the LLM async callbacks — the only difference is that the "async work" is a human making a decision instead of a model generating text. The workflow pauses, the UI shows the review screen, and when the user acts, the UI sends the CloudEvent to resume the workflow.

```
SonataFlow                    UI (React)
    │                           │
    │ (workflow reaches          │
    │  ReviewManifest state)     │
    │                           │
    │ POST /notify-ui           │
    │ {callback_url,            │
    │  manifest_ref,            │
    │  process_instance_id}     │
    │──────────(to UI backend)──>│
    │                           │
    │ (workflow WAITING)        │ (UI shows manifest review)
    │                           │ (user edits classifications)
    │                           │ (user clicks "Approve")
    │                           │
    │ POST /wait-manifest-review│
    │ CloudEvent {              │
    │   type: "manifest-reviewed",│
    │   kogitoprocrefid: "...", │
    │   data: {                 │
    │     approved: true,       │
    │     manifest_ref: "..."   │
    │   }                       │
    │ }                         │
    │<──────────────────────────│
    │                           │
    │ (workflow RESUMES →       │
    │  generate DMN/Recs)       │
```

### How the UI knows to show a review screen

The UI polls the workflow state (`GET /cpgingester/{id}`). When the workflow reaches a human review Callback state, the state data includes a marker (e.g., `awaiting_review: "manifest"` or `awaiting_review: "pre-delivery"`). The UI transitions to the appropriate review screen.

When the user completes the review, the UI POSTs a CloudEvent to the callback URL (stored in the workflow state). This is the same `post_callback()` pattern used by the LLM services, but called from the UI's backend-for-frontend (BFF) or directly from the browser.

### Three tiers of human interaction

| Tier | Pattern | When |
|---|---|---|
| **Observe** | Poll workflow state, display progress | Pipeline is running (automated steps) |
| **Review & approve** | Workflow pauses at Callback state, UI shows review, user sends callback | Quality gates (manifest review, pre-delivery review) |
| **Post-pipeline action** | Direct API call (not through SonataFlow) | Care plan approve/reject (already on FHIR server) |

All three tiers use polling as the primary communication channel. The difference is whether the user's action resumes the workflow (tier 2) or modifies a completed artifact (tier 3).

## API Endpoints the UI Calls

### cpg-ingester UI

| Action | Method | Endpoint | Through |
|---|---|---|---|
| Upload PDF to MinIO | PUT | MinIO S3 API | Direct (presigned URL) or via upload service |
| Start ingestion | POST | `/cpgingester` | SonataFlow workflow |
| Poll status | GET | `/cpgingester/{id}` | SonataFlow workflow |
| List runs | GET | `/cpgingester` | SonataFlow workflow |
| View artifacts | GET | MinIO S3 API | Direct |

### acp-writer UI

| Action | Method | Endpoint | Through |
|---|---|---|---|
| Start care plan generation | POST | `/acpwriter` | SonataFlow workflow |
| Poll status | GET | `/acpwriter/{id}` | SonataFlow workflow |
| List care plans | GET | `/api/v1/careplans` | API gateway |
| View care plan | GET | `/api/v1/careplans/{id}` | API gateway |
| Approve care plan | PUT | `/api/v1/careplans/{id}/status` | API gateway |
| Reject care plan | PUT | `/api/v1/careplans/{id}/status` | API gateway |
| List patients | MCP | `ehr_list_patients` | MCP Gateway |
| Get patient summary | MCP | `ehr_get_patient_summary` | MCP Gateway |

### Authentication (Phase 4 lightweight)

For the Phase 4 demo, the UI talks to the SonataFlow and API gateway endpoints without authentication. Patient context is passed directly (not via SMART on FHIR token). The lightweight auth (Medplum built-in, Keycloak minimal, or mock stub) is added in Phase 4 step 4.4.

## State Management

Use React Query (TanStack Query) for:
- Polling with `refetchInterval`
- Cache management
- Optimistic updates for approve/reject

```typescript
const { data: workflow } = useQuery({
  queryKey: ['workflow', workflowId],
  queryFn: () => fetchWorkflowStatus(workflowId),
  refetchInterval: (data) => {
    if (data?.workflowdata?.status === 'completed') return false
    return 5000 // 5 second poll
  },
})
```

## Error Handling

- If SonataFlow workflow errors (LLM failure, MinIO unreachable), the workflow state includes the error message. The UI displays it with a retry option.
- If a service is down, the SonataFlow workflow stays in waiting state. The UI shows "waiting for [step name]..." and the clinician can check back later.
- Network errors from the UI to the backend → standard React Query retry with exponential backoff.

## References

- [SonataFlow REST API](https://sonataflow.org/serverlessworkflow/latest/) — workflow instance query
- [TanStack Query](https://tanstack.com/query/latest) — React data fetching with polling
- [PatternFly ChatBot](https://www.patternfly.org/patternfly-ai/chatbot/about-chatbot/) — for displaying pipeline progress as a conversation
- `dev_docs/spikes/spike-async-callback.md` — the backend async pattern this UI consumes
