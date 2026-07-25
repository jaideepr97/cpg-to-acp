# Spike: Async Callback Pattern for LLM-Heavy Workflow Steps

**Date:** 2026-07-22
**Status:** In progress
**Branch:** `feature/phase3.3-integration-governance`

## Problem

SonataFlow uses synchronous REST calls that hold the HTTP connection open until the service responds. LLM-heavy steps (compose, generate-bundle, review-fhir) take 60-120+ seconds due to multiple LLM API calls. SonataFlow's Vert.x HTTP client has a ~60s timeout that resists configuration. This is fundamental — holding connections open for minutes is fragile and won't scale for agentic AI workflows with variable, unpredictable execution times.

## Decision

Use the SonataFlow **Callback state** with **HTTP-based CloudEvents** (no Kafka). The service returns immediately, processes in the background, and POSTs a CloudEvent back to the workflow's callback URL when done.

## How It Works

```
SonataFlow Workflow                    LLM Reasoning Pod
       |                                      |
       |-- POST /api/v1/compose-async -------→|
       |   { data...,                         |
       |     callback_url: ".../wait-compose",|
       |     process_instance_id: "<uuid>" }  |
       |                                      |
       |←---- 200 OK (accepted) ------------- |
       |                                      |
       | (workflow is WAITING)                |
       |                                      |
       |                          (background: LLM calls,
       |                           compose + review loop,
       |                           store result in MinIO)
       |                                      |
       | ←--- POST /wait-compose ------------ |
       |   CloudEvent {                       |
       |     type: "compose-done",            |
       |     kogitoprocrefid: "<uuid>",       |
       |     data: {planning_brief_ref: "..."} |
       |   }                                  |
       |                                      |
       | (workflow RESUMES → next state)      |
```

### Key design points

- **No Kafka** — uses `quarkus-http` connector. CloudEvents arrive via direct HTTP POST to a path on the SonataFlow pod.
- **Correlation** — workflow instance ID passed as `process_instance_id`, returned as `kogitoprocrefid` CloudEvent extension.
- **Artifact store** — results stored in MinIO, only the ref is passed back in the CloudEvent (keeps events small).
- **Graceful** — if the callback fails, the workflow stays in waiting state (can be retried or timed out).

## Which steps go async

| Step | Async? | Why |
|---|---|---|
| `scan` | No | Pure FHIR parsing, <1s |
| `resolve` | No | Guideline lookup, typically fast |
| `execute` | No | DMN evaluation via Kogito, <5s |
| `retrieve` | No | Vector search, <2s |
| **`compose`** | **Yes** | Plan composer + brief reviewer loop (2-4 LLM calls), 60-120s |
| **`generate-bundle`** | **Yes** | FHIR bundle generation (LLM call), 30-60s |
| **`review-fhir`** | **Yes** | FHIR semantic review (LLM call), 20-40s |
| `write` | No | FHIR server POST, <5s |

## Workflow YAML changes

### Event definitions (new)

```yaml
events:
  - name: composeDone
    source: ""
    type: compose-done
  - name: generateDone
    source: ""
    type: generate-done
  - name: reviewDone
    source: ""
    type: review-done
```

### Callback state (replaces operation state)

```yaml
- name: ComposePlan
  type: callback
  action:
    functionRef:
      refName: composeplanasynch
      arguments:
        callback_url: "${ \"http://acpwriter:80/wait-compose\" }"
        process_instance_id: "$WORKFLOW.instanceId"
        patient_reference: "${ .patientData.patient_reference }"
        # ... other small fields ...
        recommendations_ref: "${ .recData.recommendations_ref }"
  eventRef: composeDone
  eventDataFilter:
    data: "${ . }"
    toStateData: "${ .composerData }"
  transition: InitFHIRReview
```

### SonataFlow properties (application.properties)

```properties
# HTTP event listeners for async callbacks (no Kafka)
mp.messaging.incoming.compose-done.connector=quarkus-http
mp.messaging.incoming.compose-done.path=/wait-compose

mp.messaging.incoming.generate-done.connector=quarkus-http
mp.messaging.incoming.generate-done.path=/wait-generate

mp.messaging.incoming.review-done.connector=quarkus-http
mp.messaging.incoming.review-done.path=/wait-review
```

## Service changes

Each async endpoint:
1. Accepts the request with `callback_url` and `process_instance_id`
2. Returns 200 immediately
3. Spawns a background task that does the LLM work
4. When done, POSTs a CloudEvent to `callback_url`

```python
@app.post("/api/v1/compose-async")
async def compose_async(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    callback_url = data.pop("callback_url")
    process_instance_id = data.pop("process_instance_id")
    background_tasks.add_task(
        _run_compose, data, callback_url, process_instance_id
    )
    return {"status": "accepted"}

def _run_compose(data, callback_url, process_instance_id):
    # ... do the LLM work (takes 60-120s) ...
    result = {"planning_brief_ref": ref}

    # POST CloudEvent back to SonataFlow
    cloud_event = {
        "specversion": "1.0",
        "id": str(uuid4()),
        "source": "",
        "type": "compose-done",
        "kogitoprocrefid": process_instance_id,
        "data": result,
    }
    requests.post(callback_url, json=cloud_event,
                  headers={"Content-Type": "application/cloudevents+json"})
```

## Review loop with callbacks

The FHIR review loop (generate-bundle → review-fhir → check → loop back) needs special handling in callback mode. Two options:

**Option A: Keep the loop in the workflow, each iteration is a callback**
- GenerateBundle is a callback state → waits for generate-done
- ReviewFHIR is a callback state → waits for review-done
- CheckVerdict is a switch → loops back to GenerateBundle if needed
- Each iteration makes 2 async round-trips (generate + review)

**Option B: Move the entire review loop into the service**
- A single async endpoint handles the full loop internally
- Calls generate-bundle, then review-fhir, iterates, returns final result
- Simpler workflow (one callback), but moves orchestration logic into the service

**Recommendation:** Option A — keep the loop in the workflow. The workflow is the orchestrator; services are stateless workers. This matches the SonataFlow design philosophy and keeps the flow visible in the workflow definition.

## References

- [SonataFlow Callback states](https://sonataflow.org/serverlessworkflow/latest/core/working-with-callbacks.html)
- [OpenAPI callback example](https://sonataflow.org/serverlessworkflow/latest/use-cases/advanced-developer-use-cases/callbacks/openapi-callback-events-example.html)
- [CNCF Serverless Workflow Callback State spec](https://github.com/serverlessworkflow/specification/blob/0.8.x/specification.md#Callback-State)
- [Quarkus HTTP connector](https://quarkus.io/guides/reactive-messaging-http) — for receiving CloudEvents via HTTP
