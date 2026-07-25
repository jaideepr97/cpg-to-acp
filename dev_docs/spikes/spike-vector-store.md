# Spike: Vector Store Selection for acp-writer

## Context

acp-writer needs a vector store to index and search clinical recommendations ingested from cpg-ingester. The store must support hybrid search (metadata filters + vector similarity) and integrate with OpenShift deployment.

Scale: 100-1,000 recommendations per CPG, potentially multiple CPGs. Quality of semantic search matters more than throughput.

## Evaluation Criteria

1. Hybrid search: metadata filters (source_cpg, recommendation_type, strength) combined with vector similarity
2. Semantic search quality with clinical text
3. OpenShift deployment readiness
4. Operational complexity
5. Python async integration (acp-writer is FastAPI)
6. Production maturity

## Options Evaluated

### PostgreSQL + pgvector

**Version:** pgvector 0.8.5 (July 2026), requires PostgreSQL 15+

**Hybrid search:** Full SQL WHERE + vector similarity in a single query. At <1,000 vectors, sequential scan gives exact results (100% recall) with sub-millisecond latency — no index needed.

```sql
SELECT id, content, embedding <=> $1::vector AS distance
FROM recommendations
WHERE source_cpg = 'SYN-HTN-2026-001'
  AND recommendation_type = 'treatment'
ORDER BY embedding <=> $1::vector
LIMIT 10;
```

**OpenShift:** Crunchy PostgreSQL Operator (PGO 6.0.2) is OpenShift Certified Level 5 with pgvector 0.8.0 bundled in standard images. No custom build needed — just `CREATE EXTENSION vector;`.

**Python:** `pgvector` (0.5.0) + SQLAlchemy 2.0 async + `asyncpg` (0.31.0). Native SQLAlchemy column type `Vector(dims)` with cosine/L2/inner product operators.

**Distance functions:** Cosine (`<=>`), L2 (`<->`), inner product (`<#>`), L1 (`<+>`).

**Dimensions:** Up to 2,000 for `vector` (32-bit), 4,000 for `halfvec` (16-bit).

**Indexing:** HNSW and IVFFlat available. For <1,000 vectors: skip indexing entirely — sequential scan is faster and gives exact results.

**Production maturity:** PostgreSQL heritage — full ACID, WAL replication, PITR. Used in production by Supabase, AWS RDS/Aurora, Google Cloud SQL.

### Milvus

**Version:** 2.6.x stable, 3.0 RC

**Deployment modes:** Milvus Lite (embedded, `pip install pymilvus`, zero infra), Standalone (container), Distributed (Kubernetes). Lite → Standalone → Cluster uses the same API.

**Hybrid search:** Native `filter` parameter with boolean expressions.

**OpenShift:** Official operator + Helm chart available.

**Production maturity:** CNCF graduated project. Purpose-built for vector search.

**Trade-off:** Additional infrastructure service. For <1,000 vectors, Milvus Lite works but adds a dependency with no benefit over pgvector.

### ChromaDB

**Version:** 1.5.9 (Rust-core rewrite)

**Hybrid search:** Dict-based `where` filters with `$and`/`$or`/`$gt`/`$eq`.

**OpenShift:** No official Helm chart or operator — requires manual manifests.

**Production maturity:** Single-node only, no HA/replication, no multi-tenancy. Not suitable for clinical data in production.

**Trade-off:** Excellent for prototyping (`pip install chromadb`), not for production clinical workloads.

## Comparison

| Criterion | pgvector | Milvus | ChromaDB |
|---|---|---|---|
| Hybrid search | Full SQL + vector | Boolean filters | Dict filters |
| OpenShift | Crunchy PGO Level 5 | Official operator | No official support |
| Production readiness | Battle-tested (PostgreSQL) | CNCF graduated | Single-node only |
| Additional infra | None if PostgreSQL already used | Separate service | Low |
| Python async | SQLAlchemy 2.0 + asyncpg | pymilvus | chromadb |
| At <1K vectors | Sequential scan, exact results | Works (Lite mode) | Works |

## Embedding Model

The embedding model must be **pluggable** — organizations may need to use a specific model due to domain preferences, legal restrictions, or compliance requirements.

**Architecture:** Separate `EmbeddingProvider` interface from `VectorStore` interface. The provider produces vectors; the store stores/searches them. Configuration selects the provider; acp-writer code never depends on a specific model.

**Default recommendation:** `NeuML/pubmedbert-base-embeddings`
- 768 dimensions, local (no API dependency), free
- Fine-tuned on PubMed for medical text, 95.64% avg on medical benchmarks
- 512-token context sufficient for individual recommendations
- No provider lock-in — runs locally regardless of LLM provider choice

**Alternative:** OpenAI `text-embedding-3-large` (3,072 dims, truncatable) via LiteLLM. Use when operational simplicity through the existing proxy is preferred. Works with any provider LiteLLM supports.

**Alternative:** Any sentence-transformers model or custom fine-tuned model. The `EmbeddingProvider` interface accepts any callable that maps `list[str] → list[list[float]]`.

## Recommendation

**Use PostgreSQL + pgvector.**

Rationale:
1. **OpenShift certified** — Crunchy PGO Level 5 with pgvector bundled
2. **No additional infrastructure** — PostgreSQL may be needed for other acp-writer state (care plan persistence, approval workflow). Vector store becomes a table, not a separate service.
3. **Hybrid search via SQL** — maximally flexible for clinical metadata filtering
4. **At 100-1,000 vectors** — sequential scan gives exact results, zero tuning
5. **Pluggable per AGENTS.md** — behind an abstraction boundary within acp-writer
6. **Production mature** — ACID, backup/restore, operational tooling well-understood

**Default embedding model:** `NeuML/pubmedbert-base-embeddings` (768 dims, local, clinical-domain). Configurable via `EmbeddingProvider` interface — organizations can substitute any model.

## Dependencies

```
pgvector>=0.5.0         # Python bindings for pgvector
sqlalchemy>=2.0         # Async ORM
asyncpg>=0.31.0         # Async PostgreSQL driver
sentence-transformers   # Default embedding model (pubmedbert)
```

## Next Steps

1. Add PostgreSQL service to `compose.yml` for local development
2. Implement `EmbeddingProvider` interface (default: pubmedbert, configurable)
3. Implement `VectorStore` interface using pgvector + SQLAlchemy
4. Create Helm chart or add to existing acp-writer chart for Crunchy PGO integration
