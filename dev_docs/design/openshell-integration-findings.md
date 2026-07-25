# OpenShell Integration Findings

Status: **Active workarounds in place** (2026-07-25)
Version: OpenShell 0.0.86 (gateway + supervisor)

## Architecture

OpenShell sandboxes isolate workloads in dedicated Linux network namespaces with Landlock filesystem restrictions and OPA binary identity tracking. All outbound TCP traffic is routed through a CONNECT proxy enforcing declarative YAML policies. OCSF-format audit events log every allowed and denied connection.

Our system deploys 9 service pods inside OpenShell sandboxes, with an nginx hostname-translation router enabling Kubernetes service traffic to reach the sandboxes through the OpenShell gateway's loopback HTTP service.

```
SonataFlow → K8s Service → openshell-router (nginx)
  → rewrites Host header to <sandbox>--http.openshell.localhost
  → proxy_pass to OpenShell gateway
  → gateway proxies to sandbox's inner network namespace
  → uvicorn receives the request
```

## Workarounds

### 1. Inbound traffic routing (openshell-router)

**Problem:** OpenShell sandboxes create isolated network namespaces. Inbound Kubernetes service traffic (from SonataFlow orchestrator) cannot reach the application listening inside the sandbox. This is by design — sandboxes are built for agents that initiate outbound work, not for services receiving inbound requests.

**Workaround:** Deploy an nginx reverse proxy (`deploy/openshell-router/`) that translates K8s service hostnames to OpenShell gateway service hostnames. Patch the 9 service selectors to route through the proxy. The gateway's `enable_loopback_service_http = true` setting proxies HTTP requests to sandbox loopback ports based on the `Host` header pattern `<sandbox>--<service>.openshell.localhost`.

**Files:** `deploy/openshell-router/deploy.yaml`, service selector patches (automated in `deploy/openshell-deploy.sh`)

**Future:** OpenShell mutating webhook or supervisor init container injection would eliminate the router by running the supervisor inside existing deployments. The OpenShell split-pod architecture RFC ([#981](https://github.com/NVIDIA/OpenShell/issues/981)) would also address this.

### 2. S3 PUT via presigned URLs (proxy compatibility)

**Problem:** boto3's S3 `put_object()` fails with `ProxyConnectionError` when going through the OpenShell CONNECT proxy. The proxy forwards the PUT request to MinIO (OCSF shows ALLOWED), but the response is not relayed back to boto3. GET operations work correctly. `curl` and `requests` PUTs also work — the issue is specific to botocore's HTTP connection management.

**Root cause:** Likely a mismatch between botocore's proxy connection pooling/keep-alive behavior and the OpenShell CONNECT proxy's response relay. The proxy auto-detects HTTP traffic and does L7 inspection even for endpoints configured without `protocol`.

**Workaround:** Use `generate_presigned_url()` (boto3 signing, no network call) + `requests.put()` (works through the proxy) instead of `put_object()`. GET operations remain on boto3.

**File:** `shared/src/cpg_contracts/artifact_store.py` — `_put_via_presigned()` method

**Future:** File an issue with OpenShell about botocore proxy compatibility. Once fixed, revert to direct `put_object()`.

### 3. Short hostname matching in policies

**Problem:** The OpenShell OPA engine matches HTTP request hostnames against policy endpoints literally. Applications use short K8s DNS names (`minio`, `cpgingester`) but policies originally specified FQDNs (`minio.sschifma-cpg-to-acp.svc.cluster.local`). The wildcard `**.svc.cluster.local` does not match short names.

**Workaround:** Add both short and FQDN entries to each policy endpoint. For example:
```yaml
minio:
  endpoints:
    - host: "minio"
      port: 9000
    - host: "minio.sschifma-cpg-to-acp.svc.cluster.local"
      port: 9000
```

**Files:** All files in `deploy/openshell-policies/`

**Future:** OpenShell could support DNS-aware matching or automatic FQDN expansion for short names.

### 4. Missing ports and hosts in policies

**Problem:** Three categories of outbound connections were not covered by the initial policies:

| Connection | Port | Used by | Missing from |
|---|---|---|---|
| SonataFlow callbacks | 80 | ingestion, llm-analysis, llm-reasoning, fhir-generation | gateway wildcard only had 8080 |
| MaaS LLM inference | 80 | llm-analysis, llm-reasoning, fhir-generation | LLM policy only had 443 |
| MLflow tracing | 443 | all pods | external hostname not in any policy |

**Workaround:** Added port 80 to gateway wildcards, callback-specific policies with short hostnames, and MLflow external hostname to all policies.

**Files:** All files in `deploy/openshell-policies/`

### 5. L7 inspection breaking S3 signatures (`access: full`)

**Problem:** Setting `access: full` on policy endpoints triggers L7 HTTP inspection, where the proxy inspects and potentially modifies HTTP request headers/body. This breaks AWS v4 signature validation for S3 operations because the signature covers the exact request content.

**Workaround:** Removed `access: full` from all policy endpoints. Without `access` or `protocol`, endpoints use TCP passthrough where the proxy allows the stream without inspecting payloads. Note: the proxy still auto-detects HTTP and logs at L7, but does not modify the stream.

**Files:** All files in `deploy/openshell-policies/`

## What works well

- **Landlock filesystem isolation** — kernel-level enforcement, 17 rules per sandbox
- **OPA binary identity tracking** — per-binary network enforcement
- **OCSF audit logging** — every connection attempt logged with sandbox ID, binary path, destination, policy match
- **Hot-reloadable policies** — `openshell policy set` applies changes to running sandboxes without restart
- **Service exposure** — `openshell service expose` + gateway loopback HTTP proxy works for hostname-based routing
- **MLflow tracing visibility** — OCSF logs show exactly which pods call MLflow and when
- **Unauthorized endpoint blocking** — `config.mlflow-telemetry.io:443` correctly DENIED (not in policy)

## Recommendations for future phases

1. **File OpenShell issues** for botocore proxy compatibility and short-hostname matching
2. **Evaluate supervisor init container injection** when OpenShell adds support — eliminates the nginx router
3. **Move to `enforcement: enforce`** for all policies once audit logs confirm no false positives
4. **Add per-binary restrictions** — restrict which binaries can reach which endpoints (currently `path: "**"` allows all)
5. **Integrate with MCP Gateway** — combine OpenShell's network-level enforcement with MCP's application-level tool governance
