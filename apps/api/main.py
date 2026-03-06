"""
PersonalAssist — FastAPI Backend
Routes: health, chat (plain/stream/smart), memory, ingest, agents
"""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from packages.shared.config import settings
from packages.model_gateway.client import chat, chat_stream

# Directory containing static test pages
_STATIC_DIR = Path(__file__).parent

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App Setup ────────────────────────────────────────────────────────
app = FastAPI(
    title="PersonalAssist API",
    version="0.2.0",
    description="AI-powered personal assistant with memory & multi-model support",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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


# ── Health ───────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}


# ── Chat Endpoints ───────────────────────────────────────────────────


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """Non-streaming chat via model gateway."""
    messages = [{"role": "user", "content": req.message}]
    try:
        response = await chat(messages, model=req.model, temperature=req.temperature)
        return {"response": response, "model_used": settings.resolve_model(req.model)}
    except Exception as exc:
        logger.error("Chat error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/chat/stream")
async def chat_stream_endpoint(req: ChatRequest):
    """SSE streaming chat via model gateway."""
    messages = [{"role": "user", "content": req.message}]

    async def generate():
        try:
            async for chunk in chat_stream(messages, model=req.model, temperature=req.temperature):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            logger.error("Stream error: %s", exc)
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/chat/smart")
async def chat_smart(req: ChatRequest):
    """
    RAG-enhanced chat with auto-learning.

    1. Retrieves relevant memories AND documents for context
    2. Sends augmented prompt to the LLM
    3. Auto-extracts facts from the conversation into Mem0
    """
    messages = [{"role": "user", "content": req.message}]
    context_prefix = ""
    memory_used = False

    # ── Step 1: Build hybrid context (Mem0 + Qdrant RAG) ─────────
    try:
        from packages.memory.memory_service import build_context
        context = await build_context(req.message, user_id="default")
        if context:
            context_prefix = context
            memory_used = True
    except Exception as exc:
        logger.warning("Memory layer unavailable, proceeding without context: %s", exc)

    # ── Step 2: Call LLM with augmented context ──────────────────
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

    # ── Step 3: Auto-learn from the conversation (non-blocking) ──
    extraction_result = {}
    try:
        from packages.memory.memory_service import extract_and_store_from_turn
        from packages.memory.consolidation import increment_turn, should_consolidate, consolidate_memories
        
        turn_messages = [
            {"role": "user", "content": req.message},
            {"role": "assistant", "content": response},
        ]
        extraction_result = await extract_and_store_from_turn(
            turn_messages, user_id="default",
        )
        
        # Check if consolidation is needed
        increment_turn(user_id="default")
        if should_consolidate(user_id="default"):
            logger.info("Turn threshold reached, triggering memory consolidation")
            # Fire and forget consolidation
            import asyncio
            asyncio.create_task(consolidate_memories(user_id="default", model=req.model))
            
    except Exception as exc:
        logger.warning("Auto-extraction failed (non-fatal): %s", exc)

    return {
        "response": response,
        "model_used": settings.resolve_model(req.model),
        "memory_used": memory_used,
        "memories_extracted": extraction_result,
    }


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
        from packages.agents.base_agent import PlannerAgent
        from packages.agents.crew import run_crew
        
        # We will dispatch to the new lightweight crew orchestration.
        result = await run_crew(
            user_message=req.message,
            user_id="default",
            model=req.model,
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


# ── Local Operations Tool Endpoints ─────────────────────────────────


class ToolExecRequest(BaseModel):
    command: str
    cwd: Optional[str] = None
    timeout: int = 30
    force_approve: bool = False


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
        force_approve=req.force_approve,
    )
    if result.get("blocked"):
        raise HTTPException(status_code=403, detail=result["error"])
    return result


@app.post("/tools/exec/check")
async def tool_check_command(req: ToolExecRequest):
    """Check if a command is allowed, blocked, or requires approval."""
    from packages.tools.exec import check_allowlist
    return check_allowlist(req.command)

# ── Static Test Pages ────────────────────────────────────────────────


@app.get("/test")
async def serve_test_page():
    """Serve the original test page."""
    return FileResponse(_STATIC_DIR / "test.html")


@app.get("/prototype")
async def serve_prototype():
    """Serve the full prototype test page."""
    return FileResponse(_STATIC_DIR / "test_prototype.html")
