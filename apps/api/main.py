"""
PersonalAssist — FastAPI Backend
Routes: health, chat (plain/stream/smart), memory, ingest, agents
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from packages.shared.config import settings
from packages.model_gateway.client import chat, chat_stream

# Directory containing static test pages
_STATIC_DIR = Path(__file__).parent

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App Setup ────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up PersonalAssist API and Background Scheduler...")
    
    # Initialize chat database (required for chat persistence endpoints)
    try:
        from packages.shared.db import init_db
        await init_db()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
        
    # Check for and restore P2P synced snapshots
    try:
        from packages.automation.sync import restore_latest_snapshots
        await restore_latest_snapshots()
    except Exception as e:
        logger.error(f"Failed to restore P2P snapshots during boot: {e}")
        
    scheduler.start()
    try:
        from packages.automation.jobs import setup_jobs
        setup_jobs(scheduler)
    except Exception as e:
        logger.error(f"Failed to setup background jobs: {e}")
    yield
    # Shutdown
    logger.info("Shutting down PersonalAssist API...")
    scheduler.shutdown()


app = FastAPI(
    title="PersonalAssist API",
    version="0.2.0",
    description="AI-powered personal assistant with memory & multi-model support",
    lifespan=lifespan,
)

cors_origins_raw = os.getenv("CORS_ALLOW_ORIGINS", "")
allowed_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
if not allowed_origins:
    allowed_origins = [
        "http://127.0.0.1:1420",
        "http://localhost:1420",
        "tauri://localhost",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Podcast Router (isolated sub-router) ─────────────────────────────
from apps.api.podcast_router import podcast_router
app.include_router(podcast_router)

# ── Request / Response Models ────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    model: str = "local"
    temperature: float = 0.7
    thread_id: Optional[str] = None


class MemoryStoreRequest(BaseModel):
    content: str
    memory_type: str = "PROFILE"
    user_id: str = "default"


class MemoryQueryRequest(BaseModel):
    query: str
    user_id: str = "default"
    k: int = Field(default=5, ge=1, le=20)


class IngestRequest(BaseModel):
    path: str
    recursive: bool = True
    glob_patterns: Optional[list[str]] = None


class ForgetRequest(BaseModel):
    memory_id: str


class ModelSwitchRequest(BaseModel):
    model: str


class ContextReportRequest(BaseModel):
    file_path: Optional[str] = None
    selection: Optional[str] = None
    terminal_error: Optional[str] = None
    workspace: Optional[str] = None


class WorkflowRunRequest(BaseModel):
    nodes: list[dict]
    edges: list[dict]

class WorkflowSaveRequest(BaseModel):
    name: str
    nodes: list[dict]
    edges: list[dict]


# ── Global State ─────────────────────────────────────────────────────

_ACTIVE_CONTEXT: dict = {}

def _build_thread_title(message: str) -> str:
    title = (message or "New Chat").strip() or "New Chat"
    return title[:57] + "..." if len(title) > 60 else title


async def _resolve_or_create_thread(session, thread_id: Optional[str], message: str):
    from packages.memory.models import ChatThread

    if thread_id:
        existing = await session.get(ChatThread, thread_id)
        if existing:
            return existing

    thread = ChatThread(title=_build_thread_title(message))
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return thread


def _touch_thread(thread) -> None:
    thread.updated_at = datetime.now(timezone.utc)
# ── Health ───────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}


# ── Chat Endpoints ───────────────────────────────────────────────────


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """Non-streaming chat via model gateway."""
    from packages.shared.db import AsyncSessionLocal
    from packages.memory.models import ChatMessage

    async with AsyncSessionLocal() as session:
        thread = await _resolve_or_create_thread(session, req.thread_id, req.message)
        req.thread_id = thread.id

        user_msg = ChatMessage(
            thread_id=req.thread_id,
            role="user",
            content=req.message,
        )
        _touch_thread(thread)
        session.add(user_msg)
        await session.commit()

    messages = [{"role": "user", "content": req.message}]

    try:
        response = await chat(messages, model=req.model, temperature=req.temperature)
    except Exception as exc:
        logger.error("Chat error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    model_used = settings.resolve_model(req.model)
    async with AsyncSessionLocal() as session:
        thread = await _resolve_or_create_thread(session, req.thread_id, req.message)
        assistant_msg = ChatMessage(
            thread_id=req.thread_id,
            role="assistant",
            content=response,
            model_used=model_used,
        )
        _touch_thread(thread)
        session.add(assistant_msg)
        await session.commit()

    return {
        "response": response,
        "model_used": model_used,
        "thread_id": req.thread_id,
    }


@app.post("/chat/stream")
async def chat_stream_endpoint(req: ChatRequest):
    """SSE streaming chat via model gateway with persistence."""
    from packages.shared.db import AsyncSessionLocal
    from packages.memory.models import ChatMessage

    async with AsyncSessionLocal() as session:
        thread = await _resolve_or_create_thread(session, req.thread_id, req.message)
        req.thread_id = thread.id

        user_msg = ChatMessage(
            thread_id=req.thread_id,
            role="user",
            content=req.message,
        )
        _touch_thread(thread)
        session.add(user_msg)
        await session.commit()

    messages = [{"role": "user", "content": req.message}]

    async def generate():
        full_response = ""
        try:
            yield f"data: {json.dumps({'thread_id': req.thread_id})}\n\n"

            async for chunk in chat_stream(messages, model=req.model, temperature=req.temperature):
                full_response += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield "data: [DONE]\n\n"

            async with AsyncSessionLocal() as session:
                thread = await _resolve_or_create_thread(session, req.thread_id, req.message)
                assistant_msg = ChatMessage(
                    thread_id=req.thread_id,
                    role="assistant",
                    content=full_response,
                    model_used=settings.resolve_model(req.model),
                )
                _touch_thread(thread)
                session.add(assistant_msg)
                await session.commit()

        except Exception as exc:
            logger.error("Stream error: %s", exc)
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/chat/smart")
async def chat_smart(req: ChatRequest):
    """RAG-enhanced chat with auto-learning and persistence."""
    from packages.shared.db import AsyncSessionLocal
    from packages.memory.models import ChatMessage

    async with AsyncSessionLocal() as session:
        thread = await _resolve_or_create_thread(session, req.thread_id, req.message)
        req.thread_id = thread.id

        user_msg = ChatMessage(
            thread_id=req.thread_id,
            role="user",
            content=req.message,
        )
        _touch_thread(thread)
        session.add(user_msg)
        await session.commit()

    messages = [{"role": "user", "content": req.message}]
    context_prefix = ""
    memory_used = False

    global _ACTIVE_CONTEXT
    if _ACTIVE_CONTEXT:
        context_prefix += f"USER'S ACTIVE CONTEXT (IDE/Terminal):\n{json.dumps(_ACTIVE_CONTEXT, indent=2)}\n\n"

    try:
        from packages.memory.memory_service import build_context

        rag_context = await build_context(req.message, user_id="default")
        if rag_context:
            context_prefix += "RETRIEVED KNOWLEDGE & MEMORIES:\n" + rag_context + "\n"
            memory_used = True
    except Exception as exc:
        logger.warning("Memory layer unavailable, proceeding without context: %s", exc)

    if context_prefix:
        augmented_messages = [
            {"role": "system", "content": context_prefix},
            {"role": "user", "content": req.message},
        ]
    else:
        augmented_messages = messages

    try:
        response = await chat(augmented_messages, model=req.model, temperature=req.temperature)
    except Exception as exc:
        logger.error("Smart chat error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    model_used = settings.resolve_model(req.model)
    async with AsyncSessionLocal() as session:
        thread = await _resolve_or_create_thread(session, req.thread_id, req.message)
        assistant_msg = ChatMessage(
            thread_id=req.thread_id,
            role="assistant",
            content=response,
            model_used=model_used,
            memory_used=memory_used,
        )
        _touch_thread(thread)
        session.add(assistant_msg)
        await session.commit()

    extraction_result = {}
    try:
        from packages.memory.memory_service import extract_and_store_from_turn
        from packages.memory.consolidation import increment_turn, should_consolidate, consolidate_memories

        turn_messages = [
            {"role": "user", "content": req.message},
            {"role": "assistant", "content": response},
        ]
        extraction_result = await extract_and_store_from_turn(
            turn_messages,
            user_id="default",
        )

        increment_turn(user_id="default")
        if should_consolidate(user_id="default"):
            logger.info("Turn threshold reached, triggering memory consolidation")
            import asyncio
            asyncio.create_task(consolidate_memories(user_id="default", model=req.model))

    except Exception as exc:
        logger.warning("Auto-extraction failed (non-fatal): %s", exc)

    return {
        "response": response,
        "model_used": model_used,
        "memory_used": memory_used,
        "memories_extracted": extraction_result,
        "thread_id": req.thread_id,
    }


# ── Chat Thread Endpoints ────────────────────────────────────────────

@app.get("/chat/threads")
async def list_chat_threads():
    """List all saved chat threads."""
    from sqlalchemy import select
    from packages.shared.db import AsyncSessionLocal
    from packages.memory.models import ChatThread
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ChatThread).order_by(ChatThread.updated_at.desc())
        )
        threads = result.scalars().all()
        return {"threads": [
            {
                "id": t.id, 
                "title": t.title, 
                "updated_at": t.updated_at.isoformat()
            } for t in threads
        ]}

@app.get("/chat/threads/{thread_id}")
async def get_chat_thread(thread_id: str):
    """Get all messages for a specific thread."""
    from sqlalchemy import select
    from packages.shared.db import AsyncSessionLocal
    from packages.memory.models import ChatThread, ChatMessage
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ChatThread).where(ChatThread.id == thread_id)
        )
        thread = result.scalars().first()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
            
        msg_result = await session.execute(
            select(ChatMessage).where(ChatMessage.thread_id == thread_id).order_by(ChatMessage.timestamp)
        )
        messages = msg_result.scalars().all()
        
        return {
            "id": thread.id,
            "title": thread.title,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "model_used": m.model_used,
                    "memory_used": m.memory_used,
                    "timestamp": m.timestamp.isoformat()
                } for m in messages
            ]
        }

@app.delete("/chat/threads/{thread_id}")
async def delete_chat_thread(thread_id: str):
    """Delete a thread and all of its messages."""
    from sqlalchemy import select
    from packages.shared.db import AsyncSessionLocal
    from packages.memory.models import ChatThread
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ChatThread).where(ChatThread.id == thread_id)
        )
        thread = result.scalars().first()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
            
        await session.delete(thread)
        await session.commit()
        return {"status": "deleted", "id": thread_id}


# ── Memory Endpoints ─────────────────────────────────────────────────


@app.get("/memory/health")
async def memory_health():
    """Check Qdrant connectivity."""
    try:
        from packages.memory.qdrant_store import health_check
        result = await health_check()
        return {"status": "ok", "qdrant": "connected", "collections": result}
    except Exception as exc:
        logger.error("Qdrant health check failed: %s", exc)
        return {"status": "degraded", "qdrant": "disconnected", "error": str(exc)}


@app.post("/memory/store")
async def memory_store(req: MemoryStoreRequest):
    """Store a memory in Qdrant."""
    try:
        from packages.memory.memory_service import store_memory
        result = await store_memory(
            user_id=req.user_id,
            content=req.content,
            memory_type=req.memory_type,
        )
        return {"status": "stored", **result}
    except Exception as exc:
        logger.error("Memory store error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/memory/query")
async def memory_query(req: MemoryQueryRequest):
    """Query memories via semantic search."""
    try:
        from packages.memory.memory_service import query_memories
        results = await query_memories(
            user_id=req.user_id,
            query=req.query,
            k=req.k,
        )
        return {"results": results}
    except Exception as exc:
        logger.error("Memory query error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/memory/all")
async def memory_all(user_id: str = "default"):
    """
    List all Mem0 memories for a user.

    Provides transparency into what the system has learned.
    """
    try:
        from packages.memory.memory_service import get_all_user_memories
        memories = await get_all_user_memories(user_id=user_id)
        return {"memories": memories, "count": len(memories)}
    except Exception as exc:
        logger.error("Memory list error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/memory/forget")
async def memory_forget(req: ForgetRequest):
    """
    Delete a specific Mem0 memory by ID.

    Allows users to correct or remove learned facts.
    """
    try:
        from packages.memory.memory_service import forget_memory
        result = await forget_memory(req.memory_id)
        return result
    except Exception as exc:
        logger.error("Memory forget error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/memory/consolidate")
async def memory_consolidate(user_id: str = "default"):
    """
    Manually trigger memory consolidation routing.
    """
    try:
        from packages.memory.consolidation import consolidate_memories
        result = await consolidate_memories(user_id=user_id, model="active")
        return result
    except Exception as exc:
        logger.error("Consolidate error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Ingestion Endpoints ──────────────────────────────────────────────


@app.post("/ingest")
async def ingest_endpoint(req: IngestRequest):
    """
    Ingest files from a directory or single file into Qdrant.

    Crawls the path, parses supported file types, chunks intelligently,
    and upserts vectors into the Qdrant collection.
    """
    from pathlib import Path as PathLib

    target = PathLib(req.path)

    try:
        if target.is_dir():
            from packages.tools.ingest import ingest_directory
            report = await ingest_directory(
                path=req.path,
                recursive=req.recursive,
                glob_patterns=req.glob_patterns,
            )
        elif target.is_file():
            from packages.tools.ingest import ingest_file
            report = await ingest_file(path=req.path)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Path not found or not accessible: {req.path}",
            )

        return {
            "status": "completed",
            "report": report.to_dict(),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Ingestion error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Agent Endpoint ───────────────────────────────────────────────────


@app.post("/agents/run")
async def agents_run(req: ChatRequest):
    """Run a simple planner agent (placeholder for CrewAI)."""
    try:
        from packages.agents.crew import run_crew
        from packages.agents.trace import trace_manager
        
        # Inject context into the user message
        augmented_message = req.message
        global _ACTIVE_CONTEXT
        if _ACTIVE_CONTEXT:
            augmented_message = (
                f"Active Context (IDE/Terminal):\n{json.dumps(_ACTIVE_CONTEXT, indent=2)}\n\n"
                f"User Request:\n{req.message}"
            )
        
        # We will dispatch to the new lightweight crew orchestration.
        run_id = trace_manager.new_run()
        result = await run_crew(
            user_message=augmented_message,
            user_id="default",
            model=req.model,
            run_id=run_id,
        )
        return result
    except Exception as exc:
        logger.error("Agent run error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/agents/trace/{run_id}")
async def agents_trace_stream(run_id: str):
    """SSE streaming endpoint for agent traces."""
    from packages.agents.trace import trace_manager
    if not trace_manager.has_run(run_id):
        raise HTTPException(status_code=404, detail="Run ID not found or already finished")
        
    async def generate():
        try:
            async for event in trace_manager.stream(run_id):
                yield f"data: {event.model_dump_json()}\n\n"
        except Exception as exc:
            logger.error("Trace stream error: %s", exc)
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            
    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Model Endpoints ──────────────────────────────────────────────────

@app.get("/models")
async def list_models():
    """List all available models (local Ollama + remote)."""
    try:
        from packages.model_gateway.registry import get_all_models
        models = await get_all_models()
        return {"models": [m.model_dump() for m in models]}
    except Exception as exc:
        logger.error("List models error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/models/active")
async def get_active_model_endpoint():
    """Get the currently active model."""
    from packages.model_gateway.registry import get_active_model, get_model_by_id
    active_id = get_active_model()
    model = await get_model_by_id(active_id)
    return {"active_model": active_id, "model_info": model.model_dump() if model else None}

@app.post("/models/switch")
async def switch_model(req: ModelSwitchRequest):
    """Set the system-wide active model."""
    try:
        from packages.model_gateway.registry import set_active_model, get_model_by_id
        model = await get_model_by_id(req.model)
        if not model:
            raise HTTPException(status_code=404, detail=f"Model not found: {req.model}")
        
        active_id = set_active_model(req.model)
        from packages.shared.config import settings
        # Also persist to settings for fallback resolution
        settings.default_local_model = active_id
        
        return {"status": "success", "active_model": active_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Switch model error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Context Sensing Endpoints ────────────────────────────────────────

@app.post("/context/report")
async def report_context(req: ContextReportRequest):
    """External tools (IDE plugins, terminal hooks) ping this to report user activity."""
    global _ACTIVE_CONTEXT
    _ACTIVE_CONTEXT = req.model_dump(exclude_none=True)
    return {"status": "updated", "context": _ACTIVE_CONTEXT}

@app.get("/context/active")
async def get_active_context():
    """Get the currently sensed context."""
    return _ACTIVE_CONTEXT

@app.post("/context/clear")
async def clear_context():
    global _ACTIVE_CONTEXT
    _ACTIVE_CONTEXT = {}
    return {"status": "cleared"}

# ── Workflow Engine Endpoints (Phase J) ──────────────────────────────

@app.post("/workflows/run")
async def run_workflow(req: WorkflowRunRequest):
    """Parses a visual graph (nodes/edges) and executes it sequentially."""
    from packages.workflows.engine import WorkflowEngine
    try:
        engine = WorkflowEngine(nodes=req.nodes, edges=req.edges)
        result = await engine.run()
        return result
    except Exception as exc:
        logger.error(f"Workflow Run Error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/workflows/save")
async def save_workflow(req: WorkflowSaveRequest):
    """Saves a workflow definition to a local file."""
    try:
        wf_dir = Path(settings.data_dir) / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        file_path = wf_dir / f"{req.name}.json"
        
        with file_path.open("w") as f:
            json.dump({"nodes": req.nodes, "edges": req.edges}, f, indent=2)
            
        return {"status": "saved", "path": str(file_path)}
    except Exception as exc:
        logger.error(f"Workflow Save Error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/workflows/list")
async def list_workflows():
    """Returns a list of all saved workflows."""
    wf_dir = Path(settings.data_dir) / "workflows"
    if not wf_dir.exists():
        return {"workflows": []}
    files = [f.stem for f in wf_dir.glob("*.json")]
    return {"workflows": files}

# ── Local Operations Tool Endpoints ─────────────────────────────────


class ToolExecRequest(BaseModel):
    command: str
    cwd: Optional[str] = None
    timeout: int = 30


class FileReadRequest(BaseModel):
    path: str
    max_lines: Optional[int] = None


class FileWriteRequest(BaseModel):
    path: str
    content: str


class FileSearchRequest(BaseModel):
    directory: str
    pattern: str = "*"
    recursive: bool = True
    max_results: int = 50


class GitRepoRequest(BaseModel):
    repo_path: str
    max_commits: int = 10


class GitDiffRequest(BaseModel):
    repo_path: str
    staged: bool = False
    file_path: Optional[str] = None


@app.get("/tools/list")
async def list_tools():
    """List all available agent tools with their categories."""
    from packages.agents.tools import TOOL_REGISTRY
    return {
        "tools": [
            {
                "name": name,
                "category": info["category"],
                "description": info["description"],
            }
            for name, info in TOOL_REGISTRY.items()
        ],
        "count": len(TOOL_REGISTRY),
    }


@app.post("/tools/fs/read")
async def tool_read_file(req: FileReadRequest):
    """Read a file's contents."""
    from packages.tools.fs import read_file
    result = await read_file(req.path, max_lines=req.max_lines)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/tools/fs/write")
async def tool_write_file(req: FileWriteRequest):
    """Write content to a file."""
    from packages.tools.fs import write_file
    result = await write_file(req.path, req.content)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/tools/fs/search")
async def tool_find_files(req: FileSearchRequest):
    """Search for files matching a pattern."""
    from packages.tools.fs import find_files
    result = await find_files(
        req.directory, pattern=req.pattern,
        recursive=req.recursive, max_results=req.max_results,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/tools/fs/list")
async def tool_list_directory(req: FileReadRequest):
    """List directory contents."""
    from packages.tools.fs import list_directory
    result = await list_directory(req.path)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/tools/git/status")
async def tool_git_status(req: GitRepoRequest):
    """Get git status for a repository."""
    from packages.tools.repo import git_status
    result = await git_status(req.repo_path)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/tools/git/log")
async def tool_git_log(req: GitRepoRequest):
    """Get recent commit history."""
    from packages.tools.repo import git_log
    result = await git_log(req.repo_path, max_commits=req.max_commits)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/tools/git/diff")
async def tool_git_diff(req: GitDiffRequest):
    """Get diff of changes."""
    from packages.tools.repo import git_diff
    result = await git_diff(req.repo_path, staged=req.staged, file_path=req.file_path)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/tools/git/summary")
async def tool_repo_summary(req: GitRepoRequest):
    """Generate a full repo summary (status + log + branches)."""
    from packages.tools.repo import repo_summary
    result = await repo_summary(req.repo_path)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/tools/exec")
async def tool_exec_command(req: ToolExecRequest):
    """Execute a command in a sandboxed subprocess."""
    from packages.tools.exec import run_command
    result = await run_command(
        req.command, cwd=req.cwd, timeout=req.timeout,
    )
    if result.get("blocked"):
        raise HTTPException(status_code=403, detail=result["error"])
    return result


@app.post("/tools/exec/check")
async def tool_check_command(req: ToolExecRequest):
    """Check if a command is allowed, blocked, or requires approval."""
    from packages.tools.exec import check_allowlist
    return check_allowlist(req.command)

# ── Sync Hub Endpoints (Phase K) ─────────────────────────────────────

@app.post("/sync/trigger")
async def trigger_sync():
    """Manually force an export of all Qdrant collections to snapshot files."""
    try:
        from packages.automation.sync import create_qdrant_snapshot
        result = await create_qdrant_snapshot()

        status = result.get("status", "error")
        if status == "error":
            message = result.get("error", "Snapshot export failed")
            raise HTTPException(status_code=500, detail=message)

        return {
            "status": status,
            "message": result.get("message", "Snapshot export completed"),
            "exported": result.get("exported", []),
            "failed": result.get("failed", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sync trigger failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sync/status")
async def sync_status():
    """Get the latest modification timestamp of the snapshot directory."""
    try:
        from pathlib import Path
        from packages.shared.config import settings
        snapshot_dir = Path(settings.data_dir) / "snapshots"
        if not snapshot_dir.exists():
            return {"last_sync": None, "snapshots": []}
            
        snaps = list(snapshot_dir.glob("*.snapshot"))
        if not snaps:
            return {"last_sync": None, "snapshots": []}
            
        latest = max(snaps, key=lambda p: p.stat().st_mtime)
        return {
            "last_sync": latest.stat().st_mtime * 1000, # Convert to ms for JS
            "snapshots": [s.name for s in snaps]
        }
    except Exception as e:
        logger.error(f"Sync status failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ── Static Test Pages ────────────────────────────────────────────────


@app.get("/test")
async def serve_test_page():
    """Serve the original test page."""
    return FileResponse(_STATIC_DIR / "test.html")


@app.get("/prototype")
async def serve_prototype():
    """Serve the full prototype test page."""
    return FileResponse(_STATIC_DIR / "test_prototype.html")



