# acp-writer UI — BFF Contract Re-architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-architect the acp-writer React UI from a direct-to-backend, FHIR-parsing client into a pure view-model renderer that consumes the BFF↔UI OpenAPI contract (`acp-writer/api/bff-openapi.yaml`, PR #127), with a run-centric lifecycle, an in-run care-plan review gate, and a server-authored pipeline progress stepper.

**Architecture:** The UI stops parsing FHIR and stops reading raw LangGraph pipeline state. Instead it renders BFF view-models (`camelCase`) whose TypeScript types are **generated** from the OpenAPI contract. The lifecycle object is `RunDetail`, polled at `GET /runs/{id}` and driven by `RunStatus`; generation progress and care-plan review are two states of the *same* run screen. All work is developed and tested against **MSW mocks** seeded from the contract, so the entire UI is buildable and testable before the BFF exists. End-to-end wiring to the real BFF is a final phase gated on backend work (#124/#126/#129).

**Tech Stack:** React 19, TypeScript ~5.7, PatternFly 6, react-router-dom 7, Vite 6, Vitest + React Testing Library + jsdom (new to this package), MSW (mock service worker), `openapi-typescript` (type codegen).

---

## Background & orientation (read before starting)

**The contract:** `acp-writer/api/bff-openapi.yaml` (merged via PR #127). Screen → endpoint map:

| Screen | Endpoint | Returns |
|---|---|---|
| PatientEntryPage | `POST /runs` `{ipsBundle}` | `RunCreated {runId,status}` (202) |
| RunListPage | `GET /runs?status=&limit=` | `RunSummary[]` |
| RunDetailPage (polled) | `GET /runs/{id}` | `RunDetail` |
| (cancel) | `DELETE /runs/{id}` | 204 |
| CarePlanReview (in-run) | `POST /runs/{id}/review/careplan` `ReviewAction` | `RunDetail` (202) |
| CarePlanList | `GET /careplans` | `CarePlanSummary[]` |
| CarePlanDetail (read-only) | `GET /careplans/{id}` | `CarePlanDetail` |
| SystemStatus | `GET /status` | `SystemStatus` (schema) |

**`RunStatus` is the polling backbone:** `running` → keep polling; `awaiting_careplan_review` → STOP polling, show the review panel; `completed | failed | cancelled` → STOP (terminal). This is why the completion predicate becomes `status !== 'running'` and dovetails with the #125 fetch-loop fix already on this branch.

**What is being deleted from the current UI:**
- `src/types/state.ts` (`CarePlanComposerState` — raw pipeline state is no longer exposed).
- `updateCarePlanStatus()` + `PUT /careplans/{id}/status` (approval is now in-run).
- `src/pages/CarePlanReview.tsx` (approve/reject folds into RunDetailPage; `/careplans/:id` becomes a read-only CarePlanDetail).
- `src/components/ApprovalDialog.tsx` + `src/components/RejectionDialog.tsx` (replaced by an in-run ReviewPanel that submits a `ReviewAction`).
- The `PIPELINE_STEPS` / `stateKey`-null heuristic in `GenerationProgress.tsx` (steps are now server-authored).
- The API-response types at the bottom of `shared/ui/src/types/contracts.ts` (`CarePlanSummary`, `CarePlanStatusUpdate`, `ServiceStatus`) — superseded by generated types. The CPG *domain* mirrors above them (CPGMetadata, Recommendation, Decision*) stay; the ingester UI depends on them.

**Deliberate downgrade (tracked in #128):** `CarePlanView` is a flattened first cut. `PlanGoal` has no target/measure; `PlanActivity` has no dose/route/strength/source labels; `PlanConflict` has no cpg/recommendation lists (only `severity` + `description`). The rewritten cards render *less* than today's FHIR-parsing cards. This is expected.

**Out of scope for this plan:** the client-side SMART launch tab on PatientEntryPage (token exchange + `Patient/$summary` read) — future work tied to #29/#30. The upload path is the only entry path here.

**Blocked-on-backend (Phase 3 only):** the in-run gate (`awaiting_careplan_review`) only fires once the `ReviewCarePlan` SonataFlow Callback state exists (#129), and real data needs the BFF view-model shaping (#124/#126). Phases 0–2 are fully unblocked because everything is developed against MSW.

**Naming clashes to handle in the type-alias layer (Task 0):**
- Contract schema `SystemStatus` vs. the `SystemStatus` page component → alias the schema as `SystemHealth`.
- Contract schema `Error` vs. JS `Error` → alias as `ApiError`.
- Contract schema `PipelineStep` vs. shared/ui's exported `PipelineStep` type → alias as `RunPipelineStep`.
- Contract schema `StepStatus` vs. shared/ui's `StepStatus` → alias as `RunStepStatus`.

**Test command (all tasks):** run from `acp-writer/ui/`: `npm test` (added in Task 1). Typecheck: `npm run typecheck`. Build: `npm run build`.

**Commit discipline:** one commit per task (the final "Commit" step), on branch `worktree-acp-writer-ui`.

---

## File structure (created / modified)

Created:
- `acp-writer/ui/src/api/types.ts` — generated (do not hand-edit)
- `acp-writer/ui/src/api/models.ts` — friendly type aliases over `types.ts`
- `acp-writer/ui/vitest.config.ts`, `acp-writer/ui/src/setupTests.ts`, `acp-writer/ui/src/test/renderWithRouter.tsx`
- `acp-writer/ui/src/mocks/fixtures.ts`, `handlers.ts`, `server.ts`, `browser.ts`
- `acp-writer/ui/src/pipeline/steps.tsx` — `StepKey → {label,icon}` + status adapter
- `acp-writer/ui/src/pages/RunListPage.tsx`, `RunDetailPage.tsx`, `CarePlanDetail.tsx`
- `acp-writer/ui/src/components/ReviewPanel.tsx`
- Test files colocated under `src/**/__tests__/`

Modified:
- `acp-writer/ui/package.json` (scripts + devDeps)
- `acp-writer/ui/src/services/api.ts` (full rewrite)
- `acp-writer/ui/src/components/GoalCard.tsx`, `ActivityCard.tsx`, `ConflictAlert.tsx` (view-model rewrites)
- `acp-writer/ui/src/components/AiReasoningPanel.tsx` (degrade to step details/feedback)
- `acp-writer/ui/src/pages/IpsView.tsx` (→ PatientEntryPage submit path)
- `acp-writer/ui/src/pages/CarePlanList.tsx`, `SystemStatus.tsx` (new shapes)
- `acp-writer/ui/src/routes.tsx`, `App.tsx` (routing + nav)
- `acp-writer/ui/src/main.tsx` (mock worker bootstrap)

Deleted:
- `acp-writer/ui/src/types/state.ts`, `src/pages/CarePlanReview.tsx`, `src/pages/GenerationProgress.tsx`, `src/components/ApprovalDialog.tsx`, `src/components/RejectionDialog.tsx`
- API-response types in `shared/ui/src/types/contracts.ts`

---

# Phase 0 — Type & service backbone (fully unblocked)

### Task 0: Generate types from the contract + friendly aliases

**Files:**
- Modify: `acp-writer/ui/package.json` (add dep + script)
- Create: `acp-writer/ui/src/api/types.ts` (generated)
- Create: `acp-writer/ui/src/api/models.ts`

- [ ] **Step 1: Add the codegen dependency and script**

In `acp-writer/ui/package.json`, add to `devDependencies`:

```json
"openapi-typescript": "^7.4.0"
```

Add to `scripts`:

```json
"gen:api": "openapi-typescript ../api/bff-openapi.yaml -o src/api/types.ts"
```

- [ ] **Step 2: Install and generate**

Run (from `acp-writer/ui/`):

```bash
npm install
npm run gen:api
```

Expected: `src/api/types.ts` is written containing `export interface components { schemas: { RunDetail: {...}, RunStatus: ..., ... } }`.

> If `../api/bff-openapi.yaml` does not exist yet (PR #127 not merged), fetch it first:
> `mkdir -p ../api && git show origin/bff-ui-contract:acp-writer/api/bff-openapi.yaml > ../api/bff-openapi.yaml`

- [ ] **Step 3: Create the friendly alias layer**

Create `acp-writer/ui/src/api/models.ts`:

```ts
// Friendly aliases over the generated OpenAPI types. Import model types from
// here, never reach into components["schemas"] directly in feature code.
// Regenerate types with `npm run gen:api` after the contract changes.
import type { components } from "./types";

type S = components["schemas"];

export type RunStatus = S["RunStatus"];
export type RunCreated = S["RunCreated"];
export type RunSummary = S["RunSummary"];
export type RunDetail = S["RunDetail"];
export type RunError = S["RunError"];
export type RunPipelineStep = S["PipelineStep"]; // clashes with shared/ui PipelineStep
export type RunStepStatus = S["StepStatus"]; // clashes with shared/ui StepStatus
export type StepKey = S["StepKey"];
export type ReviewGate = S["ReviewGate"];
export type ReviewDecision = S["ReviewDecision"];
export type ReviewAction = S["ReviewAction"];
export type FeedbackItem = S["FeedbackItem"];

export type PatientSummary = S["PatientSummary"];
export type CodedItem = S["CodedItem"];

export type PlanGoal = S["PlanGoal"];
export type PlanActivity = S["PlanActivity"];
export type PlanConflict = S["PlanConflict"];
export type CarePlanView = S["CarePlanView"];
export type CarePlanSummary = S["CarePlanSummary"];
export type CarePlanDetail = S["CarePlanDetail"];

export type SystemHealth = S["SystemStatus"]; // schema clashes with the page name
export type ApiErrorBody = S["Error"];
```

- [ ] **Step 4: Verify types resolve**

Run: `npm run typecheck`
Expected: PASS (no references to `models.ts` consumers yet; this just proves `types.ts` + aliases compile).

- [ ] **Step 5: Commit**

```bash
git add acp-writer/ui/package.json acp-writer/ui/src/api/
git commit -m "Add BFF contract type codegen + model aliases"
```

---

### Task 1: Stand up the test harness (Vitest + RTL + jsdom + MSW)

`acp-writer/ui` has no test tooling today. Mirror `shared/ui`'s setup.

**Files:**
- Modify: `acp-writer/ui/package.json`
- Create: `acp-writer/ui/vitest.config.ts`, `src/setupTests.ts`, `src/test/renderWithRouter.tsx`

- [ ] **Step 1: Add test deps and script**

In `acp-writer/ui/package.json` `devDependencies` add:

```json
"@testing-library/jest-dom": "^7.0.1",
"@testing-library/react": "^16.3.2",
"@testing-library/user-event": "^14.5.2",
"jsdom": "^26.0.0",
"msw": "^2.7.0",
"vitest": "^4.1.10"
```

In `scripts` add:

```json
"test": "vitest run",
"test:watch": "vitest"
```

Run: `npm install`

- [ ] **Step 2: Create the Vitest config**

Create `acp-writer/ui/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom", "react-router-dom"],
    alias: { "@app": resolve(__dirname, "src") },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
```

- [ ] **Step 3: Create the setup file (jest-dom + MSW lifecycle)**

Create `acp-writer/ui/src/setupTests.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./mocks/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

> `./mocks/server` is created in Task 2. This file will not compile until then — that is expected; the first green test run happens at the end of Task 2.

- [ ] **Step 4: Create a router-aware render helper**

Create `acp-writer/ui/src/test/renderWithRouter.tsx`:

```tsx
import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// Render `element` mounted at `routePath`, navigated to `initialPath`, so
// hooks like useParams resolve. Defaults render the element at "/".
export function renderWithRouter(
  element: ReactElement,
  { routePath = "/", initialPath = "/" } = {},
) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path={routePath} element={element} />
      </Routes>
    </MemoryRouter>,
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add acp-writer/ui/package.json acp-writer/ui/vitest.config.ts acp-writer/ui/src/setupTests.ts acp-writer/ui/src/test/
git commit -m "Add Vitest + RTL + MSW test harness to acp-writer UI"
```

---

### Task 2: MSW fixtures, handlers, and worker wiring

**Files:**
- Create: `acp-writer/ui/src/mocks/fixtures.ts`, `handlers.ts`, `server.ts`, `browser.ts`
- Modify: `acp-writer/ui/src/main.tsx`

- [ ] **Step 1: Create typed fixtures from the contract**

Create `acp-writer/ui/src/mocks/fixtures.ts`:

```ts
import type {
  CarePlanDetail,
  CarePlanSummary,
  CarePlanView,
  RunDetail,
  RunSummary,
  SystemHealth,
} from "@app/api/models";

const patient = {
  name: "Ada Lovelace",
  birthDate: "1815-12-10",
  gender: "female",
  patientReference: "Patient/ada",
  conditions: [{ display: "Type 2 diabetes mellitus", code: "44054006", system: "http://snomed.info/sct" }],
  medications: [{ display: "Metformin 500 MG" }],
  allergies: [{ display: "Penicillin" }],
  observations: [{ display: "HbA1c 8.2%" }],
};

export const carePlanView: CarePlanView = {
  goals: [
    { id: "g1", description: "Achieve HbA1c < 7%", rationale: "Glycemic control per ADA 2024", sourceCpgId: "ada-2024" },
  ],
  activities: [
    { id: "a1", description: "Metformin 500mg twice daily", goalId: "g1", detail: "Titrate over 4 weeks" },
    { id: "a2", description: "HbA1c recheck in 3 months", goalId: "g1" },
  ],
  conflicts: [
    { id: "c1", severity: "warning", description: "Overlapping recommendation with hypertension CPG on renal dosing." },
  ],
  fhirBundle: { resourceType: "Bundle", type: "transaction", entry: [] },
};

export const runRunning: RunDetail = {
  runId: "run-123",
  status: "running",
  patient,
  steps: [
    { key: "scan_patient", status: "done" },
    { key: "resolve_guidelines", status: "done" },
    { key: "execute_dmn", status: "active" },
    { key: "retrieve_recommendations", status: "pending" },
    { key: "compose_plan", status: "pending" },
    { key: "generate_bundle", status: "pending" },
    { key: "review_fhir", status: "pending" },
    { key: "review_careplan", status: "pending" },
    { key: "write_fhir", status: "pending" },
    { key: "done", status: "pending" },
  ],
  currentSteps: ["execute_dmn"],
  awaitingReview: null,
  carePlan: null,
  reviewIteration: 0,
  previousFeedback: null,
  createdAt: "2026-08-19T15:00:00Z",
  updatedAt: "2026-08-19T15:01:00Z",
};

export const runAwaitingReview: RunDetail = {
  ...runRunning,
  status: "awaiting_careplan_review",
  steps: runRunning.steps!.map((s) =>
    s.key === "review_careplan"
      ? { ...s, status: "active" }
      : s.key === "write_fhir" || s.key === "done"
        ? s
        : { ...s, status: "done" },
  ),
  currentSteps: ["review_careplan"],
  awaitingReview: "careplan",
  carePlan: carePlanView,
  reviewIteration: 0,
  previousFeedback: null,
};

export const runCompleted: RunDetail = {
  ...runRunning,
  status: "completed",
  steps: runRunning.steps!.map((s) => ({ ...s, status: "done" })),
  currentSteps: [],
  awaitingReview: null,
  carePlan: null,
  careplanId: "cp-1",
};

export const runSummaries: RunSummary[] = [
  {
    runId: "run-123",
    status: "running",
    patientName: "Ada Lovelace",
    patientReference: "Patient/ada",
    currentSteps: ["execute_dmn"],
    createdAt: "2026-08-19T15:00:00Z",
    updatedAt: "2026-08-19T15:01:00Z",
  },
  {
    runId: "run-100",
    status: "completed",
    patientName: "Alan Turing",
    patientReference: "Patient/alan",
    currentSteps: [],
    careplanId: "cp-1",
    createdAt: "2026-08-18T09:00:00Z",
    updatedAt: "2026-08-18T09:05:00Z",
  },
];

export const carePlanSummaries: CarePlanSummary[] = [
  {
    id: "cp-1",
    patientName: "Alan Turing",
    patientReference: "Patient/alan",
    status: "active",
    generatedAt: "2026-08-18T09:05:00Z",
    runId: "run-100",
  },
];

export const carePlanDetail: CarePlanDetail = {
  ...carePlanSummaries[0],
  patient,
  view: carePlanView,
};

export const systemHealth: SystemHealth = {
  version: "0.1.0",
  decisionEngine: { available: true, modelsDeployed: 2 },
  knowledgeBase: { available: true, guidelines: 1, recommendations: 12 },
};
```

- [ ] **Step 2: Create the request handlers**

Create `acp-writer/ui/src/mocks/handlers.ts`:

```ts
import { http, HttpResponse } from "msw";
import type { ReviewAction } from "@app/api/models";
import {
  carePlanDetail,
  carePlanSummaries,
  runAwaitingReview,
  runCompleted,
  runRunning,
  runSummaries,
  systemHealth,
} from "./fixtures";

const B = "/api/v1";

export const handlers = [
  http.get(`${B}/runs`, () => HttpResponse.json(runSummaries)),

  http.post(`${B}/runs`, async () =>
    HttpResponse.json({ runId: "run-123", status: "running" }, { status: 202 }),
  ),

  http.get(`${B}/runs/:runId`, ({ params }) => {
    if (params.runId === "run-review") return HttpResponse.json(runAwaitingReview);
    if (params.runId === "run-done") return HttpResponse.json(runCompleted);
    return HttpResponse.json(runRunning);
  }),

  http.delete(`${B}/runs/:runId`, () => new HttpResponse(null, { status: 204 })),

  http.post(`${B}/runs/:runId/review/careplan`, async ({ request }) => {
    const body = (await request.json()) as ReviewAction;
    // approve -> completed; request_changes -> back to running
    return HttpResponse.json(
      body.decision === "approve" ? runCompleted : runRunning,
      { status: 202 },
    );
  }),

  http.get(`${B}/careplans`, () => HttpResponse.json(carePlanSummaries)),
  http.get(`${B}/careplans/:id`, () => HttpResponse.json(carePlanDetail)),
  http.get(`${B}/status`, () => HttpResponse.json(systemHealth)),
];
```

- [ ] **Step 3: Create the node (test) server and browser worker**

Create `acp-writer/ui/src/mocks/server.ts`:

```ts
import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);
```

Create `acp-writer/ui/src/mocks/browser.ts`:

```ts
import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";

export const worker = setupWorker(...handlers);
```

- [ ] **Step 4: Bootstrap the worker in dev behind a flag**

Modify `acp-writer/ui/src/main.tsx` — wrap the render so mocks start first when `VITE_USE_MOCKS` is set. Replace the render call with:

```tsx
async function enableMocking() {
  if (import.meta.env.VITE_USE_MOCKS !== "true") return;
  const { worker } = await import("./mocks/browser");
  await worker.start({ onUnhandledRequest: "bypass" });
}

enableMocking().then(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
```

> Keep the existing imports (`createRoot`, `StrictMode`, `App`, CSS). Only the render invocation is wrapped. Generate the worker script once: `npx msw init public/ --save`.

- [ ] **Step 5: Prove the harness runs with a smoke test**

Create `acp-writer/ui/src/mocks/__tests__/handlers.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { server } from "../server";

describe("msw handlers", () => {
  it("serves run detail", async () => {
    server.listen();
    const res = await fetch("/api/v1/runs/run-123");
    const body = await res.json();
    expect(body.runId).toBe("run-123");
    expect(body.status).toBe("running");
    server.close();
  });
});
```

Run: `npm test`
Expected: PASS. This is the first green run and proves types + MSW + Vitest are wired.

- [ ] **Step 6: Commit**

```bash
git add acp-writer/ui/src/mocks/ acp-writer/ui/src/main.tsx acp-writer/ui/public/
git commit -m "Add MSW fixtures/handlers seeded from the BFF contract"
```

---

### Task 3: Rewrite the API service layer

**Files:**
- Modify: `acp-writer/ui/src/services/api.ts` (full rewrite)
- Delete: `acp-writer/ui/src/types/state.ts`
- Modify: `shared/ui/src/types/contracts.ts` (remove API-response types) + `shared/ui/src/index.ts` if needed
- Test: `acp-writer/ui/src/services/__tests__/api.test.ts`

- [ ] **Step 1: Write the failing test**

Create `acp-writer/ui/src/services/__tests__/api.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import {
  createRun,
  listRuns,
  getRunDetail,
  submitReview,
  listCarePlans,
  getCarePlan,
  getSystemStatus,
} from "../api";

describe("api service", () => {
  it("createRun posts the ips bundle and returns runId", async () => {
    const res = await createRun({ resourceType: "Bundle" });
    expect(res.runId).toBe("run-123");
    expect(res.status).toBe("running");
  });

  it("listRuns returns summaries", async () => {
    const rows = await listRuns();
    expect(rows).toHaveLength(2);
    expect(rows[0].patientName).toBe("Ada Lovelace");
  });

  it("getRunDetail returns the run", async () => {
    const run = await getRunDetail("run-123");
    expect(run.status).toBe("running");
    expect(run.steps?.length).toBe(10);
  });

  it("submitReview approve returns a completed run", async () => {
    const run = await submitReview("run-review", { decision: "approve" });
    expect(run.status).toBe("completed");
  });

  it("listCarePlans and getCarePlan return view-models", async () => {
    expect((await listCarePlans())[0].patientName).toBe("Alan Turing");
    expect((await getCarePlan("cp-1")).view?.goals?.[0].id).toBe("g1");
  });

  it("getSystemStatus returns health", async () => {
    expect((await getSystemStatus()).decisionEngine?.available).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/services/__tests__/api.test.ts`
Expected: FAIL — the new functions don't exist yet (old `api.ts` exports `generateCarePlan`/`updateCarePlanStatus`).

- [ ] **Step 3: Rewrite the service layer**

Replace the entire contents of `acp-writer/ui/src/services/api.ts`:

```ts
import type {
  CarePlanDetail,
  CarePlanSummary,
  RunCreated,
  RunDetail,
  RunStatus,
  RunSummary,
  ReviewAction,
  SystemHealth,
} from "@app/api/models";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

const B = "/api/v1";

// --- Runs ---
export async function createRun(
  ipsBundle: Record<string, unknown>,
): Promise<RunCreated> {
  return request(`${B}/runs`, {
    method: "POST",
    body: JSON.stringify({ ipsBundle }),
  });
}

export async function listRuns(filters?: {
  status?: RunStatus;
  limit?: number;
}): Promise<RunSummary[]> {
  const params = new URLSearchParams();
  if (filters?.status) params.set("status", filters.status);
  if (filters?.limit != null) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return request(`${B}/runs${qs ? `?${qs}` : ""}`);
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  return request(`${B}/runs/${runId}`);
}

export async function cancelRun(runId: string): Promise<void> {
  return request(`${B}/runs/${runId}`, { method: "DELETE" });
}

export async function submitReview(
  runId: string,
  action: ReviewAction,
): Promise<RunDetail> {
  return request(`${B}/runs/${runId}/review/careplan`, {
    method: "POST",
    body: JSON.stringify(action),
  });
}

// --- Care plans (persisted, read-only) ---
export async function listCarePlans(): Promise<CarePlanSummary[]> {
  return request(`${B}/careplans`);
}

export async function getCarePlan(id: string): Promise<CarePlanDetail> {
  return request(`${B}/careplans/${id}`);
}

// --- Status ---
export async function getSystemStatus(): Promise<SystemHealth> {
  return request(`${B}/status`);
}

export async function healthCheck(): Promise<{ status: string }> {
  return request("/health");
}
```

- [ ] **Step 4: Delete the raw-state type**

Run: `git rm acp-writer/ui/src/types/state.ts`

- [ ] **Step 5: Remove the retired API-response types from shared/ui**

In `shared/ui/src/types/contracts.ts`, delete the entire `// --- API response types ---` section (the `CarePlanSummary`, `CarePlanStatusUpdate`, and `ServiceStatus` interfaces at the bottom). Leave everything above it intact.

> `shared/ui/src/index.ts` uses `export * from "./types/contracts"`, so no index edit is needed — the removed types simply stop being exported. Verify no *other* shared consumer imports them: `grep -rn "CarePlanStatusUpdate\|ServiceStatus" shared/ui/src cpg-ingester 2>/dev/null` should return nothing after this change (the writer UI no longer imports them either as of this task).

- [ ] **Step 6: Rebuild shared/ui so the app sees the change**

Run (from `shared/ui/`): `npm run build`
Expected: build succeeds.

- [ ] **Step 7: Run test to verify it passes**

Run (from `acp-writer/ui/`): `npm test src/services/__tests__/api.test.ts`
Expected: PASS (6 tests).

> The app will NOT fully typecheck yet — pages still import the deleted `generateCarePlan`/`state.ts`. That is fixed as each page is migrated in Phase 2. Do not run a full `npm run typecheck` as a gate until Task 16.

- [ ] **Step 8: Commit**

```bash
git add acp-writer/ui/src/services/api.ts shared/ui/src/types/contracts.ts shared/ui/dist
git rm acp-writer/ui/src/types/state.ts
git commit -m "Rewrite API service against BFF contract; drop raw-state types"
```

---

# Phase 1 — Presentational view-model components (unblocked)

### Task 4: GoalCard renders a PlanGoal

**Files:**
- Modify: `acp-writer/ui/src/components/GoalCard.tsx`
- Test: `acp-writer/ui/src/components/__tests__/GoalCard.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `acp-writer/ui/src/components/__tests__/GoalCard.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { GoalCard } from "../GoalCard";

describe("GoalCard", () => {
  it("renders description, rationale, and source", () => {
    render(
      <GoalCard
        goal={{ id: "g1", description: "Achieve HbA1c < 7%", rationale: "Per ADA 2024", sourceCpgId: "ada-2024" }}
      />,
    );
    expect(screen.getByText("Achieve HbA1c < 7%")).toBeInTheDocument();
    expect(screen.getByText("Per ADA 2024")).toBeInTheDocument();
    expect(screen.getByText("ada-2024")).toBeInTheDocument();
  });

  it("omits optional rows when absent", () => {
    render(<GoalCard goal={{ id: "g2", description: "Stop smoking" }} />);
    expect(screen.getByText("Stop smoking")).toBeInTheDocument();
    expect(screen.queryByText("Rationale")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/components/__tests__/GoalCard.test.tsx`
Expected: FAIL — GoalCard still expects a FHIR `GoalResource` (`goal.description.text`).

- [ ] **Step 3: Rewrite GoalCard**

Replace the entire contents of `acp-writer/ui/src/components/GoalCard.tsx`:

```tsx
import {
  Card,
  CardBody,
  CardTitle,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
} from "@patternfly/react-core";
import type { PlanGoal } from "@app/api/models";

export function GoalCard({ goal }: { goal: PlanGoal }) {
  return (
    <Card isCompact>
      <CardTitle>{goal.description}</CardTitle>
      {(goal.rationale || goal.sourceCpgId) && (
        <CardBody>
          <DescriptionList isHorizontal isCompact>
            {goal.rationale && (
              <DescriptionListGroup>
                <DescriptionListTerm>Rationale</DescriptionListTerm>
                <DescriptionListDescription>{goal.rationale}</DescriptionListDescription>
              </DescriptionListGroup>
            )}
            {goal.sourceCpgId && (
              <DescriptionListGroup>
                <DescriptionListTerm>Source guideline</DescriptionListTerm>
                <DescriptionListDescription>{goal.sourceCpgId}</DescriptionListDescription>
              </DescriptionListGroup>
            )}
          </DescriptionList>
        </CardBody>
      )}
    </Card>
  );
}
```

> Note: the old `GoalResource` export is removed. Any importer of `GoalResource` (CarePlanReview) is deleted in Phase 2.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test src/components/__tests__/GoalCard.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add acp-writer/ui/src/components/GoalCard.tsx acp-writer/ui/src/components/__tests__/GoalCard.test.tsx
git commit -m "Rewrite GoalCard to render PlanGoal view-model"
```

---

### Task 5: ActivityCard renders a PlanActivity

**Files:**
- Modify: `acp-writer/ui/src/components/ActivityCard.tsx`
- Test: `acp-writer/ui/src/components/__tests__/ActivityCard.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `acp-writer/ui/src/components/__tests__/ActivityCard.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActivityCard } from "../ActivityCard";

describe("ActivityCard", () => {
  it("renders description and detail", () => {
    render(
      <ActivityCard
        activity={{ id: "a1", description: "Metformin 500mg twice daily", goalId: "g1", detail: "Titrate over 4 weeks" }}
      />,
    );
    expect(screen.getByText("Metformin 500mg twice daily")).toBeInTheDocument();
    expect(screen.getByText("Titrate over 4 weeks")).toBeInTheDocument();
  });

  it("renders without optional detail", () => {
    render(<ActivityCard activity={{ id: "a2", description: "HbA1c recheck in 3 months" }} />);
    expect(screen.getByText("HbA1c recheck in 3 months")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/components/__tests__/ActivityCard.test.tsx`
Expected: FAIL — ActivityCard still expects FHIR `ActivityResource`.

- [ ] **Step 3: Rewrite ActivityCard**

Replace the entire contents of `acp-writer/ui/src/components/ActivityCard.tsx`:

```tsx
import { Card, CardBody, CardTitle } from "@patternfly/react-core";
import { RunningIcon } from "@patternfly/react-icons";
import type { PlanActivity } from "@app/api/models";

export function ActivityCard({ activity }: { activity: PlanActivity }) {
  return (
    <Card isCompact>
      <CardTitle>
        <span style={{ marginRight: "0.5rem" }}>
          <RunningIcon />
        </span>
        {activity.description}
      </CardTitle>
      {activity.detail && <CardBody>{activity.detail}</CardBody>}
    </Card>
  );
}
```

> The FHIR-extension parsing (source-cpg, strength, ai-generated) is intentionally dropped — those fields are not in the flattened `PlanActivity` (tracked in #128).

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test src/components/__tests__/ActivityCard.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add acp-writer/ui/src/components/ActivityCard.tsx acp-writer/ui/src/components/__tests__/ActivityCard.test.tsx
git commit -m "Rewrite ActivityCard to render PlanActivity view-model"
```

---

### Task 6: ConflictAlert renders a PlanConflict

**Files:**
- Modify: `acp-writer/ui/src/components/ConflictAlert.tsx`
- Test: `acp-writer/ui/src/components/__tests__/ConflictAlert.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `acp-writer/ui/src/components/__tests__/ConflictAlert.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConflictAlert } from "../ConflictAlert";

describe("ConflictAlert", () => {
  it("renders description with a severity-mapped variant", () => {
    const { container } = render(
      <ConflictAlert conflict={{ id: "c1", severity: "critical", description: "Renal dosing conflict" }} />,
    );
    expect(screen.getByText("Renal dosing conflict")).toBeInTheDocument();
    expect(container.querySelector(".pf-m-danger")).toBeTruthy();
  });

  it("defaults to a warning variant when severity is absent", () => {
    const { container } = render(
      <ConflictAlert conflict={{ id: "c2", description: "Overlapping recommendation" }} />,
    );
    expect(container.querySelector(".pf-m-warning")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/components/__tests__/ConflictAlert.test.tsx`
Expected: FAIL — old `Conflict` interface has `cpgs`/`recommendations`, not `severity`.

- [ ] **Step 3: Rewrite ConflictAlert**

Replace the entire contents of `acp-writer/ui/src/components/ConflictAlert.tsx`:

```tsx
import { Alert, type AlertProps } from "@patternfly/react-core";
import type { PlanConflict } from "@app/api/models";

const severityToVariant: Record<string, AlertProps["variant"]> = {
  info: "info",
  warning: "warning",
  critical: "danger",
};

export function ConflictAlert({ conflict }: { conflict: PlanConflict }) {
  const variant = severityToVariant[conflict.severity ?? "warning"] ?? "warning";
  return (
    <Alert variant={variant} isInline title="Recommendation conflict">
      <p>{conflict.description}</p>
    </Alert>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test src/components/__tests__/ConflictAlert.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add acp-writer/ui/src/components/ConflictAlert.tsx acp-writer/ui/src/components/__tests__/ConflictAlert.test.tsx
git commit -m "Rewrite ConflictAlert to render PlanConflict view-model"
```

---

### Task 7: Pipeline step metadata map + status adapter

Provides the UI-owned `StepKey → {label, icon}` map and adapts the contract's `StepStatus` vocab to the shared `PipelineStepper`'s vocab. This is the "map at the page boundary" decision — no change to shared/ui yet.

**Files:**
- Create: `acp-writer/ui/src/pipeline/steps.tsx`
- Test: `acp-writer/ui/src/pipeline/__tests__/steps.test.ts`

- [ ] **Step 1: Write the failing test**

Create `acp-writer/ui/src/pipeline/__tests__/steps.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { STEP_LABELS, toPipelineSteps } from "../steps";

describe("pipeline step mapping", () => {
  it("labels every StepKey", () => {
    expect(STEP_LABELS.execute_dmn).toBe("DMN decisions evaluated");
    expect(STEP_LABELS.review_careplan).toBe("Care-plan review");
  });

  it("maps contract steps to shared stepper steps with adapted status", () => {
    const steps = toPipelineSteps([
      { key: "scan_patient", status: "done" },
      { key: "execute_dmn", status: "active" },
      { key: "review_fhir", status: "skipped" },
      { key: "write_fhir", status: "error", detail: "boom" },
    ]);
    expect(steps[0]).toMatchObject({ id: "scan_patient", label: "Patient data scanned", status: "complete" });
    expect(steps[1].status).toBe("running");
    expect(steps[2].status).toBe("pending");
    expect(steps[3]).toMatchObject({ status: "error", duration: "boom" });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/pipeline/__tests__/steps.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the map + adapter**

Create `acp-writer/ui/src/pipeline/steps.tsx`:

```tsx
import type { ReactNode } from "react";
import type { PipelineStep as SharedPipelineStep, StepStatus as SharedStepStatus } from "@cpg-to-acp/ui-shared";
import {
  ClusterIcon,
  ListIcon,
  OutlinedFileAltIcon,
  SearchIcon,
} from "@patternfly/react-icons";
import type { RunPipelineStep, RunStepStatus, StepKey } from "@app/api/models";

// UI-owned label vocabulary. The contract says: UI maps key -> label/icon; do
// not hardcode the step list beyond this shared StepKey vocabulary.
export const STEP_LABELS: Record<StepKey, string> = {
  scan_patient: "Patient data scanned",
  resolve_guidelines: "Guidelines resolved",
  execute_dmn: "DMN decisions evaluated",
  retrieve_recommendations: "Recommendations retrieved",
  compose_plan: "Care plan composed",
  generate_bundle: "FHIR bundle generated",
  review_fhir: "Clinical (FHIR) review",
  review_careplan: "Care-plan review",
  write_fhir: "Written to FHIR server",
  done: "Done",
};

export const STEP_ICONS: Partial<Record<StepKey, ReactNode>> = {
  scan_patient: <SearchIcon />,
  resolve_guidelines: <ListIcon />,
  execute_dmn: <ClusterIcon />,
  generate_bundle: <OutlinedFileAltIcon />,
};

// Contract StepStatus (pending|active|done|error|skipped) -> shared stepper
// vocab (pending|running|complete|error). skipped renders as pending for now;
// aligning the shared enum is a coordinated follow-up.
const STATUS_MAP: Record<RunStepStatus, SharedStepStatus> = {
  pending: "pending",
  active: "running",
  done: "complete",
  error: "error",
  skipped: "pending",
};

export function toPipelineSteps(steps: RunPipelineStep[]): SharedPipelineStep[] {
  return steps.map((s) => ({
    id: s.key,
    label: STEP_LABELS[s.key] ?? s.key,
    status: STATUS_MAP[s.status ?? "pending"] ?? "pending",
    duration: s.detail,
  }));
}
```

> If any icon import name is not exported by `@patternfly/react-icons`, drop it from `STEP_ICONS` — icons are optional and not asserted in the test. `STEP_ICONS` is consumed in Task 12.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test src/pipeline/__tests__/steps.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add acp-writer/ui/src/pipeline/
git commit -m "Add StepKey label/icon map + contract->stepper status adapter"
```

---

# Phase 2 — Pages & routing

### Task 8: SystemStatus page (new shape)

**Files:**
- Modify: `acp-writer/ui/src/pages/SystemStatus.tsx`
- Test: `acp-writer/ui/src/pages/__tests__/SystemStatus.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `acp-writer/ui/src/pages/__tests__/SystemStatus.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithRouter } from "@app/test/renderWithRouter";
import { SystemStatus } from "../SystemStatus";

describe("SystemStatus", () => {
  it("renders BFF-shaped health fields", async () => {
    renderWithRouter(<SystemStatus />);
    await waitFor(() => expect(screen.getByText("0.1.0")).toBeInTheDocument());
    expect(screen.getByText(/2/)).toBeInTheDocument(); // modelsDeployed
    expect(screen.getByText(/12/)).toBeInTheDocument(); // recommendations
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/pages/__tests__/SystemStatus.test.tsx`
Expected: FAIL — current page reads `decision_engine.models` / `knowledge_base` (snake_case) and imports the deleted `ServiceStatus` type.

- [ ] **Step 3: Rewrite the page**

Replace the entire contents of `acp-writer/ui/src/pages/SystemStatus.tsx`:

```tsx
import { useCallback } from "react";
import {
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Label,
  PageSection,
  Title,
} from "@patternfly/react-core";
import { useAdaptivePolling } from "@cpg-to-acp/ui-shared";
import type { SystemHealth } from "@app/api/models";
import { getSystemStatus } from "@app/services/api";

export function SystemStatus() {
  const fetcher = useCallback(() => getSystemStatus(), []);
  const { data: status, error } = useAdaptivePolling<SystemHealth>({
    fetcher,
    isComplete: () => true,
  });

  return (
    <PageSection>
      <Title headingLevel="h1">System Status</Title>
      {error && <p>Failed to load status.</p>}
      {status && (
        <DescriptionList isHorizontal>
          <DescriptionListGroup>
            <DescriptionListTerm>Version</DescriptionListTerm>
            <DescriptionListDescription>{status.version}</DescriptionListDescription>
          </DescriptionListGroup>
          <DescriptionListGroup>
            <DescriptionListTerm>Decision engine</DescriptionListTerm>
            <DescriptionListDescription>
              <Label color={status.decisionEngine?.available ? "green" : "red"}>
                {status.decisionEngine?.available ? "available" : "unavailable"}
              </Label>{" "}
              {status.decisionEngine?.modelsDeployed ?? 0} models deployed
            </DescriptionListDescription>
          </DescriptionListGroup>
          <DescriptionListGroup>
            <DescriptionListTerm>Knowledge base</DescriptionListTerm>
            <DescriptionListDescription>
              <Label color={status.knowledgeBase?.available ? "green" : "red"}>
                {status.knowledgeBase?.available ? "available" : "unavailable"}
              </Label>{" "}
              {status.knowledgeBase?.guidelines ?? 0} guidelines,{" "}
              {status.knowledgeBase?.recommendations ?? 0} recommendations
            </DescriptionListDescription>
          </DescriptionListGroup>
        </DescriptionList>
      )}
    </PageSection>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test src/pages/__tests__/SystemStatus.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add acp-writer/ui/src/pages/SystemStatus.tsx acp-writer/ui/src/pages/__tests__/SystemStatus.test.tsx
git commit -m "Migrate SystemStatus page to SystemHealth view-model"
```

---

### Task 9: CarePlanList page (new shape)

**Files:**
- Modify: `acp-writer/ui/src/pages/CarePlanList.tsx`
- Test: `acp-writer/ui/src/pages/__tests__/CarePlanList.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `acp-writer/ui/src/pages/__tests__/CarePlanList.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithRouter } from "@app/test/renderWithRouter";
import { CarePlanList } from "../CarePlanList";

describe("CarePlanList", () => {
  it("shows patientName and a parsed generatedAt (not 'Invalid Date')", async () => {
    renderWithRouter(<CarePlanList />);
    await waitFor(() => expect(screen.getByText("Alan Turing")).toBeInTheDocument());
    expect(screen.queryByText("Invalid Date")).not.toBeInTheDocument();
    expect(screen.queryByText("Patient/")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/pages/__tests__/CarePlanList.test.tsx`
Expected: FAIL — current page reads `plan.patient_reference` / `plan.generated_at`.

- [ ] **Step 3: Rewrite the page**

Replace the entire contents of `acp-writer/ui/src/pages/CarePlanList.tsx`:

```tsx
import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Label, PageSection, Title } from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import { useAdaptivePolling } from "@cpg-to-acp/ui-shared";
import type { CarePlanSummary } from "@app/api/models";
import { listCarePlans } from "@app/services/api";

const statusColor: Record<string, "blue" | "green" | "red"> = {
  draft: "blue",
  active: "green",
  "entered-in-error": "red",
};

function formatDate(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

export function CarePlanList() {
  const navigate = useNavigate();
  const fetcher = useCallback(() => listCarePlans(), []);
  const { data: plans } = useAdaptivePolling<CarePlanSummary[]>({
    fetcher,
    isComplete: () => true,
  });

  return (
    <PageSection>
      <Title headingLevel="h1">Care Plans</Title>
      <Table aria-label="Care plans">
        <Thead>
          <Tr>
            <Th>Patient</Th>
            <Th>Status</Th>
            <Th>Generated</Th>
            <Th>Actions</Th>
          </Tr>
        </Thead>
        <Tbody>
          {(plans ?? []).map((plan) => (
            <Tr key={plan.id}>
              <Td>{plan.patientName ?? plan.patientReference ?? "Unknown patient"}</Td>
              <Td>
                <Label color={statusColor[plan.status] ?? "blue"}>{plan.status}</Label>
              </Td>
              <Td>{formatDate(plan.generatedAt)}</Td>
              <Td>
                <Button variant="link" onClick={() => navigate(`/careplans/${plan.id}`)}>
                  View
                </Button>
              </Td>
            </Tr>
          ))}
          {plans && plans.length === 0 && (
            <Tr>
              <Td colSpan={4}>No care plans generated yet.</Td>
            </Tr>
          )}
        </Tbody>
      </Table>
    </PageSection>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test src/pages/__tests__/CarePlanList.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add acp-writer/ui/src/pages/CarePlanList.tsx acp-writer/ui/src/pages/__tests__/CarePlanList.test.tsx
git commit -m "Migrate CarePlanList to CarePlanSummary view-model"
```

---

### Task 10: CarePlanDetail page (read-only) + delete CarePlanReview

`/careplans/:id` is now a read-only view of a persisted plan (approval happens in-run). This replaces the old `CarePlanReview` page.

**Files:**
- Create: `acp-writer/ui/src/pages/CarePlanDetail.tsx`
- Delete: `acp-writer/ui/src/pages/CarePlanReview.tsx`
- Test: `acp-writer/ui/src/pages/__tests__/CarePlanDetail.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `acp-writer/ui/src/pages/__tests__/CarePlanDetail.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithRouter } from "@app/test/renderWithRouter";
import { CarePlanDetail } from "../CarePlanDetail";

describe("CarePlanDetail", () => {
  it("renders patient name and goal/activity counts from the view-model", async () => {
    renderWithRouter(<CarePlanDetail />, {
      routePath: "/careplans/:id",
      initialPath: "/careplans/cp-1",
    });
    await waitFor(() => expect(screen.getByText("Alan Turing")).toBeInTheDocument());
    expect(screen.getByText(/Goals \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Activities \(2\)/)).toBeInTheDocument();
    // read-only: no approve/reject buttons
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/pages/__tests__/CarePlanDetail.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the read-only page**

Create `acp-writer/ui/src/pages/CarePlanDetail.tsx`:

```tsx
import { useCallback, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Label,
  PageSection,
  Stack,
  StackItem,
  Tab,
  Tabs,
  TabTitleText,
  Title,
} from "@patternfly/react-core";
import { useAdaptivePolling } from "@cpg-to-acp/ui-shared";
import type { CarePlanDetail as CarePlanDetailModel } from "@app/api/models";
import { getCarePlan } from "@app/services/api";
import { GoalCard } from "@app/components/GoalCard";
import { ActivityCard } from "@app/components/ActivityCard";
import { ConflictAlert } from "@app/components/ConflictAlert";
import { FhirJsonViewer } from "@app/components/FhirJsonViewer";

const statusColor: Record<string, "blue" | "green" | "red"> = {
  draft: "blue",
  active: "green",
  "entered-in-error": "red",
};

export function CarePlanDetail() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState(0);
  const fetcher = useCallback(() => getCarePlan(id!), [id]);
  const { data: plan } = useAdaptivePolling<CarePlanDetailModel>({
    fetcher,
    isComplete: () => true,
    enabled: !!id,
  });

  if (!plan) {
    return (
      <PageSection>
        <Title headingLevel="h1">Loading care plan…</Title>
      </PageSection>
    );
  }

  const view = plan.view ?? {};
  const goals = view.goals ?? [];
  const activities = view.activities ?? [];
  const conflicts = view.conflicts ?? [];

  return (
    <>
      <PageSection>
        <Title headingLevel="h1">Care Plan</Title>
        <div>
          Patient: {plan.patient?.name ?? plan.patientName ?? "Unknown patient"}{" "}
          <Label color={statusColor[plan.status] ?? "blue"}>{plan.status}</Label>
        </div>
      </PageSection>
      <PageSection isFilled>
        <Tabs activeKey={activeTab} onSelect={(_e, key) => setActiveTab(key as number)}>
          <Tab eventKey={0} title={<TabTitleText>Goals ({goals.length})</TabTitleText>}>
            <Stack hasGutter style={{ paddingTop: "1rem" }}>
              {goals.length === 0 ? (
                <StackItem><p>No goals defined.</p></StackItem>
              ) : (
                goals.map((g) => <StackItem key={g.id}><GoalCard goal={g} /></StackItem>)
              )}
            </Stack>
          </Tab>
          <Tab eventKey={1} title={<TabTitleText>Activities ({activities.length})</TabTitleText>}>
            <Stack hasGutter style={{ paddingTop: "1rem" }}>
              {activities.length === 0 ? (
                <StackItem><p>No activities defined.</p></StackItem>
              ) : (
                activities.map((a) => <StackItem key={a.id}><ActivityCard activity={a} /></StackItem>)
              )}
            </Stack>
          </Tab>
          <Tab eventKey={2} title={<TabTitleText>Conflicts ({conflicts.length})</TabTitleText>}>
            <Stack hasGutter style={{ paddingTop: "1rem" }}>
              {conflicts.length === 0 ? (
                <StackItem><p>No conflicts detected.</p></StackItem>
              ) : (
                conflicts.map((c) => <StackItem key={c.id}><ConflictAlert conflict={c} /></StackItem>)
              )}
            </Stack>
          </Tab>
        </Tabs>
        {view.fhirBundle && (
          <div style={{ marginTop: "1rem" }}>
            <FhirJsonViewer json={view.fhirBundle} title="View FHIR Bundle JSON" />
          </div>
        )}
      </PageSection>
    </>
  );
}
```

- [ ] **Step 4: Delete the old review page**

Run: `git rm acp-writer/ui/src/pages/CarePlanReview.tsx`

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test src/pages/__tests__/CarePlanDetail.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add acp-writer/ui/src/pages/CarePlanDetail.tsx acp-writer/ui/src/pages/__tests__/CarePlanDetail.test.tsx
git rm acp-writer/ui/src/pages/CarePlanReview.tsx
git commit -m "Add read-only CarePlanDetail page; remove CarePlanReview"
```

---

### Task 11: RunListPage (new)

**Files:**
- Create: `acp-writer/ui/src/pages/RunListPage.tsx`
- Test: `acp-writer/ui/src/pages/__tests__/RunListPage.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `acp-writer/ui/src/pages/__tests__/RunListPage.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithRouter } from "@app/test/renderWithRouter";
import { RunListPage } from "../RunListPage";

describe("RunListPage", () => {
  it("lists runs with status and current step", async () => {
    renderWithRouter(<RunListPage />);
    await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("DMN decisions evaluated")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/pages/__tests__/RunListPage.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the page**

Create `acp-writer/ui/src/pages/RunListPage.tsx`:

```tsx
import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Label, PageSection, Title } from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import { useAdaptivePolling } from "@cpg-to-acp/ui-shared";
import type { RunSummary } from "@app/api/models";
import { listRuns } from "@app/services/api";
import { STEP_LABELS } from "@app/pipeline/steps";

const statusColor: Record<string, "blue" | "green" | "red" | "grey"> = {
  running: "blue",
  awaiting_careplan_review: "orange" as "blue",
  completed: "green",
  failed: "red",
  cancelled: "grey",
};

export function RunListPage() {
  const navigate = useNavigate();
  const fetcher = useCallback(() => listRuns(), []);
  const { data: runs } = useAdaptivePolling<RunSummary[]>({
    fetcher,
    isComplete: () => true,
  });

  return (
    <PageSection>
      <Title headingLevel="h1">Runs</Title>
      <Table aria-label="Runs">
        <Thead>
          <Tr>
            <Th>Patient</Th>
            <Th>Status</Th>
            <Th>Current step</Th>
            <Th>Actions</Th>
          </Tr>
        </Thead>
        <Tbody>
          {(runs ?? []).map((run) => (
            <Tr key={run.runId}>
              <Td>{run.patientName ?? run.patientReference ?? "Unknown patient"}</Td>
              <Td>
                <Label color={statusColor[run.status] ?? "blue"}>{run.status}</Label>
              </Td>
              <Td>{(run.currentSteps ?? []).map((k) => STEP_LABELS[k] ?? k).join(", ") || "—"}</Td>
              <Td>
                <Button variant="link" onClick={() => navigate(`/runs/${run.runId}`)}>
                  View
                </Button>
              </Td>
            </Tr>
          ))}
          {runs && runs.length === 0 && (
            <Tr>
              <Td colSpan={4}>No runs yet.</Td>
            </Tr>
          )}
        </Tbody>
      </Table>
    </PageSection>
  );
}
```

> `@patternfly/react-core` `Label` `color` prop does not include `"orange"` in its union in some versions; the cast keeps it compiling. If your PatternFly version accepts `"orange"`, drop the cast.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test src/pages/__tests__/RunListPage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add acp-writer/ui/src/pages/RunListPage.tsx acp-writer/ui/src/pages/__tests__/RunListPage.test.tsx
git commit -m "Add RunListPage dashboard"
```

---

### Task 12: RunDetailPage — stepper + polling (part A)

**Files:**
- Create: `acp-writer/ui/src/pages/RunDetailPage.tsx`
- Delete: `acp-writer/ui/src/pages/GenerationProgress.tsx`
- Test: `acp-writer/ui/src/pages/__tests__/RunDetailPage.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `acp-writer/ui/src/pages/__tests__/RunDetailPage.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithRouter } from "@app/test/renderWithRouter";
import { RunDetailPage } from "../RunDetailPage";

describe("RunDetailPage", () => {
  it("renders the server-authored stepper and patient while running", async () => {
    renderWithRouter(<RunDetailPage />, {
      routePath: "/runs/:runId",
      initialPath: "/runs/run-123",
    });
    await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());
    expect(screen.getByText("DMN decisions evaluated")).toBeInTheDocument();
    // running -> no review panel yet
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/pages/__tests__/RunDetailPage.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create RunDetailPage (stepper + polling only for now)**

Create `acp-writer/ui/src/pages/RunDetailPage.tsx`:

```tsx
import { useCallback, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Flex,
  FlexItem,
  PageSection,
  Stack,
  StackItem,
  Title,
} from "@patternfly/react-core";
import { PipelineStepper, useAdaptivePolling } from "@cpg-to-acp/ui-shared";
import type { RunDetail } from "@app/api/models";
import { getRunDetail } from "@app/services/api";
import { toPipelineSteps } from "@app/pipeline/steps";

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [refreshKey, setRefreshKey] = useState(0);

  // fetcher carries runId + refreshKey so submitting a review restarts polling
  // (the run goes back to `running` after request_changes). See #125 fix: a new
  // fetcher identity is the intended restart trigger.
  const fetcher = useCallback(
    () => getRunDetail(runId!),
    [runId, refreshKey],
  );
  const isComplete = useCallback((r: RunDetail) => r.status !== "running", []);
  const { data: run } = useAdaptivePolling<RunDetail>({
    fetcher,
    isComplete,
    enabled: !!runId,
  });

  const steps = useMemo(() => toPipelineSteps(run?.steps ?? []), [run]);

  // Placeholder: the review gate + terminal navigation are wired in part B.
  const restartPolling = () => setRefreshKey((k) => k + 1);
  void navigate;
  void restartPolling;

  if (!run) {
    return (
      <PageSection>
        <Title headingLevel="h1">Loading run…</Title>
      </PageSection>
    );
  }

  return (
    <PageSection>
      <Flex direction={{ default: "column" }} gap={{ default: "gapLg" }}>
        <FlexItem>
          <Title headingLevel="h1">
            Care Plan Run{run.patient?.name ? ` — ${run.patient.name}` : ""}
          </Title>
          <p>Status: {run.status}</p>
        </FlexItem>
        <FlexItem>
          <Stack hasGutter>
            <StackItem>
              <Title headingLevel="h2">Pipeline</Title>
            </StackItem>
            <StackItem>
              <PipelineStepper steps={steps} />
            </StackItem>
          </Stack>
        </FlexItem>
      </Flex>
    </PageSection>
  );
}
```

- [ ] **Step 4: Delete the old generation page**

Run: `git rm acp-writer/ui/src/pages/GenerationProgress.tsx`

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test src/pages/__tests__/RunDetailPage.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add acp-writer/ui/src/pages/RunDetailPage.tsx acp-writer/ui/src/pages/__tests__/RunDetailPage.test.tsx
git rm acp-writer/ui/src/pages/GenerationProgress.tsx
git commit -m "Add RunDetailPage with server-authored pipeline stepper + RunStatus polling"
```

---

### Task 13: ReviewPanel + wire the in-run review gate (part B)

**Files:**
- Create: `acp-writer/ui/src/components/ReviewPanel.tsx`
- Modify: `acp-writer/ui/src/pages/RunDetailPage.tsx`
- Delete: `acp-writer/ui/src/components/ApprovalDialog.tsx`, `RejectionDialog.tsx`
- Test: `acp-writer/ui/src/components/__tests__/ReviewPanel.test.tsx`, extend `RunDetailPage.test.tsx`

- [ ] **Step 1: Write the failing ReviewPanel test**

Create `acp-writer/ui/src/components/__tests__/ReviewPanel.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReviewPanel } from "../ReviewPanel";
import { carePlanView } from "@app/mocks/fixtures";

describe("ReviewPanel", () => {
  it("submits an approve decision", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ReviewPanel carePlan={carePlanView} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ decision: "approve" }));
  });

  it("submits request_changes with a comment", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ReviewPanel carePlan={carePlanView} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: /request changes/i }));
    await userEvent.type(screen.getByLabelText(/overall comment/i), "Tighten the HbA1c target");
    await userEvent.click(screen.getByRole("button", { name: /submit changes/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ decision: "request_changes", comment: "Tighten the HbA1c target" }),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/components/__tests__/ReviewPanel.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create ReviewPanel**

Create `acp-writer/ui/src/components/ReviewPanel.tsx`:

```tsx
import { useState } from "react";
import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FlexItem,
  Stack,
  StackItem,
  TextArea,
  TextInput,
} from "@patternfly/react-core";
import type { CarePlanView, ReviewAction } from "@app/api/models";
import { GoalCard } from "./GoalCard";
import { ActivityCard } from "./ActivityCard";
import { ConflictAlert } from "./ConflictAlert";

interface ReviewPanelProps {
  carePlan: CarePlanView;
  reviewIteration?: number;
  previousFeedback?: ReviewAction | null;
  onSubmit: (action: ReviewAction) => Promise<void>;
}

export function ReviewPanel({
  carePlan,
  reviewIteration,
  previousFeedback,
  onSubmit,
}: ReviewPanelProps) {
  const [mode, setMode] = useState<"idle" | "changes">("idle");
  const [clinician, setClinician] = useState("");
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const goals = carePlan.goals ?? [];
  const activities = carePlan.activities ?? [];
  const conflicts = carePlan.conflicts ?? [];

  const submit = async (action: ReviewAction) => {
    setSubmitting(true);
    try {
      await onSubmit(action);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardTitle>
        Care-plan review{typeof reviewIteration === "number" ? ` — round ${reviewIteration + 1}` : ""}
      </CardTitle>
      <CardBody>
        <Stack hasGutter>
          {previousFeedback?.comment && (
            <StackItem>
              <em>Previously requested:</em> {previousFeedback.comment}
            </StackItem>
          )}
          {conflicts.map((c) => (
            <StackItem key={c.id}><ConflictAlert conflict={c} /></StackItem>
          ))}
          <StackItem>
            <strong>Goals ({goals.length})</strong>
            <Stack hasGutter>
              {goals.map((g) => <StackItem key={g.id}><GoalCard goal={g} /></StackItem>)}
            </Stack>
          </StackItem>
          <StackItem>
            <strong>Activities ({activities.length})</strong>
            <Stack hasGutter>
              {activities.map((a) => <StackItem key={a.id}><ActivityCard activity={a} /></StackItem>)}
            </Stack>
          </StackItem>

          <StackItem>
            <TextInput
              aria-label="Clinician name"
              placeholder="Clinician name"
              value={clinician}
              onChange={(_e, v) => setClinician(v)}
            />
          </StackItem>

          {mode === "changes" && (
            <StackItem>
              <TextArea
                aria-label="Overall comment"
                placeholder="What should change?"
                value={comment}
                onChange={(_e, v) => setComment(v)}
              />
            </StackItem>
          )}

          <StackItem>
            <Flex gap={{ default: "gapSm" }}>
              {mode === "idle" ? (
                <>
                  <FlexItem>
                    <Button
                      variant="primary"
                      isLoading={submitting}
                      isDisabled={submitting}
                      onClick={() =>
                        submit({ decision: "approve", clinician: clinician || undefined })
                      }
                    >
                      Approve
                    </Button>
                  </FlexItem>
                  <FlexItem>
                    <Button variant="secondary" onClick={() => setMode("changes")}>
                      Request changes
                    </Button>
                  </FlexItem>
                </>
              ) : (
                <>
                  <FlexItem>
                    <Button
                      variant="primary"
                      isLoading={submitting}
                      isDisabled={submitting || !comment.trim()}
                      onClick={() =>
                        submit({
                          decision: "request_changes",
                          clinician: clinician || undefined,
                          comment: comment.trim(),
                        })
                      }
                    >
                      Submit changes
                    </Button>
                  </FlexItem>
                  <FlexItem>
                    <Button variant="link" onClick={() => setMode("idle")}>
                      Cancel
                    </Button>
                  </FlexItem>
                </>
              )}
            </Flex>
          </StackItem>
        </Stack>
      </CardBody>
    </Card>
  );
}
```

- [ ] **Step 4: Run the ReviewPanel test**

Run: `npm test src/components/__tests__/ReviewPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Extend the RunDetailPage test for the gate + terminal nav**

Add these cases to `acp-writer/ui/src/pages/__tests__/RunDetailPage.test.tsx` (inside the existing `describe`):

```tsx
  it("shows the review panel when awaiting care-plan review", async () => {
    renderWithRouter(<RunDetailPage />, {
      routePath: "/runs/:runId",
      initialPath: "/runs/run-review",
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument(),
    );
    expect(screen.getByText("Achieve HbA1c < 7%")).toBeInTheDocument();
  });
```

- [ ] **Step 6: Run to verify the new case fails**

Run: `npm test src/pages/__tests__/RunDetailPage.test.tsx`
Expected: FAIL on the new case — the page doesn't render the panel yet.

- [ ] **Step 7: Wire the gate into RunDetailPage**

Edit `acp-writer/ui/src/pages/RunDetailPage.tsx`. Add imports:

```tsx
import { useEffect } from "react";
import type { ReviewAction } from "@app/api/models";
import { submitReview } from "@app/services/api";
import { ReviewPanel } from "@app/components/ReviewPanel";
```

Replace the placeholder block (`const restartPolling = ...; void navigate; void restartPolling;`) with:

```tsx
  // Navigate to the persisted plan once the run completes.
  useEffect(() => {
    if (run?.status === "completed" && run.careplanId) {
      navigate(`/careplans/${run.careplanId}`, { replace: true });
    }
  }, [run?.status, run?.careplanId, navigate]);

  const handleReview = async (action: ReviewAction) => {
    await submitReview(runId!, action);
    // Resume polling: request_changes -> back to running; approve -> terminal.
    setRefreshKey((k) => k + 1);
  };
```

Then, inside the returned JSX, add a review section after the pipeline `FlexItem` (before the closing `</Flex>`):

```tsx
        {run.awaitingReview === "careplan" && run.carePlan && (
          <FlexItem>
            <ReviewPanel
              carePlan={run.carePlan}
              reviewIteration={run.reviewIteration}
              previousFeedback={run.previousFeedback}
              onSubmit={handleReview}
            />
          </FlexItem>
        )}
        {run.status === "failed" && (
          <FlexItem>
            <p style={{ color: "var(--pf-t--global--color--status--danger--default)" }}>
              Run failed{run.error?.message ? `: ${run.error.message}` : "."}
            </p>
          </FlexItem>
        )}
```

- [ ] **Step 8: Delete the old dialogs**

Run: `git rm acp-writer/ui/src/components/ApprovalDialog.tsx acp-writer/ui/src/components/RejectionDialog.tsx`

- [ ] **Step 9: Run the full RunDetailPage + ReviewPanel tests**

Run: `npm test src/pages/__tests__/RunDetailPage.test.tsx src/components/__tests__/ReviewPanel.test.tsx`
Expected: PASS (all cases).

- [ ] **Step 10: Commit**

```bash
git add acp-writer/ui/src/components/ReviewPanel.tsx acp-writer/ui/src/pages/RunDetailPage.tsx acp-writer/ui/src/components/__tests__/ReviewPanel.test.tsx acp-writer/ui/src/pages/__tests__/RunDetailPage.test.tsx
git rm acp-writer/ui/src/components/ApprovalDialog.tsx acp-writer/ui/src/components/RejectionDialog.tsx
git commit -m "Wire in-run care-plan review gate into RunDetailPage"
```

---

### Task 14: PatientEntryPage — submit via createRun

Keep IpsView's client-side IPS preview (it parses the uploaded bundle to show demographics before submit — that is legitimate pre-submit, client-owned). Only the submit path changes.

**Files:**
- Modify: `acp-writer/ui/src/pages/IpsView.tsx`
- Test: `acp-writer/ui/src/pages/__tests__/IpsView.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `acp-writer/ui/src/pages/__tests__/IpsView.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithRouter } from "@app/test/renderWithRouter";
import { IpsView } from "../IpsView";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useNavigate: () => navigateMock,
}));

describe("IpsView", () => {
  it("navigates to the run page after createRun", async () => {
    renderWithRouter(<IpsView />);
    const file = new File(
      [JSON.stringify({ resourceType: "Bundle", entry: [] })],
      "ips.json",
      { type: "application/json" },
    );
    // FileUpload renders a hidden file input
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate care plan/i })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: /generate care plan/i }));
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/runs/run-123"));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/pages/__tests__/IpsView.test.tsx`
Expected: FAIL — page still imports `generateCarePlan` and navigates to `/generate/:run_id`.

- [ ] **Step 3: Update the submit path**

In `acp-writer/ui/src/pages/IpsView.tsx`:

Change the import line:

```tsx
import { generateCarePlan } from "@app/services/api";
```

to:

```tsx
import { createRun } from "@app/services/api";
```

Replace `handleGenerate`:

```tsx
  const handleGenerate = async () => {
    if (!bundle) return;
    setGenerating(true);
    setError(null);
    try {
      const result = await createRun(bundle);
      navigate(`/runs/${result.runId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
      setGenerating(false);
    }
  };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test src/pages/__tests__/IpsView.test.tsx`
Expected: PASS.

> If the FileUpload interaction proves flaky in jsdom, assert the same behavior by calling the component's upload handler directly is not possible (it's internal); instead keep the hidden-input upload approach shown above, which is the supported RTL pattern.

- [ ] **Step 5: Commit**

```bash
git add acp-writer/ui/src/pages/IpsView.tsx acp-writer/ui/src/pages/__tests__/IpsView.test.tsx
git commit -m "PatientEntryPage: submit IPS via createRun -> /runs/:runId"
```

---

### Task 15: Routing + nav + AiReasoningPanel cleanup

**Files:**
- Modify: `acp-writer/ui/src/routes.tsx`, `acp-writer/ui/src/App.tsx`
- Modify: `acp-writer/ui/src/components/AiReasoningPanel.tsx` (only if still referenced) — see note
- Test: `acp-writer/ui/src/__tests__/routes.test.tsx`

- [ ] **Step 1: Write the failing routing test**

Create `acp-writer/ui/src/__tests__/routes.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes } from "@app/routes";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe("AppRoutes", () => {
  it("routes /runs to the run list", async () => {
    renderAt("/runs");
    await waitFor(() => expect(screen.getByText("Runs")).toBeInTheDocument());
  });
  it("routes /careplans to the care plan list", async () => {
    renderAt("/careplans");
    await waitFor(() => expect(screen.getByText("Care Plans")).toBeInTheDocument());
  });
  it("routes /runs/:id to the run detail page", async () => {
    renderAt("/runs/run-123");
    await waitFor(() => expect(screen.getByText(/Care Plan Run/)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test src/__tests__/routes.test.tsx`
Expected: FAIL — routes still point at IpsView/GenerationProgress/CarePlanReview at old paths.

- [ ] **Step 3: Rewrite routes**

Replace the entire contents of `acp-writer/ui/src/routes.tsx`:

```tsx
import { Route, Routes } from "react-router-dom";
import { IpsView } from "@app/pages/IpsView";
import { RunListPage } from "@app/pages/RunListPage";
import { RunDetailPage } from "@app/pages/RunDetailPage";
import { CarePlanList } from "@app/pages/CarePlanList";
import { CarePlanDetail } from "@app/pages/CarePlanDetail";
import { SystemStatus } from "@app/pages/SystemStatus";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<IpsView />} />
      <Route path="/runs" element={<RunListPage />} />
      <Route path="/runs/:runId" element={<RunDetailPage />} />
      <Route path="/careplans" element={<CarePlanList />} />
      <Route path="/careplans/:id" element={<CarePlanDetail />} />
      <Route path="/status" element={<SystemStatus />} />
    </Routes>
  );
}
```

- [ ] **Step 4: Update the nav**

In `acp-writer/ui/src/App.tsx`, replace the `navItems` array:

```tsx
const navItems = [
  { label: "New Care Plan", path: "/", icon: <PlusCircleIcon /> },
  { label: "Runs", path: "/runs", icon: <RunningIcon /> },
  { label: "Care Plans", path: "/plans", icon: <ListIcon /> },
  { label: "System Status", path: "/status", icon: <MonitoringIcon /> },
];
```

with (note `/plans` → `/careplans`, add Runs):

```tsx
const navItems = [
  { label: "New Care Plan", path: "/", icon: <PlusCircleIcon /> },
  { label: "Runs", path: "/runs", icon: <RunningIcon /> },
  { label: "Care Plans", path: "/careplans", icon: <ListIcon /> },
  { label: "System Status", path: "/status", icon: <MonitoringIcon /> },
];
```

Add `RunningIcon` to the `@patternfly/react-icons` import in `App.tsx`.

- [ ] **Step 5: Handle AiReasoningPanel**

`AiReasoningPanel` was only used by the deleted `GenerationProgress`. The contract carries no reasoning transcript (only `steps[].detail` + `previousFeedback`), so the panel has no data source in v1.

Run: `grep -rn "AiReasoningPanel" acp-writer/ui/src`

- If the only remaining references are its own file, delete it: `git rm acp-writer/ui/src/components/AiReasoningPanel.tsx`
- Do not add it to RunDetailPage. (A reasoning field is a proposed contract extension — see the plan's "Contract feedback" note; revisit under #128.)

- [ ] **Step 6: Run test to verify it passes**

Run: `npm test src/__tests__/routes.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add acp-writer/ui/src/routes.tsx acp-writer/ui/src/App.tsx acp-writer/ui/src/__tests__/routes.test.tsx
git rm acp-writer/ui/src/components/AiReasoningPanel.tsx 2>/dev/null || true
git commit -m "Rewire routing/nav to run-centric structure; remove dead AI panel"
```

---

### Task 16: Full sweep — typecheck, build, tests, dev-with-mocks smoke

**Files:** none (verification task)

- [ ] **Step 1: Full typecheck**

Run (from `acp-writer/ui/`): `npm run typecheck`
Expected: PASS with zero errors. If any file still imports a deleted symbol (`generateCarePlan`, `updateCarePlanStatus`, `CarePlanComposerState`, `GoalResource`, `ActivityResource`, old `Conflict`, `ServiceStatus`, `CarePlanStatusUpdate`), fix the importer — every such site should have been migrated in Tasks 3–15.

- [ ] **Step 2: Full test suite**

Run: `npm test`
Expected: PASS — all suites green.

- [ ] **Step 3: Production build**

Run: `npm run build`
Expected: `tsc && vite build` succeeds.

- [ ] **Step 4: Manual smoke against mocks**

Run: `VITE_USE_MOCKS=true npm run dev`, open the app, and verify:
- `/` upload a bundle from `mock-EHR/data/` → click Generate → lands on `/runs/run-123` with the stepper showing "DMN decisions evaluated" active.
- Navigate to `/runs/run-review` directly → the ReviewPanel renders with goals/activities/conflicts and Approve / Request changes.
- Click Approve → run polls, becomes completed, redirects to `/careplans/cp-1` (read-only).
- `/careplans` shows "Alan Turing" and a real date (no "Invalid Date"/"Patient/").
- `/status` shows version + engine/KB health.

Record any deviation as a follow-up; do not fix silently.

- [ ] **Step 5: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "Fix residual type/import issues after BFF re-architecture"
```

---

# Phase 3 — Integration with the real BFF (blocked; do not start until dependencies land)

> **Blocked on:** BFF view-model endpoints (#124 async generate, #126 shaping) and the `ReviewCarePlan` SonataFlow gate (#129). Until then, `awaiting_careplan_review` never fires and `/runs/*` returns nothing. Everything in Phases 0–2 is already proven against mocks.

### Task 17: Point the UI at the real BFF and validate end-to-end

- [ ] **Step 1:** Confirm the deployed BFF serves `/api/v1/*` per the contract (the `servers.url` is `/api/v1`, proxied by nginx to `${BFF_HOST}`). Coordinate the nginx `API_URL`/`BFF_HOST` value with Jaideep (integration seam per the deployment handoff doc).
- [ ] **Step 2:** Run the app without mocks (`npm run dev`, `VITE_USE_MOCKS` unset) against the BFF. Walk the full flow: upload IPS → run progresses → care-plan gate → approve → persisted plan.
- [ ] **Step 3:** Regenerate types if the contract changed since Task 0 (`npm run gen:api`) and re-run `npm run typecheck && npm test`.
- [ ] **Step 4:** File follow-ups for any view-model gaps the real data reveals (candidates: reasoning transcript, richer goal/activity provenance — the #128 extension).

---

## Cross-cutting follow-ups (file as issues; out of scope here)

- **Align `shared/ui` `PipelineStepper` to the contract vocab** — add `skipped`, rename `running/complete → active/done`, support multiple concurrent `currentSteps`. Coordinate with Sam (shared ownership) + Jaideep (ingester UI consumes the stepper). Until then, Task 7's boundary adapter stands.
- **Contract extension #128** — restore goal targets, activity dose/route/strength/source, and conflict cpg/recommendation lists to the view-models; then re-enrich GoalCard/ActivityCard/ConflictAlert.
- **AI transparency** — issue #28 scope lists an AI transparency display, but the contract has no reasoning transcript. Decide whether to add a `reasoning[]`/messages field to `RunDetail` or drop the feature for v1.
- **SMART launch tab** on PatientEntryPage (#29/#30) — client-side token exchange + `Patient/$summary`; the contract already accommodates it via `POST /runs`.
- **npm/pnpm workspaces (#123)** — removes the `resolve.dedupe` band-aid and the double install; do it when next touching the build.

---

## Self-review notes (for the executor)

- **Type consistency:** feature code imports model types **only** from `@app/api/models` (aliases), never from `@app/api/types` directly. Service functions return the aliased types; pages/components consume them.
- **The #125 fetch-loop fix is load-bearing here:** RunDetailPage relies on `fetcher` identity as the intended polling restart trigger (bumping `refreshKey` after a review submit). Do not "optimize" `fetcher` to a stable identity, or request_changes won't resume polling.
- **`isComplete` is inline in several pages (`() => true`)** — safe post-#125 (it's held in a ref in the shared hook). Do not re-introduce a requirement to memoize it.
- **Deliberate downgrades are not bugs:** missing goal targets / activity strength / conflict refs are expected (flattened view-model, #128). Do not "restore" them by parsing `fhirBundle` in the cards — the JSON viewer is the only place raw FHIR is read.
