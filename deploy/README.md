# Deploying CPG-to-ACP on OpenShift

This guide covers deploying the full CPG-to-ACP system to an OpenShift cluster with MaaS and OpenShell.

## Prerequisites

Before deploying, ensure:

| Prerequisite | How to check |
|---|---|
| `oc` CLI installed and logged in | `oc whoami` |
| `helm` CLI installed | `helm version` |
| `envsubst` available | `which envsubst` (part of `gettext`) |
| `openshell` CLI installed | `openshell --version` |
| OpenShift namespace exists | `oc project <namespace>` |
| OpenShell controller running | `oc get pod openshell-0 -n <namespace>` |
| SonataFlow platform deployed | `oc get pods -l app=sonataflow-platform -n <namespace>` |
| MaaS gateway available | `oc get svc maas-default-gateway-openshift-default -n openshift-ingress` |

## Quick Start

```bash
# 1. Configure (one-time)
cp deploy/config/cluster.env.template deploy/config/cluster.env
# Edit cluster.env: set NAMESPACE, verify MaaS URLs

# 2. Create secrets (one-time)
cp deploy/config/secrets.env.template deploy/config/secrets.env
# Edit secrets.env: set OPENAI_API_KEY, MINIO_ROOT_PASSWORD
./deploy/setup/setup-secrets.sh --from-env deploy/config/secrets.env

# 3. Deploy everything
./deploy/deploy-all.sh
```

## Configuration

### `deploy/config/cluster.env`

Non-secret configuration. Template checked in; actual file gitignored.

| Variable | Description | Example |
|---|---|---|
| `NAMESPACE` | OpenShift project | `sschifma-cpg-to-acp` |
| `MAAS_GATEWAY_URL` | MaaS gateway base URL (bare origin, no `/v1`) | `http://maas-default-gateway-...:80` |
| `MAAS_ROUTE_SEGMENT` | Model path segment on the gateway | `gpt-5-6` |
| `LLM_MODEL_DEFAULT` | Model parameter in API payloads | `gpt-5.6-terra` |
| `ACP_WRITER_LLM_MODEL` | Override model for acp-writer (optional) | |
| `CPG_INGESTER_LLM_MODEL` | Override model for cpg-ingester (optional) | |
| `MLFLOW_TRACKING_URI` | MLflow tracking server | |
| `GIT_REPO` | Git repository for BuildConfigs | |
| `GIT_BRANCH` | Git branch to build from | `main` |

**Important:** All LLM URLs are bare origins/paths. `get_llm()` appends `/v1` automatically. Never include `/v1` in config values (it produces `/v1/v1`, a verified failure).

### Secrets

Secrets are stored in K8s Secrets — never in config files, git, or command-line arguments.

```bash
# Create/update secrets from a local file
./deploy/setup/setup-secrets.sh --from-env deploy/config/secrets.env

# Or interactively
./deploy/setup/setup-secrets.sh --interactive
```

| K8s Secret | Keys | Used by |
|---|---|---|
| `llm-credentials` | `LLM_API_KEY` | LLM-reasoning, llm-analysis, fhir-generation |
| `minio-credentials` | `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `ARTIFACT_STORE_ACCESS_KEY`, `ARTIFACT_STORE_SECRET_KEY` | MinIO, all service pods |
| `fhir-client-credentials` | `FHIR_CLIENT_ID`, `FHIR_CLIENT_SECRET` | fhir-server pod |

**Security notes:**
- `secrets.env` is gitignored and NOT allowlisted in gitleaks
- Helm pods inject secrets via `secretKeyRef` (never plain values in pod specs)
- OpenShell sandboxes receive secrets via `--env` at creation time (documented residual exposure — the values appear in the sandbox environment)
- Anyone with namespace access can read K8s Secrets via `oc get secret`

### Key rotation

```bash
# 1. Update the secret
# Edit secrets.env with the new key value
vi deploy/config/secrets.env
./deploy/setup/setup-secrets.sh --from-env deploy/config/secrets.env

# 2. Restart consumers
acp-writer/deploy/deploy.sh --skip-build    # recreates sandboxes
cpg-ingester/deploy/deploy.sh --skip-build  # recreates sandboxes
```

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

## Security Boundary

OpenShell enforcement covers the 9 sandboxes (5 acp-writer, 4 cpg-ingester). UI, BFF, MCP, decision-service, and mock-EHR pods run without OpenShell egress policies. This is by explicit decision — not an oversight.

## Known Limitations

- OpenShell has no native K8s Secret mounting. Secrets are passed via `--env` at sandbox creation.
- The MaaS ExternalName service (`maas-model-*-backend:443`) does not work from pods (TLS/SNI failure). All traffic uses the MaaS gateway URL.
- `etcd` encryption at rest is not verified for this cluster. K8s Secrets may be stored in plaintext.
