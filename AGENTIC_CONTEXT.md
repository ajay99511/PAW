# PersonalAssist — Agentic Context & Architecture Brief

**Document Purpose:** Single-source truth for understanding the PersonalAssist codebase, architecture decisions, gaps, security posture, and actionable next steps.

**Date:** March 29, 2026  
**Project Type:** Local-first AI Personal Assistant with Multi-Agent Orchestration  
**Stack:** FastAPI + Tauri + React + Qdrant + Mem0 + LiteLLM + SQLite

---

## 📊 Executive Summary

PersonalAssist is a **well-architected but incomplete** multi-agent system with strong foundational design. The core stack choices are sound, but critical execution gaps exist between designed architecture and runtime reality.

### Current State at a Glance

| Dimension | Status | Health |
|-----------|--------|--------|
| **Core Architecture** | ✅ Implemented | 🟢 Strong |
| **Memory System (5-Layer)** | ⚠️ Partially Dormant | 🟡 60% Active |
| **Agent Orchestration** | ✅ Crew Pipeline | 🟢 Functional |
| **A2A Registry** | ⚠️ Stub Handlers | 🟡 40% Active |
| **Security Boundaries** | ⚠️ Fragmented | 🟡 Moderate Risk |
| **Dependency Health** | ⚠️ 4 CVEs (pip), 1 High (npm) | 🟡 Needs Attention |
| **Test Coverage** | ✅ 160 tests, 138 pass | 🟢 86% Pass Rate |
| **Frontend Build** | ✅ Clean (after fixes) | 🟢 Passing |

### Top 3 Critical Gaps

1. **Memory Layers 2-4 Dormant**: Session ID not threaded through chat endpoints → JSONL transcripts, pruning, and compaction never fire
2. **A2A Agent Handlers Stubbed**: 4 Tier-1 agents registered but return placeholder responses
3. **Security Boundary Fragmentation**: `FS_ALLOWED_ROOTS` permissive when empty, shell execution not sandboxed, CSP overly permissive

---

## 🏗️ Architecture Overview

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Tauri Desktop App                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │  Chat    │ │  Memory  │ │  Agents  │ │ Telegram │ │  Health  │ │
│  │  Page    │ │  Page    │ │  Page    │ │  Page    │ │  Page    │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
└───────┼────────────┼────────────┼────────────┼────────────┼────────┘
        │            │            │            │            │
        └────────────┴────────────┴────────────┴────────────┘
                              │
                    x-api-token auth
                              │
        ┌─────────────────────▼─────────────────────┐
        │           FastAPI Backend (Port 8000)     │
        │  ┌─────────────────────────────────────┐  │
        │  │  API Gateway + Auth Middleware      │  │
        │  └──────────────┬──────────────────────┘  │
        │                 │                          │
        │  ┌──────────────┼──────────────────────┐  │
        │  │              │                      │  │
        │  ▼              ▼                      ▼  │
        │ ┌──────────┐ ┌──────────┐ ┌──────────────┐│
        │ │  Chat    │ │  Agent   │ │   Memory     ││
        │ │  Routes  │ │  Routes  │ │   Routes     ││
        │ └────┬─────┘ └────┬─────┘ └──────┬───────┘│
        │      │            │              │         │
        └──────┼────────────┼──────────────┼─────────┘
               │            │              │
    ┌──────────▼────┐ ┌─────▼────────┐ ┌──▼──────────┐
    │  LiteLLM      │ │  Crew        │ │  Mem0       │
    │  Model        │ │  Pipeline    │ │  + Qdrant   │
    │  Gateway      │ │  (ReAct)     │ │  (RAG)      │
    └───────────────┘ └──────────────┘ └─────────────┘
```

### Core Runtime Flow

1. **User Input** → Tauri Desktop (`ChatPage.tsx`)
2. **API Call** → `POST /chat/smart` or `POST /chat/smart/stream`
3. **Context Assembly** → `build_context()` (5-layer memory)
4. **LLM Inference** → LiteLLM → Ollama/Gemini/Claude/DeepSeek
5. **Response Streaming** → SSE back to frontend
6. **Auto-Learning** → `extract_and_store_from_turn()` → Mem0
7. **Persistence** → ChatMessage saved to SQLite

### Repository Structure

```
C:\Agents\PersonalAssist\
├── apps/
│   ├── api/              # FastAPI backend (main.py, routers)
│   └── desktop/          # Tauri + React UI
│       ├── src/          # React pages, components, hooks
│       └── src-tauri/    # Rust/Tauri configuration
├── packages/             # Shared Python packages
│   ├── agents/           # Crew, A2A registry, tools
│   ├── memory/           # Memory service, Qdrant, Mem0
│   ├── tools/            # FS, Git, Shell, Exec, Ingest
│   ├── model_gateway/    # LiteLLM client, model registry
│   ├── automation/       # ARQ worker, jobs scheduler
│   ├── messaging/        # Telegram bot, webhook
│   └── shared/           # Config, DB, redaction, utils
├── infra/                # Docker Compose (Qdrant)
├── storage/              # Qdrant data volume
└── tests/                # Pytest test suite
```

---

## 🧠 Memory System (5-Layer Architecture)

### Designed Architecture

| Layer | Name | Purpose | Status |
|-------|------|---------|--------|
| **Layer 1** | Bootstrap Injection | AGENTS.md, SOUL.md, USER.md | ✅ Active |
| **Layer 2** | JSONL Transcripts | Append-only session history | ❌ Dormant |
| **Layer 3** | Session Pruning | TTL-aware in-memory window | ❌ Dormant |
| **Layer 4** | Compaction | Adaptive summarization | ❌ Dormant |
| **Layer 5A** | Mem0 | Semantic fact extraction | ✅ Active |
| **Layer 5B** | Qdrant RAG | Document search | ✅ Active |

### Critical Gap: Session ID Not Threaded

**Problem:**
```python
# In main.py chat endpoints
context = await build_context(req.message, user_id="default")
#                                                  ^^^^^^^^^^^^^
#                                          No session_id passed!
```

**Consequence:**
- Layers 2-4 require `session_id` to function
- `build_context()` silently skips dormant layers
- Session transcripts never written to disk
- Pruning and compaction never trigger
- **Result:** Memory system operates at ~60% capacity

**Fix Required:**
```python
# Thread session_id through entire call chain
context = await build_context(
    req.message,
    user_id="default",
    session_id=session_id,  # ← Add this
)
```

### Context Budget Constraints

| Budget | Current Value | Issue |
|--------|---------------|-------|
| `rag_context_char_budget` | 3200 chars | Too tight for complex projects |
| `chat_history_max_messages` | 10 messages | Loses early context in long conversations |
| `agent_context_char_budget` | 6000 chars | Competes with memory layers |

**Recommendation:** Dynamic budgeting based on message complexity, not hardcoded limits.

---

## 🤖 Agent Orchestration

### Crew Pipeline (Active)

**Flow:** `Planner → Researcher → Synthesizer`

```python
# crew.py
async def run_crew(user_message, user_id, model):
    # Stage 1: Planner creates action plan
    plan = await chat(PLANNER_SYSTEM, user_message, context)
    
    # Stage 2: Researcher gathers info
    research = await chat(RESEARCHER_SYSTEM, plan, context)
    
    # Stage 3: Synthesizer writes response
    response = await chat(SYNTHESIZER_SYSTEM, research, plan)
    
    return response
```

**Status:** ✅ Functional, used by `/chat/smart` and background jobs

### Tool Loop (Active with Caveats)

**Two Modes:**
1. **Native Tool Calling** (preferred) — Models with function-calling support
2. **Legacy Regex JSON** (fallback) — Fragile, breaks on inconsistent JSON

**Available Tools:**
- `read_file`, `write_file`, `find_files`, `list_directory`
- `git_status`, `git_log`, `git_diff`, `git_summary`
- `search_user_memories`, `search_documents`
- `exec_command` (gated behind `ALLOW_EXEC_TOOLS`)

**Security Concern:** `exec_command` uses `subprocess.Popen` with shell execution. Allowlist checks are policy-based, not sandboxed.

### A2A Registry (Partially Active)

**Designed Flow:**
```
User Request → Agent Router → A2A Registry → Delegate → Handler → Format → Response
```

**Registered Tier-1 Agents:**
1. **Code Reviewer** — Reviews code, finds security issues
2. **Workspace Analyzer** — Analyzes project structure
3. **Test Generator** — Generates test files
4. **Dependency Auditor** — Audits dependencies

**Current State:** All 4 agents registered but handlers return **stub responses**:

```python
# agents.py (BEFORE FIX)
async def handle_code_review(task, **kwargs):
    # TODO: Implement actual code review logic
    return {
        "findings": [],
        "summary": "Code review not yet implemented",  # ← Placeholder
        "score": {"security": 0, "performance": 0, "style": 0, "overall": 0},
    }
```

**After Fix (March 29, 2026):**
Handlers now run specialized crew prompts with structured JSON output parsing.

---

## 🔒 Security Posture

### Vulnerability Scan Results (March 29, 2026)

#### Python Dependencies (pip-audit)
- **4 CVEs in 3 packages**
  - `pip` (2 CVEs): Path traversal in wheel extraction (CVE-2026-1703), tar extraction (CVE-2025-8869)
  - `pygments` (1 CVE): Inefficient regex complexity (CVE-2026-4539)
  - `requests` (1 CVE): Predictable temp file extraction (CVE-2026-25645)

#### npm Dependencies
- **1 High Severity**: `picomatch` ReDoS vulnerability (CVSS 7.5)
  - Transitive via Vite → fix available in picomatch 4.0.4+

#### Rust Dependencies (cargo audit)
- **0 vulnerabilities**
- **17 unmaintained warnings** (transitive GTK/unic ecosystem)
- **1 unsound warning** (transitive)

### Security Boundary Issues

#### 1. Filesystem Security Fragmented

**Issue:** `FS_ALLOWED_ROOTS` env var is permissive when empty

```python
# config.py
FS_ALLOWED_ROOTS: str = ""  # ← Empty = all paths allowed!

# fs.py
if not self.allowed_roots:
    return True, "No roots configured, allowing"  # ← Bypass!
```

**Risk:** If env var not set, agent can read/write anywhere on system.

**Fix:** Make non-empty roots mandatory in production profile.

#### 2. Shell Execution Not Sandboxed

**Issue:** `exec_command` uses `subprocess.Popen(shell=True)`

```python
# exec.py
process = await asyncio.create_subprocess_shell(
    command,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

**Allowlist Checks:** Policy-based, not enforced isolation.

**Risk:** Command injection via shell operators (`;`, `|`, `&&`).

**Fix:** Use `subprocess.Popen` with `shell=False` and argument lists.

#### 3. Tauri CSP Overly Permissive

**Issue:** `tauri.conf.json` allows `'unsafe-eval'` and wide localhost policy

```json
{
  "security": {
    "csp": "default-src 'self'; script-src 'self' 'unsafe-eval'; connect-src 'self' http://localhost:*"
  }
}
```

**Risk:** XSS vulnerability if any frontend code is compromised.

**Fix:** Remove `'unsafe-eval'`, restrict `connect-src` to exact API endpoint.

#### 4. Frontend Auth Inconsistency

**Issue:** Some UI components bypass shared API client

```typescript
// ChatPage.tsx (BEFORE FIX)
const response = await fetch(`http://127.0.0.1:8000/chat/threads/${threadId}`);
//                                                         ^^^^^^^^^^^^^^^^^^^
//                                          No x-api-token header!

// api.ts (shared client)
function buildHeaders() {
  headers.set("x-api-token", API_TOKEN);  // ← Only used in api.ts
}
```

**Risk:** If token enforcement enabled, parts of UI silently break.

**Fix:** All fetch calls route through `api()` helper in `api.ts`.

---

## 📦 Dependency Health

### Python Dependencies

**Total:** ~140 packages  
**Outdated:** 25 packages (check with `pip list --outdated`)  
**Vulnerabilities:** 4 CVEs (see Security section)

**Critical Updates Needed:**
| Package | Current | Fixed In | CVE |
|---------|---------|----------|-----|
| `pip` | 25.1.1 | 25.3, 26.0 | CVE-2025-8869, CVE-2026-1703 |
| `requests` | 2.32.5 | 2.33.0 | CVE-2026-25645 |
| `pygments` | 2.19.2 | No fix yet | CVE-2026-4539 |

**Duplicate Declarations:**
- `httpx>=0.28.0` appears twice in `requirements.txt` (lines 9 and 49)

**Missing Direct Declarations:**
- `apscheduler>=3.11.2` (used in `jobs.py`, not in requirements)
- `elevenlabs` (optional, used in `tts.py`)

### npm Dependencies

**Total:** 253 packages (132 prod, 122 dev)  
**Outdated:** Check with `npm outdated`  
**Vulnerabilities:** 1 High (picomatch)

**Fix:** `npm update picomatch` or upgrade Vite to latest

### Rust Dependencies

**Total:** ~200 crates (Tauri ecosystem)  
**Vulnerabilities:** 0  
**Warnings:** 17 unmaintained, 1 unsound (all transitive)

**Action:** No immediate action required — warnings are in transitive GTK dependencies.

---

## 🧪 Test Suite Status

### Pytest Results

**Total Tests:** 160  
**Passing:** 138 (86%)  
**Failing:** 14  
**Skipped:** 8

**Failure Concentration:**
- `test_phase2_workspace.py` — FS permission semantics with `FS_ALLOWED_ROOTS`
- `test_pruning.py` — Edge cases in session pruning logic

**Test Coverage by Module:**
| Module | Tests | Coverage |
|--------|-------|----------|
| `memory/` | 45 | High |
| `agents/` | 38 | Medium |
| `tools/` | 32 | High |
| `model_gateway/` | 18 | Medium |
| `messaging/` | 12 | Low |
| `automation/` | 8 | Low |

### Build Status

**npm run build:** ✅ Passing (after March 29 fixes)  
**TypeScript Errors:** 0 (was 15+ before fixes)

**Fixes Applied:**
- Removed unused imports (`AgentCard`, `TaskResult` interfaces)
- Fixed `unknown` typing in `workspace-api.ts`
- Unified API client usage across all pages

---

## 🔄 Background Jobs & Scheduling

### Current State

**Scheduler:** APScheduler (AsyncIOScheduler)  
**Registered Jobs:**
1. **Daily Briefing** — 8:00 AM, summarizes git activity
2. **Qdrant Snapshot** — Hourly, exports Qdrant collection snapshots

**Issue:** APScheduler is in-process and fragile
- Jobs reset on restart
- No persistence layer
- No retry logic

### ARQ Worker (Partially Integrated)

**Designed Flow:**
```
FastAPI → Redis Queue → ARQ Worker → Job Handler → Result Storage
```

**Current State:**
- ARQ worker exists (`arq_worker.py`)
- Missing `export_snapshot` function in `qdrant_store.py` (FIXED March 29)
- Not integrated with job router
- Redis connection configured but not used by default

**Migration Plan:**
1. Decide: APScheduler-only vs ARQ-only (not both)
2. If ARQ: Fully integrate with job router, add persistence
3. If APScheduler: Add SQLite job store, remove ARQ code

**Recommendation:** Use ARQ for production — provides retries, persistence, distributed execution.

---

## 📱 Telegram Bot Integration

### Current State

**Status:** ✅ Functional (polling mode)  
**Features:**
- Text message handling
- User authentication (pairing/allowlist/open policy)
- Rate limiting (10 msg/min)
- Chunked responses (≤4096 chars)

**Configuration:**
- Bot token: Env var `TELEGRAM_BOT_TOKEN` (read at startup)
- DM policy: Env var `TELEGRAM_DM_POLICY`
- Config persistence: `~/.personalassist/telegram_config.env` (FIXED March 29)

**Missing Features:**
- Voice message transcription (Whisper integration)
- File/image handling
- Proactive push notifications
- Hot-reload without bot restart

### Webhook Mode (Broken)

**Issue:** Webhook handler creates fresh service instance

```python
# telegram_webhook.py
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    service = TelegramBotService()  # ← New instance, not initialized!
    # ...
    return JSONResponse(status_code=503, content={"error": "Service not initialized"})
```

**Fix:** Unify webhook and polling modes under `BotManager`.

---

## 🎯 Podcast Generation

### Current State

**Status:** ✅ Functional (background job)  
**Pipeline:** `Planner → Researcher → Script Writer → Producer → TTS`

**TTS Providers:**
1. **edge-tts** (default) — Free, robotic voice
2. **ElevenLabs** (optional) — Premium, rate-limited

**Issues:**
- No multi-voice support (host + guest)
- Research stored in separate `podcast_research` Qdrant collection
- No progress streaming to UI (5+ minute wait with spinner)
- Audio quality limited by edge-tts capabilities

**Recommendation:** De-prioritize until core agent loop is robust.

---

## 🖥️ Desktop App (Tauri + React)

### Pages Overview

| Page | Purpose | Status |
|------|---------|--------|
| `ChatPage` | Multi-model chat with RAG toggle | ✅ Active |
| `MemoryPage` | View/search memories, sessions, bootstrap files | ✅ Active |
| `AgentsPage` | Run crew, view trace | ✅ Active |
| `A2APage` | Delegate to specialized agents | ⚠️ Partially Active |
| `TelegramPage` | Configure bot, manage users | ✅ Active |
| `WorkspacePage` | Manage workspaces, permissions | ✅ Active |
| `IngestionPage` | Ingest files/directories into Qdrant | ✅ Active |
| `PodcastPage` | Generate podcasts | ✅ Active |
| `JobsPage` | View background jobs | ⚠️ Read-only |
| `HealthPage` | System health monitoring | ✅ Active |
| `ModelsPage` | Switch active model | ✅ Active |

### Frontend Architecture

**State Management:** React Query (TanStack Query)  
**API Client:** Custom `api.ts` with token auth  
**Markdown Rendering:** `react-markdown` + `remark-gfm`  
**Streaming:** SSE via `fetch` with `Content-Type: text/event-stream`

**Recent Fixes (March 29, 2026):**
- Unified API client usage across all pages
- Removed hardcoded fetch calls
- Fixed TypeScript build errors
- Added proper error handling

---

## 📚 Research & Best Practices References

### Agentic Architecture Patterns

1. **ReAct Pattern** (Reason + Act)
   - Paper: [ReAct: Synergizing Reasoning and Acting](https://arxiv.org/abs/2210.03629)
   - Used in: Crew tool loop
   - Status: ✅ Implemented

2. **RAG Pattern** (Retrieval-Augmented Generation)
   - Paper: [RAG for Knowledge-Intensive NLP](https://arxiv.org/abs/2005.11401)
   - Used in: `build_context()` + Qdrant search
   - Status: ✅ Implemented (budget constrained)

3. **Context Engineering**
   - Anthropic: [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents/)
   - Principle: "Context is a critical but finite resource"
   - Status: ⚠️ Budget too tight (3200 chars)

4. **Durable Execution**
   - LangGraph: Checkpoints, time-travel, human-in-the-loop
   - CrewAI Flows: Persist execution state
   - Status: ❌ Not implemented (APScheduler limitation)

5. **Lost in the Middle**
   - Paper: [Lost in the Middle](https://arxiv.org/abs/2307.03172)
   - Finding: Models recall info at start/end of context better than middle
   - Implication: Prioritize bootstrap + recent messages

### Security Standards

1. **OWASP Top 10 for LLM Applications**
   - https://genai.owasp.org/llm-top-10/
   - Relevant: Prompt injection, insecure output handling, model DoS

2. **NIST AI RMF 1.0**
   - Risk management framework for AI systems
   - Relevant: Trustworthiness, safety, security

3. **Model Context Protocol (MCP)**
   - Anthropic standard for tool interoperability
   - Risk: Remote MCP = remote code execution
   - OpenAI Warning: "Connectors may have access to sensitive data"

---

## 🛠️ Actionable Next Steps

### Phase 1: Critical Fixes (Week 1-2)

**Priority:** Security + Correctness

1. **Wire Session ID Through Chat Path**
   - Modify `main.py` chat endpoints to accept `session_id`
   - Thread through `build_context()` call
   - Activate Layers 2-4 of memory

2. **Harden Security Boundaries**
   - Make `FS_ALLOWED_ROOTS` non-empty by default
   - Replace `shell=True` with `shell=False` in `exec.py`
   - Tighten Tauri CSP (remove `'unsafe-eval'`)

3. **Fix Dependency Vulnerabilities**
   - Upgrade `pip` to 25.3+
   - Upgrade `requests` to 2.33.0+
   - Upgrade `picomatch` to 4.0.4+

4. **Unify Orchestration Contracts**
   - Fix `run_crew()` signature mismatches
   - Remove dead params (`session_type`, `session_id` in compaction/ARQ)
   - Add typed request/response models

### Phase 2: Architecture Hardening (Week 3-4)

**Priority:** Reliability + Observability

1. **Decide Scheduler Strategy**
   - Option A: APScheduler + SQLite job store
   - Option B: ARQ + Redis (recommended)
   - Remove unused code

2. **Add Checkpointing**
   - Persist session state to SQLite
   - Enable workflow replay
   - Add time-travel debugging

3. **Improve Observability**
   - Add structured logging (JSON format)
   - Trace IDs across service boundaries
   - Metrics dashboard (response time, token usage, error rates)

4. **Enhance A2A System**
   - Add agent chaining/pipelining
   - Persist task results to SQLite
   - Add streaming output from delegated tasks

### Phase 3: Feature Polish (Week 5+)

**Priority:** User Experience

1. **Dynamic Context Budgeting**
   - Replace hardcoded char limits with adaptive budgeting
   - Prioritize recent + relevant context

2. **Telegram Enhancements**
   - Add Whisper voice transcription
   - Add file/image handling
   - Add proactive push notifications

3. **Memory Timeline UI**
   - Visualize when facts were learned
   - Tag memories as "permanent" vs "session-only"
   - Proactive memory surfacing

4. **Workspace Awareness**
   - Incremental re-indexing (watch for file changes)
   - "Cite your sources" mode
   - Full-text search across threads

---

## 📋 Decision Log

### Architecture Decisions

| Date | Decision | Rationale | Status |
|------|----------|-----------|--------|
| 2026-03-15 | Use LiteLLM as model gateway | Abstraction over multiple LLM providers | ✅ Active |
| 2026-03-18 | Qdrant + Mem0 for memory | Vector search + user-centric memory | ✅ Active |
| 2026-03-20 | Tauri for desktop app | Lightweight, Rust security, cross-platform | ✅ Active |
| 2026-03-22 | APScheduler for background jobs | Simple, in-process | ⚠️ Being Replaced |
| 2026-03-25 | A2A registry for agent delegation | Decoupled agent architecture | ⚠️ Partially Active |
| 2026-03-28 | Crew pipeline for complex tasks | ReAct pattern implementation | ✅ Active |
| 2026-03-29 | Fix A2A stub handlers | Make agents actually functional | ✅ Fixed |
| 2026-03-29 | Unify frontend API client | Consistent auth, error handling | ✅ Fixed |

### Rejected Alternatives

1. **LangGraph for Orchestration**
   - Rejected: Adds complexity, learning curve
   - Alternative: Custom crew pipeline (simpler for solo dev)

2. **Docker for Command Sandboxing**
   - Rejected: Overhead, Windows compatibility
   - Alternative: `shell=False` + allowlist (good enough for local-first)

3. **PostgreSQL for Chat History**
   - Rejected: Overkill for local-first
   - Alternative: SQLite (lightweight, file-based)

---

## 🔍 Code Quality Metrics

### Complexity Analysis (Radon)

**Maintainability Index:**
- Average: 72/100 (Good)
- Lowest: `crew.py` (58/100), `memory_service.py` (61/100)

**Cyclomatic Complexity:**
- `run_crew()`: 28 (High) — Refactor recommended
- `build_context()`: 24 (High) — Split into smaller functions
- `fs.list_directory()`: 18 (Medium) — Acceptable

### Code Style

**Python:**
- Linting: No flake8/pylint scans in CI
- Formatting: No black/isort enforcement
- Type Hints: Partial (Pydantic models well-typed, functions mixed)

**TypeScript:**
- Strict mode: Enabled
- Build: Passing (after March 29 fixes)
- Linting: No ESLint configuration

**Recommendation:** Add pre-commit hooks for black, isort, flake8, ESLint.

---

## 📖 Glossary

| Term | Definition |
|------|------------|
| **A2A** | Agent-to-Agent delegation protocol |
| **ARQ** | Async Redis Queue (background job processor) |
| **CSP** | Content Security Policy (browser security header) |
| **Mem0** | User-centric memory extraction service |
| **Qdrant** | Vector database for semantic search |
| **RAG** | Retrieval-Augmented Generation |
| **ReAct** | Reason + Act pattern for agent loops |
| **SSE** | Server-Sent Events (streaming protocol) |
| **TTL** | Time-To-Live (session expiration) |

---

## 📞 Quick Start Commands

### Development

```bash
# Start API server
cd C:\Agents\PersonalAssist
.\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --reload

# Start desktop dev server
cd C:\Agents\PersonalAssist\apps\desktop
npm run dev

# Run tests
.\.venv\Scripts\python.exe -m pytest -v

# Check dependencies
.\.venv\Scripts\python.exe -m pip_audit
npm audit
cargo audit
```

### Production

```bash
# Build desktop app
cd C:\Agents\PersonalAssist\apps\desktop
npm run tauri build

# Start API server (production)
.\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

---

## 🎯 Success Metrics

### Current State (March 29, 2026)

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Test Pass Rate | >90% | 86% | 🟡 Close |
| Build Status | Clean | Clean | ✅ Pass |
| Critical CVEs | 0 | 3 | 🟡 Needs Work |
| A2A Handler Coverage | 100% | 100% | ✅ Fixed |
| Memory Layer Activation | 100% | 60% | 🟡 In Progress |

### Target State (End of Phase 2)

- Test Pass Rate: >95%
- Critical CVEs: 0
- Memory Layer Activation: 100%
- Scheduler: Unified (ARQ or APScheduler)
- Security: All boundaries hardened

---

**Document Version:** 1.0  
**Last Updated:** March 29, 2026  
**Maintainer:** Solo Developer (PersonalAssist Project)
