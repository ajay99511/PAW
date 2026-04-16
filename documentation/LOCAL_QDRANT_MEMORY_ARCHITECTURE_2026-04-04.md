# Local Qdrant Memory Architecture (2026-04-04)

## Objective

Eliminate framework dependency for long-term memory management and run memory fully local with:

- Qdrant (storage + retrieval)
- Ollama (embeddings + optional memory extraction prompt)
- In-repo logic (extraction, dedupe, scoring, diversification, consolidation)

## Implemented Design

### 1. Single local memory backend

- The `packages/memory/mem0_client.py` module now implements local memory directly on Qdrant.
- No `mem0ai` runtime dependency remains.
- Existing `mem0_*` function names are preserved for compatibility with current API/agent call sites.

### 2. Memory extraction without external framework

- Primary path: structured JSON extraction prompt to local Ollama model.
- Fallback path: deterministic heuristic extraction from user messages.
- Normalized text hashing + semantic near-duplicate checks prevent duplicate memory bloat.

### 3. Retrieval quality upgrades

- Hybrid scoring on memory recall:
  - vector similarity (primary)
  - lexical overlap
  - temporal recency decay
- MMR-style diversification to reduce repeated/near-identical memory snippets in context.

### 4. Operational reliability

- Qdrant collection auto-init on first use.
- Scroll-based full memory listing for transparency APIs.
- Direct point update/delete support.
- Existing 5-layer orchestration remains intact.

## Why these choices

- Qdrant supports dense+sparse/hybrid retrieval patterns and search relevance tuning in its core docs.
- Qdrant documents local Docker usage with persistent host storage.
- Quantization and optimization knobs are documented for memory/performance tradeoffs.
- Diversification via MMR and ANN foundations via HNSW are well-established retrieval techniques.

## Sources (validated 2026-04-04)

- Qdrant Quickstart: persistent Docker volume and local deployment patterns  
  https://qdrant.tech/documentation/quickstart/
- Qdrant Concepts / Search / Hybrid / Filtering / Snapshots navigation and APIs  
  https://qdrant.tech/documentation/concepts/  
  https://qdrant.tech/documentation/operations/snapshots/
- Qdrant Quantization (scalar/binary/1.5-bit/2-bit tradeoffs)  
  https://qdrant.tech/documentation/manage-data/quantization/
- Qdrant sparse vectors + hybrid search article  
  https://qdrant.tech/articles/sparse-vectors/
- HNSW paper (ANN foundation)  
  https://arxiv.org/abs/1603.09320
- ColBERT paper (late interaction / retrieval quality reference)  
  https://arxiv.org/abs/2004.12832
- RAG paper (retrieval-augmented generation baseline)  
  https://arxiv.org/abs/2005.11401
- Lost in the Middle (long-context placement effects)  
  https://arxiv.org/abs/2307.03172

