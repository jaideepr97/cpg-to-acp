# acp-writer React UI — deployment handoff

Point-in-time handoff (2026-08-17) for integrating the acp-writer React/PatternFly UI
into the deployment framework (PR #122). Written for Jaideep, who owns the
pod-split migration + BFF. Khaled continues on pure UI work.

## TL;DR

- PR #25 (`worktree-acp-writer-ui`) is now **rebased onto the framework base** and
  trimmed to the **React UI component only** — all monolith-era deploy artifacts we
  had added were removed (superseded by PR #122).
- The framework's `ui` pod today is the **Jinja UI** (`Containerfile.ui` runs
  `acp_writer.ui.app:app`). Integration = **swap that seam to serve the React SPA**,
  pointed at the BFF.
- Two files are left in place for **you to decide on** (see "Judgment calls").

## Current state of the React UI

Deployed and exercised end-to-end against a monolith backend on the cluster
(now torn down). What we observed:

- **Works:** app renders, routing, theme toggle; **IPS upload + client-side parsing**
  (demographics, conditions, meds, vitals) is solid; Care Plans list; review page shell.
- **Verified pipeline round-trip:** upload → generate → DMN + LLM + adversarial review
  loops → 29-resource FHIR bundle (graceful FHIR-write fallback with no Medplum).
- **Known bugs (filed):**
  - #124 — generation does a **blocking POST** that runs the whole pipeline; the
    OpenShift route times out at ~30s → 504 (pipeline still finishes server-side).
    **BFF-owned:** belongs in an async job API (the UI already has a
    `GenerationProgress` page + `useAdaptivePolling` hook scaffolded for this).
  - #126 — review shows **Goals(0)/Activities(0)**, "Unknown patient"; list shows
    "Patient/" + "Invalid Date". The API returns `{id, bundle(FHIR), status,
    patient_reference, server_ids}` — no `planning_brief`. **BFF-owned contract
    decision:** return a UI view-model (brief/goals) or have the UI parse FHIR.
  - #125 — `CarePlanReview` **infinite fetch loop** (`ERR_INSUFFICIENT_RESOURCES`);
    a `useEffect`/polling dependency bug. **UI-owned** (Khaled).
  - #123 — adopt npm workspaces to replace the `resolve.dedupe` band-aid. **UI/shared-owned.**

## Integration seam

The framework builds a `ui` pod (`acp-writer-ui` image from
`acp-writer/deploy/pods/Containerfile.ui`, currently the Jinja app) and deploys it
via `chart-pods` behind the openshell-router. To serve the React UI instead:

1. Build the React SPA image (see "UI packaging").
2. Point the `ui` pod at that image (replace/augment `Containerfile.ui`), or add a
   `react-ui` pod alongside it.
3. Wire the SPA's `/api` + `/health` proxy (nginx `${API_URL}`) at the **BFF**, not a
   monolith. The nginx config is already env-driven — just set `API_URL`.

## UI packaging (facts you'll need)

- **Monorepo dep:** `acp-writer/ui` depends on `@cpg-to-acp/ui-shared` via
  `file:../../shared/ui`. The image must mirror the repo layout for that to resolve.
  Our `acp-writer/ui/Containerfile` builds from a **repo-root context** for this reason
  (mirrors how the backend Containerfile works).
- **`resolve.dedupe`** (in `vite.config.ts`) for `react`/`react-dom`/`react-router-dom`
  is **required** — without it the `file:` dep pulls a second react-router-dom copy and
  `AppShell`'s `useLocation()` crashes the app (blank page). Proper fix is workspaces (#123).
- **nginx** serves the SPA and proxies `location /api/` + `/health` to `${API_URL}`
  (envsubst at startup). Port 8080 (nginx-unprivileged).
- **Docker Hub bases:** the UI Containerfile uses `node:22-alpine` +
  `nginxinc/nginx-unprivileged:alpine`. These are the **same Docker Hub images the
  framework README flags as rate-limited and pending UBI migration** for mock-EHR.
  Expect to migrate these to UBI for reliable cluster builds.

## Migration-requirements checklist (what we had to wire for the monolith)

Use this to confirm each concern is covered in the framework, or port what isn't:

| What acp-writer needed | Status in framework (PR #122) |
|---|---|
| LLM env (`LITELLM_URL`/`LLM_MODEL`/`LLM_API_KEY`) | ✅ mapped to MaaS gateway in `deploy.sh` |
| Sample-data seeding | ✅ replaced by `deploy/load-published-artifacts.sh` (MinIO) |
| NetworkPolicy DNS (`kube-system` → `openshift-dns`) | ❓ verify `chart-pods` netpol allows OpenShift DNS (framework tested e2e, likely fine) |
| Pipeline blocking the event loop (we used `run_in_threadpool` in the monolith) | ❓ check the split `llm-reasoning`/`fhir-generation` services for the same async-handler-runs-blocking-work pattern |
| Health-probe path (litellm `/health` → 401) | ⚪ moot — no LiteLLM pod (MaaS) |
| React UI: dedupe + repo-root Containerfile | ➡️ carry into integration |
| React UI Docker Hub bases → UBI | ⚠️ pending, same as mock-EHR |
| Async generate (#124) + view-model shaping (#126) | ➡️ **BFF** |

## Judgment calls (your decision — we left them in place)

We deliberately did **not** delete these; decide whether they have a home:

- **`compose.acp-dev.yml`** (repo root) — a lightweight local (podman) stack:
  acp-writer monolith + LiteLLM + Kogito, no EHR. It was our local inner loop (bring up
  a backend, run `vite dev` against it). AGENTS.md now says local dev uses `compose.yml`
  (the full stack). Question: keep `compose.acp-dev.yml` as a lighter local-UI loop, fold
  its intent into `compose.yml`, or drop it? (Related: the lightweight-profile spike #119.)
- **`acp-writer/ui/deploy/acp-dev.yaml`** — a standalone Deployment/Service/Route for the
  React UI wired to a monolith backend service. Superseded by your `chart-pods` `ui` pod,
  but documents the UI's runtime shape (nginx SPA, `API_URL`, port 8080, edge route).
  Keep as reference, or delete once the `chart-pods` seam serves the SPA?

## What we removed (and why)

Dropped from this PR (all superseded by PR #122): our `setup-openshift.sh` scripts,
monolith `chart/` edits, `platform/litellm` chart edits, and the `values-dev.yaml`
files (monolith/kogito/litellm). The framework's config-driven approach
(`cluster.env` + secrets + SHA tags) replaces them.
