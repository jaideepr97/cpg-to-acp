# Spike: Artifact Store for SonataFlow State Transfer

**Date:** 2026-07-22
**Status:** In progress
**Branch:** `feature/phase3.3-integration-governance`

## Problem

SonataFlow orchestrates the acp-writer pipeline across 5 pods. The workflow accumulates state as a single JSON object — patient bundle, recommendations, DMN results, planning brief — passing it through every HTTP call. By the compose step, the accumulated payload exceeds the Vert.x HTTP client connection limit (~64KB default), causing `HttpClosedException: Connection was closed`.

This was anticipated in the implementation notes ("State transfer: full state in each REST call — optimize later if payload size is a problem"). The problem is now real.

## Decision

Deploy MinIO as an S3-compatible artifact store. Pods store large payloads and pass references (S3 keys) through the SonataFlow workflow. Each pod fetches what it needs.

### Why MinIO

| Option | Pros | Cons |
|---|---|---|
| **MinIO** | S3-compatible, lightweight (1 pod), boto3 SDK, works on any K8s | Extra pod to manage |
| AWS S3 native | Managed service, no pod | Requires IAM setup, AWS-specific |
| Shared PVC (EFS) | Simple file I/O | EFS CSI driver not installed, gp3 is RWO only |
| Redis | Fast key-value | Not standard for large artifacts, needs serialization |
| Increase Vert.x limit | No new infrastructure | Doesn't scale, just pushes the limit |

MinIO is the standard artifact store pattern on Kubernetes. It's S3-compatible, so the code works identically against AWS S3 in production.

## Cluster State

- **Cloud:** AWS ROSA, us-east-2
- **Storage:** gp3-csi (EBS, default), no ODF/NooBaa
- **Existing object stores:** None (MLflow uses local filesystem)
- **Python SDK:** `boto3` available via pip, or `minio` package

## Design

### Artifact key format

```
s3://cpg-artifacts/{workflow_id}/{step_name}.json
```

Example:
```
s3://cpg-artifacts/e2e-test-1721671200/scan_result.json
s3://cpg-artifacts/e2e-test-1721671200/resolve_result.json
s3://cpg-artifacts/e2e-test-1721671200/retrieve_result.json
s3://cpg-artifacts/e2e-test-1721671200/compose_result.json
s3://cpg-artifacts/e2e-test-1721671200/fhir_bundle.json
```

### What stays inline vs gets stored

| Data | Size | Store? | Why |
|---|---|---|---|
| `patient_reference` | ~30B | Inline | Tiny string |
| `condition_codes` | ~500B | Inline | Small array of codes |
| `medication_codes` | ~300B | Inline | Small array |
| `allergy_codes` | ~100B | Inline | Small array |
| `ips_bundle` | ~7KB | **Store** | Full FHIR Bundle, only needed by scan + execute |
| `applicable_cpgs` | ~2KB | Inline | List of CPG metadata |
| `applicable_dmn_models` | ~1KB | Inline | List of model summaries |
| `dmn_results` | ~2KB | Inline | Decision outputs |
| `recommendations` | ~15-50KB | **Store** | Full recommendation text, biggest payload |
| `planning_brief` | ~5-10KB | **Store** | LLM-generated structured plan |
| `fhir_bundle` | ~10-30KB | **Store** | Generated FHIR Bundle |
| Review counters/feedback | ~100B | Inline | Control flow data |

### Integration pattern

Each pod-split service accepts either:
- **Direct payload:** `{"recommendations": [...]}` — works as today (local mode)
- **Artifact reference:** `{"recommendations_ref": "s3://cpg-artifacts/run123/retrieve_result.json"}` — fetches from MinIO

The pod checks for `_ref` suffixed fields. If present, it fetches from the artifact store before processing. Output is stored to the artifact store and a `_ref` is returned.

```python
# Shared utility: shared/src/cpg_contracts/artifact_store.py
class ArtifactStore:
    def __init__(self, endpoint_url, bucket="cpg-artifacts"):
        self.client = boto3.client("s3", endpoint_url=endpoint_url)
        self.bucket = bucket

    def put(self, key: str, data: dict) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=json.dumps(data).encode())
        return f"s3://{self.bucket}/{key}"

    def get(self, ref: str) -> dict:
        bucket, key = ref.replace("s3://", "").split("/", 1)
        obj = self.client.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read().decode())
```

### SonataFlow workflow changes

The workflow jq expressions change to pass references:

```yaml
# Before (full payload):
arguments:
  recommendations: "${ .recData.recommendations }"

# After (reference):
arguments:
  recommendations_ref: "${ .recData.recommendations_ref }"
```

### MinIO deployment

Single pod, single PVC (2Gi gp3-csi), ClusterIP Service on port 9000.

```yaml
# deploy/mcp-gateway/minio.yaml (or deploy/platform/minio.yaml)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: minio
spec:
  containers:
    - name: minio
      image: quay.io/minio/minio:latest
      args: ["server", "/data"]
      env:
        - name: MINIO_ROOT_USER
          value: minioadmin
        - name: MINIO_ROOT_PASSWORD
          valueFrom:
            secretKeyRef: ...
      volumeMounts:
        - name: data
          mountPath: /data
```

## Scope

### Spike (verify)

- [ ] Deploy MinIO on OpenShift
- [ ] Verify put/get from a pod (Python boto3)
- [ ] Measure actual payload sizes for each pipeline step

### Implementation

- [ ] Create `shared/src/cpg_contracts/artifact_store.py` — put/get utility
- [ ] Update pod-split services to support `_ref` fields
- [ ] Update SonataFlow workflow YAML — pass references for large payloads
- [ ] Test full SonataFlow E2E with artifact store

## References

- [MinIO on Kubernetes](https://min.io/docs/minio/kubernetes/upstream/)
- [boto3 S3 client](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html)
- [SonataFlow state management](https://sonataflow.org/serverlessworkflow/latest/core/understanding-workflow-data.html)
