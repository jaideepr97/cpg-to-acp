# Platform Services

Shared infrastructure services that multiple application components consume. These are platform-level dependencies, not application logic.

On OpenShift AI, these are typically platform capabilities that are configured rather than deployed by this project. For local development (podman/kind), this directory contains the deployment artifacts needed to stand up equivalent services locally.

## Services

| Service | Purpose | Phase |
|---|---|---|
| `litellm/` | LiteLLM inference gateway — local stand-in for MaaS, routing to configurable LLM providers | Phase 1 |
| `maas/` | MaaS inference gateway — replaces LiteLLM on OpenShift with enterprise governance | Phase 2 |
| `mlflow/` | MLflow tracing and experiment tracking | Phase 2 |

## LiteLLM (Phase 1)

LiteLLM provides a unified OpenAI-compatible endpoint that proxies requests to an LLM provider. The default configuration uses OpenAI (GPT-5.6). In Phase 2, MaaS replaces LiteLLM on OpenShift — application code should not need to change since both expose the same OpenAI-compatible API.

### Setup

1. Copy `.env.example` to `.env` and add your OpenAI API key:
   ```bash
   cp platform/litellm/deploy/.env.example platform/litellm/deploy/.env
   ```

2. Run via compose (see root `compose.yml`) or standalone:
   ```bash
   cd platform/litellm
   podman build -f deploy/Containerfile -t cpg-litellm .
   podman run -p 4000:4000 --env-file deploy/.env cpg-litellm
   ```

### Test

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"model": "default", "messages": [{"role": "user", "content": "Hello"}]}'
```

### Switching to Claude on Vertex AI

LiteLLM crashes at startup if any configured model has missing credentials, so both providers cannot be in the config simultaneously unless both are configured. To switch to Claude:

1. Edit `platform/litellm/deploy/config.yaml` — replace the model entry:
   ```yaml
   model_list:
     - model_name: default
       litellm_params:
         model: vertex_ai/claude-opus-4-6
         vertex_project: os.environ/VERTEX_PROJECT
         vertex_location: os.environ/VERTEX_LOCATION

   general_settings:
     master_key: os.environ/LITELLM_MASTER_KEY
   ```

2. Update `platform/litellm/deploy/.env`:
   ```
   VERTEX_PROJECT=your-gcp-project-id
   VERTEX_LOCATION=us-east5
   LITELLM_MASTER_KEY=sk-change-me
   ```

3. Set up GCP credentials and add the volume mount to `compose.yml` under the `litellm` service:
   ```yaml
   volumes:
     - ${HOME}/.config/gcloud/application_default_credentials.json:/app/credentials.json:ro
   environment:
     - GOOGLE_APPLICATION_CREDENTIALS=/app/credentials.json
   ```

4. Rebuild: `podman-compose build litellm`

The cpg-ingester CLI uses whichever model is named `default` in the LiteLLM config — no code change needed when switching providers.
