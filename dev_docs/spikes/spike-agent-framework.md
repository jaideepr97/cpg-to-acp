# Spike: Agent Framework Evaluation

**Date:** 2026-07-20
**Status:** Draft
**Context:** Phase 2 spike -- blocks all multi-agent work in Phase 3

## Problem

The CPG-to-ACP system needs a multi-agent framework for Phase 3. In cpg-ingester, multiple agents (filtering, decision identification, DMN writing, recommendation extraction) will form an extraction pipeline. In acp-writer, agents will collaborate on care plan composition with clinician review. The framework must run inside OpenShell sandboxes on OpenShift with MaaS-routed inference and MLflow tracing.

## Evaluation Criteria

| # | Criterion | Weight | Why it matters |
|---|-----------|--------|----------------|
| 1 | OpenShell compatibility | High | Agents run in sandboxes with per-binary network policies; heavy infrastructure is a liability |
| 2 | MCP tool support | High | MCP is the project's standard for tool integration (FHIR, DMN, vector store) |
| 3 | MLflow tracing | Medium | Required for observability; OpenTelemetry bridge is acceptable |
| 4 | Orchestration patterns | Medium | Need sequential pipelines (ingester) and hierarchical delegation (writer) |
| 5 | Community / maturity | Medium | Pre-1.0 is acceptable for a demo; abandoned is not |
| 6 | License | Hard gate | Must be Apache-2.0 compatible |
| 7 | Complexity | Medium | Small team; framework should not dominate the codebase |

## Comparison Matrix

| Criterion | LangGraph | CrewAI | Rookery | AG2 (AutoGen) | BeeAI |
|-----------|-----------|--------|---------|---------------|-------|
| **License** | MIT | MIT | Apache-2.0 | Apache-2.0 | Apache-2.0 |
| **MCP support** | Via adapter lib (v0.3.0) | Native (MCPServerAdapter) | Native (MCP Gateway) | Native (autogen.mcp) | Native (client + server) |
| **MLflow tracing** | Auto (`mlflow.langchain.autolog`) | Auto (`mlflow.crewai.autolog`) | Built-in (observability pillar) | Auto (`mlflow.ag2.autolog`) | Partial -- OTel only, no autolog |
| **Orchestration** | Graph, parallel (Send), supervisor, hierarchical, swarm | Sequential, hierarchical, consensual, Flows | Peer-to-peer messaging, composable workflows | Group chat (5 patterns), sequential, nested | Sequential, hierarchical (HandoffTool), conditional |
| **OpenShell fit** | Feasible but heavy (needs Postgres + Redis for production) | Good -- pure Python, in-process | Designed for Podman/kind/OpenShift tiers | Good -- pure Python, in-process | Poor -- no sandbox docs, Podman issues |
| **Maturity** | v1.2.9, ~32K stars, production-stable | ~54K stars, well-funded, production use | v0.5.1, 30 commits, experimental | v1.0.0b0 (beta), ~4.7K stars | v0.1.81, ~3.3K stars, IBM disclaiming maintenance |
| **Complexity** | High -- graph DSL, state management, LangChain ecosystem | Low-Medium -- role/task abstractions | Medium -- microkernel, 8-pillar architecture | Medium -- conversation patterns, group chat config | Medium -- workflow API, OTel setup |

## Per-Framework Analysis

### LangGraph

The most mature option with the richest orchestration model. Graph-based workflows with typed state, checkpointing, and the `Send` primitive for fan-out/fan-in map well to both the ingester pipeline and writer composition. MLflow auto-instrumentation works via `mlflow.langchain.autolog()`. MCP support is through `langchain-mcp-adapters` (v0.3.0), which is actively maintained but adds a dependency layer.

**Concerns:** LangGraph's production deployment assumes Postgres, Redis, and LangGraph Server -- infrastructure that conflicts with OpenShell's minimal-sandbox model. The LangChain ecosystem creates significant lock-in and frequent breaking changes between minor versions. The graph DSL has a steep learning curve with substantial boilerplate for simple agents. For a demo-stage project, this is over-engineered.

### CrewAI

Role-based agent abstraction with the lowest barrier to entry. Agents are defined with a role, goal, and backstory; tasks chain naturally. Native MCP support and MLflow auto-instrumentation (`mlflow.crewai.autolog`) work out of the box. Runs as pure Python in-process -- no external services needed for core orchestration.

**Concerns:** Four CVEs disclosed in 2026 (RCE, SSRF, file read -- all mitigated). Async tracing not captured by MLflow integration. Hierarchical mode adds non-determinism. Community consensus is that CrewAI is better for prototyping than production -- teams often migrate to LangGraph later. For a demo that may evolve, this is a risk.

### Rookery

Sam's own microkernel "operating system" for multi-agent systems. Designed around standards composition (A2A, MCP, AG-UI, OpenTelemetry) with swappable drivers behind a narrow interface. MCP is native via an MCP Gateway. MLflow is a built-in observability driver. Explicitly designed for three deployment tiers (Podman, kind, OpenShift) using the same Helm charts. Tag-based model routing (light/medium/heavy) aligns with MaaS. Institutional memory seeding from documents supports CPG context injection. Apache 2.0 with a CI check guarding against copyleft dependencies.

**Concerns:** Experimental -- 30 commits, zero community adoption outside the author. No production validation. Documentation is architectural rather than tutorial. Choosing your own framework for your own project creates a bootstrap dependency: framework bugs block application development.

### AG2 (AutoGen)

The community fork of Microsoft's AutoGen, now under active development with a clear path to v1.0. Rich orchestration via Group Chat with five patterns (default, auto, round-robin, random, manual). MCP client support is first-class. MLflow auto-instrumentation via `mlflow.ag2.autolog()`. Runs as pure Python in-process. Apache 2.0 license.

**Concerns:** The AutoGen-to-AG2 transition created ecosystem confusion (multiple PyPI packages, dual API surfaces). The conversation-based paradigm means multi-agent interactions are inherently chatty and token-expensive -- a concern for clinical data processing where cost and latency matter. Still in beta (v1.0.0b0). The framework's strength (multi-agent debate) is not a primary pattern for this project's extraction pipelines.

### BeeAI

IBM-originated, now under Linux Foundation governance. Native MCP support (client and server) and Apache 2.0 license. The A2A/ACP protocol for agent-to-agent communication is forward-looking.

**Concerns:** IBM has explicitly disclaimed ongoing maintenance obligations. No MLflow autolog -- observability is OpenTelemetry-to-Arize-Phoenix, requiring manual bridging to MLflow. No OpenShell documentation or sandboxing model. Known Podman compatibility issues. The recommended `RequirementAgent` is still in an experimental import path. Despite IBM owning Red Hat, BeeAI and Red Hat AI operate as separate initiatives with no documented integration. Red Hat's own agent-frameworks evaluation treats BeeAI as one of many candidates with no preference.

## Recommendation

**Primary: LangGraph** -- with a lightweight deployment model (skip LangGraph Server; use in-process graphs with SQLite checkpointing).

**Rationale:**

1. **Best orchestration fit.** The cpg-ingester pipeline maps directly to a sequential graph with conditional branching. The acp-writer composition maps to a supervisor pattern with human-in-the-loop interrupts for clinician review. LangGraph supports both natively.

2. **MLflow integration is production-grade.** Auto-instrumentation via `mlflow.langchain.autolog()` captures every node execution as a trace span with token usage and cost -- no manual wiring.

3. **MCP integration is proven.** The `langchain-mcp-adapters` library (v0.3.0, 30 releases) handles MCP tool conversion, multi-server connections, and all transport types.

4. **OpenShell is workable.** Skip the Postgres/Redis/Server stack. Use LangGraph as a library with `MemorySaver` (dev) or SQLite checkpointer (production-lite). The Python process runs inside the OpenShell sandbox; outbound connections are allowlisted per the existing `target-policy.yaml` pattern.

5. **Community and longevity.** v1.2.9, ~32K stars, weekly releases, enterprise adoption. If the project outgrows a demo, LangGraph scales.

6. **License.** MIT is Apache-2.0 compatible.

**Why not the others:**

- **CrewAI** -- lower barrier but weaker long-term trajectory. Good for a quick prototype, but if Phase 3 agents grow in complexity, CrewAI's abstractions become limiting. The CVE history suggests less rigorous security review.
- **Rookery** -- architecturally aligned (OpenShift-native, MCP-native, MLflow-native) but too early. Consider revisiting if Rookery reaches v1.0 with community adoption. Using it now creates a single-person dependency across both the framework and the application.
- **AG2** -- rich orchestration but the conversation-based paradigm is a poor fit for extraction pipelines. The token cost of multi-agent chat is unnecessary when agents have well-defined sequential handoffs.
- **BeeAI** -- the IBM maintenance disclaimer and lack of MLflow/OpenShell integration make it unsuitable. The "Red Hat adjacent" positioning is aspirational, not actual.

## Migration Path

If LangGraph proves too heavy during implementation, the fallback is CrewAI for rapid prototyping with a plan to revisit at Phase 5. The MCP tool contracts are framework-agnostic by design (defined in `shared/`), so switching frameworks does not require rewriting tool implementations.

## Next Steps

1. Prototype the cpg-ingester pipeline as a LangGraph `StateGraph` with 4 nodes (filter, identify, write-DMN, extract-recommendations)
2. Verify MLflow tracing captures the full graph execution on the OpenShift cluster
3. Confirm the in-process deployment model works inside an OpenShell sandbox
4. Document the pattern in `cpg-ingester/README.md` for reuse in acp-writer
