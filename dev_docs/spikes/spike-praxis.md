# Spike: Praxis as Future Inference Gateway

**Date:** 2026-07-20
**Status:** Research complete
**Phase:** 2 (investigation) / 5 (adoption target)

## What Is Praxis?

Praxis is an open-source, Rust-based proxy framework built for AI and cloud-native infrastructure. It uses a composable filter pipeline architecture -- incoming requests flow through a chain of filters (CORS, rate limiting, model extraction, credential injection, routing, load balancing) that can be composed declaratively in configuration.

- **Website:** https://praxis.fast
- **GitHub:** https://github.com/praxis-proxy (10 repos)
- **License:** MIT
- **Current version:** v0.4.0 (released 2026-07-08)
- **Created:** April 2026 (repo history begins 2026-04-01)

AI-specific capabilities (model-aware routing, provider credential injection, LLM request inspection) are developed in a separate repo (`praxis-proxy/ai`), keeping the core proxy generic.

## Who Is Behind It?

Praxis is not officially branded as a Red Hat product, but the evidence is clear:

- Top contributors are Red Hat Senior Principal Engineers: Shane Utt (554 commits), Sebastien Han (86 commits), Brent Salisbury (36 commits), Alex Snaps, Aslak Knutsen.
- The GitHub org is verified with the `praxis.fast` domain.
- The `extproc` repo integrates with Envoy via External Processing, enabling Praxis filter pipelines to run as a sidecar alongside Envoy/Istio -- the same service mesh stack used by OpenShift.
- The `operator` repo implements the Kubernetes Gateway API v1.5.1.

This follows Red Hat's pattern: incubate in open source, later productize (as they did with vLLM becoming Red Hat AI Inference Server, and llm-d for distributed inference).

## What Does It Replace?

| Tool | Relationship to Praxis |
|---|---|
| **LiteLLM** | Direct replacement for LLM routing/gateway. Praxis handles model-aware request routing, per-provider credential injection, and load balancing -- the same core functions we use LiteLLM for locally. |
| **MaaS (OpenShift AI)** | Complementary, not replaced. MaaS is the OpenShift AI governance layer (quotas, API keys, showback). MaaS currently uses Red Hat Connectivity Link as its gateway; Praxis could become an alternative or successor gateway implementation. |
| **OGX/LlamaStack** | Different layer. OGX is an application framework (RAG, agents, tools). Praxis is infrastructure (proxy/routing). They are complementary. |
| **Red Hat Connectivity Link** | Potential overlap. Connectivity Link (based on Kuadrant/Envoy) currently powers MaaS gateway. Praxis could replace or augment it, especially via the `extproc` integration. |

## Current State

- **v0.4.0** (July 2026): 35+ built-in filters, Envoy ExtProc integration, PII detection in guardrails, gRPC support, >=95% test coverage.
- **Kubernetes Operator** exists but has no tagged releases yet (25 commits, early stage).
- **AI repo** (`praxis-proxy/ai`) was created June 30, 2026 -- less than a month old. Updated actively (last push: today).
- **Community:** 58 stars, 48 forks. Small but with heavyweight Red Hat engineering talent.
- **Not production-ready.** No stable release, no Red Hat productization announced, operator is pre-release.

## When Will It Be Production-Ready?

No public roadmap exists. Based on the trajectory:

- The project is ~4 months old with rapid iteration (v0.1 to v0.4 in 3 months).
- The AI-specific repo is less than 1 month old.
- The Kubernetes operator has no releases.
- Red Hat AI 3.4 (current, May 2026) does not include Praxis.
- **Optimistic estimate:** Red Hat AI 3.6 (~Nov 2026) could include Praxis as tech preview, aligning with the project plan's Phase 5 timeline. GA would likely follow in 2027.

## How It Fits This Project

**Phase 1-2 (now):** No action. Continue using LiteLLM locally and MaaS on OpenShift. Both work and are stable.

**Phase 5 (target):** Evaluate Praxis as a replacement for LiteLLM in local dev and as the inference gateway on OpenShift. The filter pipeline architecture adds capabilities we do not get from LiteLLM: PII detection, guardrails, rate limiting, and native Kubernetes Gateway API integration -- all relevant for a clinical data project.

**Migration path:** Praxis exposes an OpenAI-compatible API (model routing inspects the same JSON body format). Switching from LiteLLM should require only configuration changes, not code changes, in `platform/litellm/` and application `litellm_config.yaml`.

## Recommendation

1. **Do not adopt now.** Praxis is pre-production (v0.4, no operator release, AI repo is 3 weeks old). The risk is too high for a project handling clinical data.
2. **Track it.** Watch the `praxis-proxy/ai` and `praxis-proxy/operator` repos for releases. The key milestone is a tagged operator release and appearance in Red Hat AI release notes.
3. **Plan for Phase 5.** When the project reaches Phase 5 (guardrails, evaluation, self-hosted models), re-evaluate Praxis. If it has reached tech preview in Red Hat AI by then, adopt it. If not, continue with MaaS + Connectivity Link on OpenShift and LiteLLM locally.
4. **Architecture is compatible.** No changes are needed now to prepare for Praxis. The OpenAI-compatible API pattern used throughout this project (LiteLLM locally, MaaS on OpenShift) is the same interface Praxis targets.

## Key Links

- https://praxis.fast -- project website
- https://github.com/praxis-proxy/praxis -- core proxy (v0.4.0)
- https://github.com/praxis-proxy/ai -- AI features (no release yet)
- https://github.com/praxis-proxy/operator -- Kubernetes operator (no release yet)
- https://github.com/praxis-proxy/extproc -- Envoy ExtProc integration
