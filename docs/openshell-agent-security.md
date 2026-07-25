# Agent Security with OpenShell

This document describes how the CPG-to-ACP system uses [NVIDIA OpenShell](https://github.com/NVIDIA/openshell) to enforce per-agent security policies on OpenShift, ensuring that each AI agent can only access the resources it needs.

## Why OpenShell?

This system handles clinical data — patient records, medication decisions, diagnostic information. When AI agents process this data, we need guarantees stronger than "the code doesn't try to exfiltrate." We need enforcement at the kernel level that a compromised or misbehaving agent *cannot* reach endpoints it shouldn't, regardless of what the application code does.

Kubernetes NetworkPolicies operate at the pod network layer, but they can't distinguish between binaries inside a container or audit individual connections. OpenShell provides process-level enforcement: it intercepts every outbound connection, checks it against a declarative policy, and logs the result — allowed or denied — as a structured audit event (OCSF).

The result is a system where the LLM Reasoning agent physically cannot reach the FHIR server, the Patient Data agent cannot reach the LLM, and the Decision Engine can only reach Kogito — all enforced at the kernel level and auditable in the OpenShell gateway logs.

## How It Works

OpenShell runs as a per-namespace gateway that manages sandboxed pods. Each agent pod runs inside an OpenShell sandbox with three layers of enforcement:

- **Landlock filesystem sandbox** — kernel-level restriction on which paths are read-only vs. read-write, preventing agents from modifying system binaries or reading files outside their scope.
- **Network policy engine** — every outbound TCP connection is intercepted and checked against a per-sandbox policy that specifies allowed hosts, ports, and protocols. Connections to unlisted endpoints are denied.
- **Binary identity tracking** — OPA-based enforcement that tracks which binary (e.g., `python3`, `uvicorn`) initiated each connection, enabling policies that restrict specific binaries to specific endpoints.

## Architecture

The system is split into 11 agent pods across two pipelines (cpg-ingester and acp-writer), each running in its own OpenShell sandbox with a tailored security policy.

### Pod-level view

```mermaid
graph TB
    subgraph gateway["OpenShell Gateway"]
        GW[Policy Engine<br/>Audit Logs<br/>Token Auth]
    end

    subgraph cpg["cpg-ingester pipeline"]
        ING[Ingestion<br/><i>Docling PDF parsing</i>]
        LLM1[LLM Analysis<br/><i>Structure, classify,<br/>generate DMN + Recs</i>]
        ASM[Assembly<br/><i>Cross-reference,<br/>integrity checks</i>]
        DEL[Delivery<br/><i>POST to acp-writer</i>]
        UI1[UI<br/><i>Upload + browse</i>]
    end

    subgraph acp["acp-writer pipeline"]
        PAT[Patient Data<br/><i>Condition Scanner</i>]
        LLM2[LLM Reasoning<br/><i>Resolve, retrieve,<br/>compose, review</i>]
        DMN[Decision Engine<br/><i>DMN Executor</i>]
        FHG[FHIR Generation<br/><i>Bundle + validators</i>]
        FHS[FHIR Server<br/><i>Writer + approval</i>]
        UI2[UI<br/><i>Review + approve</i>]
    end

    subgraph infra["Infrastructure"]
        MAAS[MaaS<br/><i>LLM Inference</i>]
        KOG[Kogito<br/><i>Decision Runtime</i>]
        HAPI[HAPI FHIR<br/><i>Patient Data + Care Plans</i>]
        TERM[Terminology APIs<br/><i>SNOMED, RxNorm, LOINC</i>]
    end

    GW -.->|policy + audit| ING
    GW -.->|policy + audit| LLM1
    GW -.->|policy + audit| ASM
    GW -.->|policy + audit| DEL
    GW -.->|policy + audit| PAT
    GW -.->|policy + audit| LLM2
    GW -.->|policy + audit| DMN
    GW -.->|policy + audit| FHG
    GW -.->|policy + audit| FHS

    LLM1 -->|HTTPS 443| MAAS
    LLM2 -->|HTTPS 443| MAAS
    DMN -->|port 8081| KOG
    FHG -->|HTTPS 443| TERM
    FHS -->|port 8080| HAPI
    DEL -->|port 8082| FHS
```

### Network access matrix

Each sandbox policy defines exactly which endpoints the agent can reach. Everything not listed is denied.

```mermaid
graph LR
    subgraph "No External Network"
        ING[Ingestion]
        ASM[Assembly]
        PAT[Patient Data]
    end

    subgraph "LLM Only"
        LLM1[cpg-ingester LLM]
        LLM2[acp-writer LLM]
    end

    subgraph "Specific Service Only"
        DMN[Decision Engine]
        FHG[FHIR Generation]
        FHS[FHIR Server]
        DEL[Delivery]
    end

    LLM1 -->|api.openai.com:443| MAAS((MaaS))
    LLM2 -->|api.openai.com:443| MAAS
    DMN -->|port 8081| KOG((Kogito))
    FHG -->|port 443| TERM((Terminology))
    FHS -->|port 8080| HAPI((HAPI FHIR))
    DEL -->|port 8082| ACP((acp-writer))

    ING -.-x|DENIED| MAAS
    ASM -.-x|DENIED| MAAS
    PAT -.-x|DENIED| MAAS
    PAT -.-x|DENIED| HAPI
    LLM2 -.-x|DENIED| HAPI
```

### Policy details

| Agent Pod | Allowed Network | Denied | Filesystem |
|---|---|---|---|
| **Ingestion** | Gateway only | LLM, FHIR, external | RO: system; RW: /app, /tmp |
| **LLM Analysis** | MaaS (api.openai.com:443) | FHIR server, patient data | RO: system; RW: /app, /tmp |
| **Assembly** | Gateway only | LLM, FHIR, external | RO: system; RW: /app, /tmp |
| **Delivery** | acp-writer API (port 8082) | LLM, FHIR, external | RO: system; RW: /app, /tmp |
| **Patient Data** | Gateway only | LLM, FHIR server, external | RO: system; RW: /app, /tmp |
| **LLM Reasoning** | MaaS (api.openai.com:443) | FHIR server, Kogito | RO: system; RW: /app, /tmp |
| **Decision Engine** | Kogito (port 8081) | LLM, FHIR, external | RO: system; RW: /app, /tmp |
| **FHIR Generation** | Terminology APIs (HTTPS) | LLM, FHIR server, patient data | RO: system; RW: /app, /tmp |
| **FHIR Server** | HAPI FHIR (port 8080) | LLM, patient data, external | RO: system; RW: /app, /tmp |

### Enforcement layers

Each sandbox enforces security through multiple independent mechanisms:

```mermaid
graph TB
    subgraph sandbox["Agent Sandbox"]
        APP[Application<br/><i>uvicorn + FastAPI</i>]
        SUP[OpenShell Supervisor]
        LL[Landlock<br/><i>Filesystem rules</i>]
        NP[Network Policy<br/><i>Endpoint allowlist</i>]
        OPA[OPA<br/><i>Binary identity</i>]
    end

    subgraph external["Outside Sandbox"]
        GW[OpenShell Gateway<br/><i>Token auth, audit</i>]
        K8S[Kubernetes<br/><i>NetworkPolicy</i>]
    end

    APP --> SUP
    SUP --> LL
    SUP --> NP
    SUP --> OPA
    NP -->|allowed| GW
    NP -->|denied + logged| GW
    GW --> K8S

    style LL fill:#e8f5e9
    style NP fill:#fff3e0
    style OPA fill:#e3f2fd
```

1. **Landlock** (kernel) — 17 filesystem rules enforced before the application starts. System directories are read-only; application directories are read-write.
2. **Network Policy** (supervisor) — every TCP connection intercepted. The policy defines which host:port combinations are allowed. Unlisted destinations are denied and logged.
3. **Binary Identity** (OPA) — tracks which executable initiated each connection. Policies can restrict specific binaries to specific endpoints.
4. **Gateway Audit** (OCSF) — all connection events (open, close, deny) are logged as structured OCSF events, visible via `openshell logs <sandbox>`.

## Audit Trail

Every network connection is logged as an OCSF (Open Cybersecurity Schema Framework) event:

```
[ocsf] NET:OPEN [INFO] api.openai.com:443/tcp
[ocsf] NET:CLOSE [INFO] api.openai.com:443/tcp
[ocsf] CONFIG:BUILT [INFO] Landlock ruleset built [rules_applied:17 skipped:0]
[ocsf] CONFIG:CONFIGURED [INFO] OPA runtime binary identity mode configured
```

These logs are collected by the OpenShell gateway and can be forwarded to centralized logging for compliance auditing. Every allowed and denied connection is recorded with the sandbox ID, timestamp, binary path, and destination.

## Deployment Considerations

OpenShell sandboxes isolate workloads in dedicated network namespaces — they are designed for agents that initiate outbound work, not for services receiving inbound requests. Integrating OpenShell with Kubernetes service-mesh-style workloads requires several deployment-level workarounds documented in [`dev_docs/design/openshell-integration-findings.md`](../dev_docs/design/openshell-integration-findings.md).

### Inbound traffic routing

SonataFlow orchestrates calls to pod services via Kubernetes DNS. Since OpenShell sandboxes can't receive inbound traffic directly, an nginx hostname-translation router (`deploy/openshell-router/`) sits between the K8s services and the OpenShell gateway. It rewrites the `Host` header from K8s service names (e.g., `acp-llm-reasoning`) to OpenShell gateway service hostnames (e.g., `sb-llm-reasoning--http.openshell.localhost`), enabling the gateway's loopback HTTP proxy to route requests to the correct sandbox.

### S3-compatible storage

The OpenShell CONNECT proxy handles HTTP GET requests correctly but drops boto3 PUT responses, causing `ProxyConnectionError`. The artifact store uses presigned URLs with `requests.put()` instead of boto3's `put_object()` for all S3 write operations. GET operations remain on boto3.

### Network policy configuration

Three patterns are required for cluster-internal endpoints:

1. **Short hostnames** — The OPA engine matches hostnames literally. Policies must include both short names (`minio`) and FQDN wildcards (`**.svc.cluster.local`) since K8s DNS resolves both forms.

2. **`allowed_ips` CIDR lists** — The proxy blocks RFC 1918 addresses by default (SSRF protection). Cluster-internal endpoints need explicit `allowed_ips` entries with the service CIDR (`172.30.0.0/16`) and pod CIDR (`10.128.0.0/14`).

3. **Port coverage** — Policies must cover all ports the application uses, including SonataFlow callback port (80), MaaS inference port (80 or 443), and MLflow tracing (443 to external hostname).

## Future Direction

- **Per-binary network policies** — restrict specific Python processes to specific endpoints (e.g., only the embedding model binary can reach the vector store).
- **MCP Gateway integration** — combine OpenShell's network-level enforcement with MCP Gateway's application-level tool governance for defense-in-depth.
- **Inference routing** — use OpenShell's built-in inference privacy router to strip caller credentials and inject backend credentials, ensuring agents never see real API keys.
- **Policy Advisor** — enable agents to request additional network access through structured proposals that a human reviews and approves.
- **SPIFFE/SPIRE identity** — replace service account tokens with SPIFFE-based workload identity for cross-cluster agent authentication.

## Further Reading

- [NVIDIA OpenShell Documentation](https://docs.nvidia.com/openshell/)
- [OpenShell GitHub Repository](https://github.com/NVIDIA/openshell)
- [Sandbox Policies Reference](https://docs.nvidia.com/openshell/sandboxes/policies)
- [OCSF (Open Cybersecurity Schema Framework)](https://ocsf.io/)
