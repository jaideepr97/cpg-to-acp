# Deploying CPG-to-ACP on OpenShift

This guide covers deploying the full CPG-to-ACP system to an OpenShift cluster with MaaS and OpenShell.

## Prerequisites

Before deploying, ensure:

| Prerequisite | How to check |
|---|---|
| `oc` CLI installed and logged in | `oc whoami` |
| `helm` CLI installed | `helm version` |
| `envsubst` available | `which envsubst` (part of `gettext`) |
| `python3` available | `python3 --version` |
| `podman` installed (for mock-EHR image push) | `podman --version` |
| `openshell` CLI installed | `openshell --version` |
| MaaS gateway available | `oc get svc maas-default-gateway-openshift-default -n openshift-ingress` |

**Namespace name constraint:** the namespace name plus Helm release prefixes form Route hostnames, which are subject to a 63-character DNS label limit. The longest prefix is `cpg-mock-ehr-medplum-server-` (28 chars), so **keep namespace names under 35 characters**.

## MaaS Setup

MaaS (Model as a Service) provides governed LLM inference on OpenShift AI. The steps below are **platform-level setup outside the scope of this project** — they must be completed before deploying cpg-to-acp. Work with your cluster administrator or platform team as needed.

### 1. Get your namespace whitelisted

The MaaS gateway enforces namespace-level authorization — pods in non-whitelisted namespaces receive 403 responses. Request whitelisting from your platform team, providing:
- The namespace name (e.g. `my-team-cpg-to-acp`)
- The models you need access to (e.g. `gpt-5.6-terra`)

### 2. Create the provider API key secret

The `ExternalProvider` (next step) references a K8s Secret containing your upstream LLM provider's API key. Create it before applying the ExternalProvider CR:

```bash
oc create secret generic llm-credentials \
  --from-literal=LLM_API_KEY=<your-openai-api-key> \
  -n <your-namespace>
```

> **Note:** The cpg-to-acp deploy framework also creates this same `llm-credentials` secret via `setup-secrets.sh`. If you run `setup-secrets.sh` first (step 4 in the Quick Start below), this step is already done. Either way, the secret must exist before the ExternalProvider CR is applied.

### 3. Create an ExternalProvider

An `ExternalProvider` CR defines the upstream LLM provider (e.g. OpenAI, Azure OpenAI). Created once per provider in your namespace.

```yaml
apiVersion: maas.redhat.com/v1alpha1
kind: ExternalProvider
metadata:
  name: openai
  namespace: <your-namespace>
spec:
  url: https://api.openai.com/v1
  authType: bearer
  credentialsRef:
    name: llm-credentials    # K8s Secret created in step 2
    key: LLM_API_KEY
```

### 4. Create an ExternalModel

An `ExternalModel` CR registers a specific model through the provider, making it available on the MaaS gateway.

```yaml
apiVersion: maas.redhat.com/v1alpha1
kind: ExternalModel
metadata:
  name: gpt-5-6-terra
  namespace: <your-namespace>
spec:
  providerRef:
    name: openai              # references the ExternalProvider above
  model: gpt-5.6-terra        # model name sent to the upstream provider
  routeSegment: gpt-5-6       # URL path segment on the MaaS gateway
```

The `routeSegment` determines the URL path on the MaaS gateway. Note that it differs from the `model` parameter (dashes vs dots) — this is a MaaS convention.

### 5. Create a ModelRef (optional)

A `ModelRef` creates a namespace-scoped alias for the model, enabling model governance policies and usage tracking.

```yaml
apiVersion: maas.redhat.com/v1alpha1
kind: ModelRef
metadata:
  name: default-llm
  namespace: <your-namespace>
spec:
  modelRef:
    name: gpt-5-6-terra       # references the ExternalModel above
```

### 6. Verify MaaS access

```bash
# Check the MaaS gateway service exists
oc get svc maas-default-gateway-openshift-default -n openshift-ingress

# Check your ExternalModel status
oc get externalmodel -n <your-namespace>

# Test inference (from a pod in your namespace, or via port-forward)
curl -X POST \
  http://maas-default-gateway-openshift-default.openshift-ingress.svc.cluster.local:80/<route-segment>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "<model-name>", "messages": [{"role": "user", "content": "Hello"}]}'
```

Replace `<route-segment>` with the `routeSegment` from your ExternalModel (e.g. `gpt-5-6`) and `<model-name>` with the model parameter (e.g. `gpt-5.6-terra`).

Once MaaS is verified, set the gateway URL and model in `deploy/config/cluster.env` (see [Configuration](#configuration) below):

```bash
MAAS_GATEWAY_URL=http://maas-default-gateway-openshift-default.openshift-ingress.svc.cluster.local:80
MAAS_ROUTE_SEGMENT=gpt-5-6
LLM_MODEL_DEFAULT=gpt-5.6-terra
```

> **Port 80, not 443:** The MaaS gateway serves on port 80 (HTTP). The cpg-to-acp OpenShell network policies allow both ports 80 and 443 for LLM inference traffic. If you encounter connection failures from sandboxed pods, verify the port in your gateway URL matches the actual service port.

## Quick Start

```bash
# 1. Configure (one-time)
cp deploy/config/cluster.env.template deploy/config/cluster.env
# Edit cluster.env: set NAMESPACE, CLUSTER_DOMAIN, verify MaaS URLs

# 2. Create namespace
oc new-project <namespace>

# 3. Provision OpenShell + SonataFlow (one-time per namespace, requires cluster-admin)
./deploy/setup/setup-openshell.sh --config deploy/config/cluster.env

# 4. Create secrets (one-time)
cp deploy/config/secrets.env.template deploy/config/secrets.env
# Edit secrets.env: set OPENAI_API_KEY, MINIO_ROOT_PASSWORD, optionally Medplum creds
./deploy/setup/setup-secrets.sh --from-env deploy/config/secrets.env

# 5. Set up shared infrastructure (MinIO, router, MCP gateway)
./deploy/setup/setup-namespace.sh --config deploy/config/cluster.env

# 6. Deploy all components
./deploy/deploy-all.sh --config deploy/config/cluster.env

# 7. Verify
./deploy/verify-all.sh --config deploy/config/cluster.env --e2e
```

## Configuration

### `deploy/config/cluster.env`

Non-secret configuration. Template checked in; actual file gitignored.

| Variable | Description | Example |
|---|---|---|
| `NAMESPACE` | OpenShift project (max 35 chars) | `sschifma-cpg-to-acp` |
| `CLUSTER_DOMAIN` | Cluster domain for Route hostnames | `apps.rosa.agentic-mcp.jolf.p3.openshiftapps.com` |
| `MAAS_GATEWAY_URL` | MaaS gateway base URL (bare origin, no `/v1`) | `http://maas-default-gateway-...:80` |
| `MAAS_ROUTE_SEGMENT` | Model path segment on the gateway | `gpt-5-6` |
| `LLM_MODEL_DEFAULT` | Model parameter in API payloads | `gpt-5.6-terra` |
| `ACP_WRITER_LLM_MODEL` | Override model for acp-writer (optional) | |
| `CPG_INGESTER_LLM_MODEL` | Override model for cpg-ingester (optional) | |
| `MLFLOW_TRACKING_URI` | MLflow tracking server | |
| `GIT_REPO` | Git repository for BuildConfigs | |
| `GIT_BRANCH` | Git branch to build from | `main` |
| `BUILD_TIMEOUT` | Build timeout in seconds (default 1200 = 20 min) | `1200` |

**Important:** All LLM URLs are bare origins/paths. `get_llm()` appends `/v1` automatically. Never include `/v1` in config values (it produces `/v1/v1`, a verified failure).

### Secrets

Secrets are stored in K8s Secrets — never in config files, git, or command-line arguments.

```bash
# Create/update secrets from a local file
./deploy/setup/setup-secrets.sh --from-env deploy/config/secrets.env

# Or interactively
./deploy/setup/setup-secrets.sh --interactive
```

| K8s Secret | Keys | Created by | Used by |
|---|---|---|---|
| `llm-credentials` | `LLM_API_KEY` | `setup-secrets.sh` | LLM-reasoning, llm-analysis, fhir-generation |
| `minio-credentials` | `MINIO_ROOT_USER/PASSWORD`, `ARTIFACT_STORE_ACCESS/SECRET_KEY` | `setup-secrets.sh` | MinIO, all service pods |
| `fhir-client-credentials` | `FHIR_CLIENT_ID`, `FHIR_CLIENT_SECRET` | `setup-secrets.sh` (optional) | fhir-server pod |
| `medplum-user-credentials` | `MEDPLUM_SUPERADMIN_PASSWORD`, `MEDPLUM_ADMIN_EMAIL/PASSWORD`, `MEDPLUM_PRACTITIONER_PASSWORD` | `setup-secrets.sh` (optional) | mock-EHR loader job |
| `smart-client-credentials` | `smart-config.json` (JSON with clientId/clientSecret) | mock-EHR loader job | IPS Viewer (mounted as file) |

**Security notes:**
- `secrets.env` is gitignored and NOT allowlisted in gitleaks
- Helm pods inject secrets via `secretKeyRef` (never plain values in pod specs)
- OpenShell sandboxes receive secrets via `--env` at creation time (documented residual exposure — the values appear in the sandbox environment)
- Anyone with namespace access can read K8s Secrets via `oc get secret`

### Key rotation

Rotating a secret (e.g. the OpenAI API key) is a two-step process. There is no single command — OpenShell sandboxes bake secret values into their environment at creation time, so they must be recreated to pick up new values.

```bash
# 1. Update the K8s Secret
vi deploy/config/secrets.env                # edit the value(s) you're rotating
./deploy/setup/setup-secrets.sh --from-env deploy/config/secrets.env

# 2. Recreate sandboxes to pick up the new values
#    --skip-build avoids rebuilding images (only the secrets changed)
#    --tag <sha> must match the currently deployed image tag
acp-writer/deploy/deploy.sh --skip-build --tag <current-sha>
cpg-ingester/deploy/deploy.sh --skip-build --tag <current-sha>
```

**Why both steps are needed:**
- Helm pods use `secretKeyRef` and pick up new Secret values on pod restart (the deploy scripts trigger a rollout).
- OpenShell sandboxes receive secrets via `--env` at creation time. The old sandbox keeps the old value until it is deleted and recreated. `deploy.sh` tears down and recreates all sandboxes automatically.
- mock-EHR pods generally don't consume LLM/MinIO secrets directly, so they don't need restarting for most key rotations. If you rotated MinIO credentials, also re-run `mock-EHR/deploy/deploy.sh --skip-build --tag <sha>`.

## Deploying Components

### Deploy everything

```bash
./deploy/deploy-all.sh [--skip-build] [--skip-openshell] [--tag <sha>]
```

### Deploy one component

```bash
# Each component deploys independently
acp-writer/deploy/deploy.sh [--skip-build] [--skip-openshell] [--tag <sha>]
cpg-ingester/deploy/deploy.sh [--skip-build] [--skip-openshell] [--tag <sha>]
mock-EHR/deploy/deploy.sh [--skip-build] [--tag <sha>]
```

### Rollback

```bash
# Deploy a previous commit (one flag, no rebuild needed)
acp-writer/deploy/deploy.sh --skip-build --tag <old-sha>
```

## Image Tagging

Images are tagged with the git SHA (`git rev-parse --short HEAD`). Mutable tags (`:phase3`, `:latest`) are not used in deploy paths.

- `imagePullPolicy: Always` in all templates
- Override with `--tag <sha>` on any deploy command
- ImageStream tags are pruned to the last 5 SHAs per image
- **Never use `--skip-build` without `--tag`** — without `--tag`, IMAGE_TAG defaults to git HEAD, which may not match the built images (e.g. after a deploy-script-only commit). This causes `ImagePullBackOff`.

### `--skip-openshell` mode

By default, sandboxed pods run under OpenShell with security policies. Passing `--skip-openshell` to a component deploy script sets `openshellMode=false` in the Helm chart, which renders standard Kubernetes Deployments instead of OpenShell sandboxes. Services select the pods directly (not the openshell-router). Use this for environments without OpenShell.

## Teardown

```bash
# Remove one component
acp-writer/deploy/teardown.sh
cpg-ingester/deploy/teardown.sh
mock-EHR/deploy/teardown.sh

# Remove everything (components + shared infrastructure)
./deploy/teardown-all.sh --infra

# Full wipe (removes ImageStreams AND K8s Secrets — typed confirmation required)
./deploy/teardown-all.sh --full-wipe

# Full wipe without confirmation (for automation)
./deploy/teardown-all.sh --full-wipe --yes
```

Routine teardown preserves K8s Secrets and ImageStreams so you don't need to re-enter API keys or rebuild images on the next deploy. Only `--full-wipe` removes secrets.

### Cluster-scoped resources

`setup-openshell.sh` creates a ClusterRole and ClusterRoleBinding named `<namespace>-openshell-tokenreview`. These are **cluster-scoped**: deleting the namespace does *not* remove them. `teardown-all.sh --full-wipe` deletes them; if you delete a namespace without running `--full-wipe` first, clean them up manually:

```bash
oc delete clusterrolebinding <namespace>-openshell-tokenreview
oc delete clusterrole <namespace>-openshell-tokenreview
```

## Component Ownership

Each component owns its deployment:

```
acp-writer/deploy/
├── chart-pods/           # Helm chart
├── pods/                 # Containerfiles
├── orchestrator/         # SonataFlow workflow
├── openshell/
│   ├── deploy.sh         # OpenShell sandbox management
│   ├── policies/         # Security policies
│   └── router-fragment.conf.tmpl  # nginx routing fragment
├── setup-images.sh       # ImageStreams + BuildConfigs
├── deploy.sh             # Full component deploy
├── verify.sh             # Post-deploy verification
└── teardown.sh           # Component teardown
```

A change to cpg-ingester's pods or policies touches zero files in acp-writer's tree.

The shared `deploy/` directory contains only:
- Config templates and secrets setup
- Shared helpers (`lib.sh`)
- Namespace infrastructure (MinIO, openshell-router, MCP gateway)
- Top-level orchestrators (thin loops over component scripts)

## Deploy Order

The recommended order is: mock-EHR → acp-writer → cpg-ingester.

This order ensures services are available when their consumers start. However, **any order must work** — connections are made lazily at request time, not at startup. If a component fails to start because a sibling is absent, that is a bug.

## Resource Footprint

| Component | Pods | CPU request | Memory request |
|---|---|---|---|
| acp-writer (+ decision-service) | ~8 | ~2.5 | ~3 Gi |
| cpg-ingester | ~7 | ~1.5 | ~4.5 Gi |
| mock-EHR | ~5 | ~1.5 | ~2.5 Gi |
| Shared infra | ~6 | ~1 | ~2 Gi |
| **Total** | **~26** | **~6.5 CPU** | **~12 Gi** |

Build resources: cpg-ingester ingestion image needs 2 CPU / 8Gi (Docling model download).

## OpenShell Port-Forward

The `openshell` CLI needs a port-forward to the controller:

```bash
oc port-forward pod/openshell-0 18080:8080 -n <namespace> &
```

The deploy scripts manage this automatically via `lib.sh`. The port-forward is left running on exit (harmless, avoids churn).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `sleep infinity` instead of uvicorn | Command not passed correctly to sandbox | Ensure `sh -c "$command"` pattern (fixed in current scripts) |
| 502 through openshell-router | Sandbox not supervised / router config stale | Re-run component `openshell/deploy.sh`; check router ConfigMap |
| `command not found` in sandbox | zsh word-splitting | Scripts include `SH_WORD_SPLIT` shim |
| Build fails with OOM | Insufficient BuildConfig resources | Ingestion: 2 CPU / 8Gi; others: 1 CPU / 2Gi |
| Stale image after deploy | Mutable tag + IfNotPresent | Use SHA tags (default); `imagePullPolicy: Always` |
| `/v1/v1` in LLM URL | Config value ends with `/v1` | Remove `/v1` — `get_llm()` appends it |
| OpenShell policy denial | Short hostname doesn't match `**.svc.cluster.local` | Use FQDNs in all service URLs |
| `oc exec curl localhost:8080` returns 000 | Supervised process runs in sandbox namespace | Use routed path (via openshell-router), not localhost |
| Route hostname >63 chars | Namespace name too long | Keep namespace names under 35 characters |
| `ImagePullBackOff` after `--skip-build` | IMAGE_TAG defaulted to HEAD, not the built tag | Always pass `--tag <sha>` with `--skip-build` |
| BFF upload returns 404 | BFF in mock mode (`minio:false` or `sonataflow:false`) | Check `MINIO_ENDPOINT` and `SONATAFLOW_URL` in chart values |
| Parse completes but workflow stays in "parsing" | SonataFlow props CM missing → `/wait-parse` returns 404 | Verify props CM applied: `oc get cm cpgingester-props` |
| `nginx -t` fragment validation fails | Bad `server_name` in router fragment (e.g. empty `${NAMESPACE}`) | Check `envsubst` — variables must be exported (`set -a` in `load_config`) |

## Security Boundary

OpenShell enforcement covers the 9 sandboxes (5 acp-writer, 4 cpg-ingester). UI, BFF, MCP, decision-service, and mock-EHR pods run without OpenShell egress policies. This is by explicit decision — not an oversight.

## Loading Published Artifacts

After cpg-ingester publishes artifacts (DMN models, recommendations, guideline metadata) to MinIO, they must be loaded into acp-writer before care plan generation can use them. The delivery/notification flow is not yet wired; use the temporary helper:

```bash
./deploy/load-published-artifacts.sh --config deploy/config/cluster.env <cpg-id>
# Example: ./deploy/load-published-artifacts.sh --config deploy/config/cluster.env UNK-HTN-UNDATED
```

This loads the guideline metadata, recommendations (into the vector store), and DMN models (into the decision engine) from `cpg-artifacts/published/<cpg-id>/` in MinIO.

## SonataFlow Workflow Configuration

Each workflow (cpg-ingester and acp-writer) requires a **props ConfigMap** that maps CloudEvent channels to HTTP callback endpoints (e.g. `mp.messaging.incoming.parse-done.path=/wait-parse`). Without these, async workflow steps complete but their callbacks are rejected with 404, and the workflow stalls.

The deploy scripts apply these automatically (`cpgingester-props.yaml` and `acpwriter-props.yaml` in each component's `orchestrator/` directory). If you deploy a workflow manually, apply its props CM first.

## Known Limitations

- OpenShell has no native K8s Secret mounting. Secrets are passed via `--env` at sandbox creation.
- The MaaS ExternalName service (`maas-model-*-backend:443`) does not work from pods (TLS/SNI failure). All traffic uses the MaaS gateway URL.
- `etcd` encryption at rest is not verified for this cluster. K8s Secrets may be stored in plaintext.
- **Delivery/notification not wired:** cpg-ingester publishes artifacts to MinIO but does not notify acp-writer. Use `deploy/load-published-artifacts.sh` as a stopgap.
- **mock-EHR Docker Hub base images:** `mock-EHR/ui/Containerfile` and `mock-EHR/ips-viewer/Containerfile` still pull from Docker Hub (`node:22-alpine`, `nginxinc/nginx-unprivileged:alpine`). These are subject to rate limits on shared cluster egress IPs. cpg-ingester's UI has been migrated to UBI base images; mock-EHR migration is pending.

## Test Coverage

The framework was validated on virgin namespaces (August 2026): full setup sequence, single-shot `deploy-all.sh` (exit 0, zero manual actions), `verify-all.sh --e2e` (all checks including a DMN + LLM QA round trip), component teardown, `teardown-all.sh --infra` (zero orphans), and `--full-wipe` including cluster-scoped RBAC cleanup. The full application flow was exercised end-to-end: CPG upload → published artifacts → loaded into acp-writer → DMN-driven care plan → SMART launch in mock-EHR.

The following paths are **documented but have not been exercised** — expect rough edges on first use:

| Untested path | Notes |
|---|---|
| `teardown-all.sh --full-wipe --yes` (non-interactive) | The `--yes` propagation to component scripts was fixed after test 3 but not re-run |
| `--skip-openshell` mode | Helm-managed pods instead of OpenShell sandboxes |
| Rollback (`--skip-build --tag <old-sha>`) | Mechanism is the same as a normal skip-build deploy, but never run against a prior SHA |
| Key rotation end-to-end | Both steps work individually; the full rotate-and-verify sequence hasn't been run |
| `setup-secrets.sh --interactive` | Only `--from-env` has been used |
| Single-component update | Changing one component and verifying the others are untouched |
| Non-admin deploy | All testing ran with cluster-admin; a least-privilege role has not been derived |
