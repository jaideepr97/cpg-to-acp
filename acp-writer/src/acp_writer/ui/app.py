"""FastAPI web UI for acp-writer care plan review and approval.

In pod-split mode, the UI does NOT import pipeline or node code.
All backend interactions happen via HTTP to the API / pod services.
In monolithic mode (API_URL points to local acp-writer), behavior is identical.
"""

import json
import logging
import os
from pathlib import Path

import requests as http_requests
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

app = FastAPI(title="ACP Writer UI")


@app.get("/health")
def health():
    return {"status": "UP", "service": "acp-writer-ui"}


API_URL = os.environ.get("API_URL", "http://localhost:8082")

_pending_runs: dict[str, dict] = {}


def _api_get(path: str) -> dict | list | None:
    try:
        r = http_requests.get(f"{API_URL}{path}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except http_requests.RequestException as e:
        logger.warning("API GET %s failed: %s", path, e)
    return None


def _api_post(path: str, json_data: dict | None = None, data=None, headers=None, timeout=300) -> dict | None:
    try:
        r = http_requests.post(f"{API_URL}{path}", json=json_data, data=data, headers=headers, timeout=timeout)
        if r.status_code in (200, 201):
            return r.json()
        logger.warning("API POST %s returned %d", path, r.status_code)
    except http_requests.RequestException as e:
        logger.warning("API POST %s failed: %s", path, e)
    return None


def _api_put(path: str, json_data: dict) -> dict | None:
    try:
        r = http_requests.put(f"{API_URL}{path}", json=json_data, timeout=30)
        if r.status_code == 200:
            return r.json()
        logger.warning("API PUT %s returned %d", path, r.status_code)
    except http_requests.RequestException as e:
        logger.warning("API PUT %s failed: %s", path, e)
    return None


def _setup_sample_data():
    """Load sample CPG data via API if not already registered."""
    guidelines = _api_get("/api/v1/guidelines")
    if guidelines and len(guidelines) > 0:
        return

    project_root = Path(__file__).parent.parent.parent.parent.parent
    fixtures_file = project_root / "shared" / "tests" / "fixtures" / "sample-recommendations.json"
    if not fixtures_file.exists():
        logger.warning("Sample fixtures not found at %s", fixtures_file)
        return

    data = json.loads(fixtures_file.read_text())

    _api_post("/api/v1/guidelines", json_data=data["metadata"])

    dmn_dir = project_root / "cpg-ingester" / "data" / "golden"
    for f in ["treatment-recommendation.dmn", "monitoring-plan.dmn"]:
        dmn_path = dmn_dir / f
        if dmn_path.exists():
            _api_post(
                "/api/v1/decisions/models",
                data=dmn_path.read_bytes(),
                headers={"Content-Type": "application/xml"},
            )

    _api_post("/api/v1/knowledge/recommendations/batch", json_data=data["recommendation_bundle"])
    logger.info("Loaded sample data via API")


@app.on_event("startup")
async def startup():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    _setup_sample_data()


@app.get("/", response_class=HTMLResponse)
async def submit_page(request: Request):
    guidelines = _api_get("/api/v1/guidelines") or []
    models = _api_get("/api/v1/decisions/models") or []
    status = _api_get("/api/v1/status") or {}
    return templates.TemplateResponse(request, "submit.html", {
        "error": request.query_params.get("error"),
        "guidelines": guidelines,
        "models_deployed": len(models),
        "recs_ingested": status.get("knowledge", {}).get("recommendations", 0),
    })


@app.post("/submit")
async def submit_bundle(request: Request, bundle_file: UploadFile = File(...)):
    content = await bundle_file.read()
    try:
        ips_bundle = json.loads(content)
    except json.JSONDecodeError:
        return templates.TemplateResponse(
            request, "submit.html", {"error": "Invalid JSON file"}, status_code=400
        )

    if ips_bundle.get("resourceType") != "Bundle":
        return templates.TemplateResponse(
            request, "submit.html", {"error": "File must be a FHIR Bundle"}, status_code=400
        )

    import uuid
    run_id = str(uuid.uuid4())[:8]
    _pending_runs[run_id] = {"status": "processing"}

    from threading import Thread
    thread = Thread(target=_generate_via_api, args=(run_id, ips_bundle), daemon=True)
    thread.start()

    return templates.TemplateResponse(request, "processing.html", {"run_id": run_id})


@app.post("/submit-sample")
async def submit_sample(request: Request, sample: str = Form(...)):
    project_root = Path(__file__).parent.parent.parent.parent.parent
    sample_dir = project_root / "mock-EHR" / "data"
    filename = f"patient-bundle-{sample}.json"
    path = sample_dir / filename
    if not path.exists():
        return templates.TemplateResponse(
            request, "submit.html", {"error": f"Sample '{sample}' not found"}, status_code=404
        )

    ips_bundle = json.loads(path.read_text())

    import uuid
    run_id = str(uuid.uuid4())[:8]
    _pending_runs[run_id] = {"status": "processing"}

    from threading import Thread
    thread = Thread(target=_generate_via_api, args=(run_id, ips_bundle), daemon=True)
    thread.start()

    return templates.TemplateResponse(request, "processing.html", {"run_id": run_id})


def _generate_via_api(run_id: str, ips_bundle: dict):
    """Generate a care plan by calling the acp-writer API."""
    try:
        result = _api_post("/api/v1/careplans", json_data=ips_bundle, timeout=600)
        if result and result.get("resourceType") == "Bundle":
            plans = _api_get("/api/v1/careplans") or []
            careplan_id = plans[-1]["id"] if plans else ""
            _pending_runs[run_id] = {"status": "complete", "careplan_id": careplan_id}
            logger.info("Care plan generated via API for run %s -> %s", run_id, careplan_id)
        else:
            _pending_runs[run_id] = {"status": "error", "error": "API returned unexpected response"}
    except Exception as e:
        logger.error("API call failed for run %s: %s", run_id, e)
        _pending_runs[run_id] = {"status": "error", "error": str(e)}


@app.get("/plans/{run_id}/poll")
async def poll_run(run_id: str):
    run = _pending_runs.get(run_id, {})
    if run.get("status") == "complete":
        careplan_id = run.get("careplan_id", "")
        if careplan_id:
            return RedirectResponse(url=f"/ui/plans/{careplan_id}", status_code=303)
    elif run.get("status") == "error":
        return RedirectResponse(url=f"/ui/?error={run.get('error', 'unknown')}", status_code=303)

    return HTMLResponse(
        f'<html><head><meta http-equiv="refresh" content="5;url=/ui/plans/{run_id}/poll">'
        f'</head><body>Still processing run {run_id}...</body></html>'
    )


@app.get("/plans", response_class=HTMLResponse)
async def plans_list(request: Request):
    plans = _api_get("/api/v1/careplans") or []
    return templates.TemplateResponse(request, "plans.html", {"plans": plans})


@app.get("/plans/{careplan_id}", response_class=HTMLResponse)
async def plan_review(request: Request, careplan_id: str):
    cp = _api_get(f"/api/v1/careplans/{careplan_id}")
    if not cp:
        return HTMLResponse("<h1>Care plan not found</h1>", status_code=404)

    bundle = cp.get("bundle", {})
    entries = bundle.get("entry", [])
    resource_types: dict[str, int] = {}
    for entry in entries:
        rt = entry.get("resource", {}).get("resourceType", "unknown")
        resource_types[rt] = resource_types.get(rt, 0) + 1

    brief = None
    for run in _pending_runs.values():
        if run.get("careplan_id") == careplan_id:
            brief = run.get("planning_brief")
            break

    return templates.TemplateResponse(request, "review.html", {
        "plan_id": careplan_id,
        "patient_ref": cp.get("patient_reference", "unknown"),
        "status": cp.get("status", "unknown"),
        "brief": brief,
        "entry_count": len(entries),
        "bundle_type": bundle.get("type", "unknown"),
        "resources": resource_types,
        "fhir_json": json.dumps(bundle, indent=2, default=str),
    })


@app.post("/plans/{careplan_id}/approve")
async def approve(careplan_id: str, clinician: str = Form("")):
    _api_put(
        f"/api/v1/careplans/{careplan_id}/status",
        json_data={"status": "active", "clinician": clinician or "Clinician"},
    )
    return RedirectResponse(url=f"/ui/plans/{careplan_id}", status_code=303)


@app.post("/plans/{careplan_id}/reject")
async def reject(careplan_id: str, reason: str = Form("")):
    _api_put(
        f"/api/v1/careplans/{careplan_id}/status",
        json_data={"status": "entered-in-error", "reason": reason or "No reason provided"},
    )
    return RedirectResponse(url=f"/ui/plans/{careplan_id}", status_code=303)
