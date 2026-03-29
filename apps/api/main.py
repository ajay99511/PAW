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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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
    if not settings.api_access_token:
        logger.warning("API_ACCESS_TOKEN is not set. Protected API endpoints are open to local processes.")
    
    # Initialize chat database (required for chat persistence endpoints)
    try:
        from packages.shared.db import init_db
        await init_db()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
        
    scheduler.start()
    try:
        from packages.automation.jobs import setup_jobs
        setup_jobs(scheduler)
    except Exception as e:
        logger.error(f"Failed to setup background jobs: {e}")

    # Register built-in A2A agents so discovery/delegation works after startup.
    try:
        from packages.agents.a2a import register_tier1_agents
        register_tier1_agents()
    except Exception as e:
        logger.error(f"Failed to register A2A agents: {e}")
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

_PUBLIC_PATHS = {"/health", "/test", "/prototype", "/docs", "/redoc", "/openapi.json"}


@app.middleware("http")
async def enforce_api_access_token(request: Request, call_next):
    if not settings.api_access_token or request.url.path in _PUBLIC_PATHS:
        return await call_next(request)

    token = request.headers.get("x-api-token", "")
    if token != settings.api_access_token:
        return JSONResponse(status_code=401, content={"detail": "Invalid API token"})

    return await call_next(request)


# ── Podcast Router (isolated sub-router) ─────────────────────────────
from apps.api.podcast_router import podcast_router
app.include_router(podcast_router)

# ── Workspace Router ──────────────────────────────────────────────────
from apps.api.workspace_router import router as workspace_router
app.include_router(workspace_router)

# ── Job Monitoring Router ─────────────────────────────────────────────
from apps.api.job_router import router as job_router
app.include_router(job_router)

# ── Telegram Webhook Router ───────────────────────────────────────────
try:
    from packages.messaging.telegram_webhook import router as telegram_webhook_router
    app.include_router(telegram_webhook_router)
    logger.info("Telegram webhook router included")
except ImportError as exc:
    logger.warning(f"Telegram webhook router not available: {exc}")

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


def _clip_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


async def _build_thread_messages(session, thread_id: str, system_context: str = "") -> list[dict[str, str]]:
    from sqlalchemy import select
    from packages.memory.models import ChatMessage

    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.timestamp.desc())
        .limit(settings.chat_history_max_messages)
    )
    recent_messages = result.scalars().all()

    selected: list[dict[str, str]] = []
    used_chars = 0
    budget = max(settings.chat_history_char_budget, 1000)

    for item in recent_messages:
        role = item.role if item.role in {"user", "assistant", "system"} else "user"
        content_limit = 1600 if role == "user" else 2200
        content = _clip_text(item.content, content_limit)
        if not content:
            continue
        if selected and used_chars + len(content) > budget:
            break
        selected.append({"role": role, "content": content})
        used_chars += len(content)

    messages = list(reversed(selected))
    if system_context:
        messages.insert(
            0,
            {
                "role": "system",
                "content": _clip_text(system_context, settings.rag_context_char_budget),
            },
        )
    return messages


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
        messages = await _build_thread_messages(session, req.thread_id)

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
        messages = await _build_thread_messages(session, req.thread_id)

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


@app.post("/chat/smart/stream")
async def chat_smart_stream(req: ChatRequest):
    """SSE streaming RAG-enhanced chat with auto-learning and persistence."""
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

    context_prefix = ""
    memory_used = False

    global _ACTIVE_CONTEXT
    if _ACTIVE_CONTEXT:
        context_prefix += _clip_text(
            f"USER'S ACTIVE CONTEXT (IDE/Terminal):\n{json.dumps(_ACTIVE_CONTEXT, indent=2)}\n\n",
            settings.rag_context_char_budget,
        )

    try:
        from packages.memory.memory_service import build_context

        rag_context = await build_context(req.message, user_id="default")
        if rag_context:
            context_prefix += "RETRIEVED KNOWLEDGE AND MEMORIES:\n" + rag_context + "\n"
            memory_used = True
    except Exception as exc:
        logger.warning("Memory layer unavailable, proceeding without context: %s", exc)

    async with AsyncSessionLocal() as session:
        messages = await _build_thread_messages(session, req.thread_id, system_context=context_prefix)

    async def generate():
        full_response = ""
        try:
            yield f"data: {json.dumps({'thread_id': req.thread_id, 'memory_used': memory_used})}\n\n"

            async for chunk in chat_stream(messages, model=req.model, temperature=req.temperature):
                full_response += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield "data: [DONE]\n\n"

            model_used = settings.resolve_model(req.model)
            async with AsyncSessionLocal() as session:
                thread = await _resolve_or_create_thread(session, req.thread_id, req.message)
                assistant_msg = ChatMessage(
                    thread_id=req.thread_id,
                    role="assistant",
                    content=full_response,
                    model_used=model_used,
                    memory_used=memory_used,
                )
                _touch_thread(thread)
                session.add(assistant_msg)
                await session.commit()

            try:
                from packages.memory.memory_service import extract_and_store_from_turn
                from packages.memory.consolidation import consolidate_memories, increment_turn, should_consolidate

                turn_messages = [
                    {"role": "user", "content": req.message},
                    {"role": "assistant", "content": full_response},
                ]
                await extract_and_store_from_turn(turn_messages, user_id="default")

                increment_turn(user_id="default")
                if should_consolidate(user_id="default"):
                    logger.info("Turn threshold reached, triggering memory consolidation")
                    import asyncio

                    asyncio.create_task(consolidate_memories(user_id="default", model=req.model))
            except Exception as exc:
                logger.warning("Auto-extraction failed (non-fatal): %s", exc)

        except Exception as exc:
            logger.error("Smart stream error: %s", exc)
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

    context_prefix = ""
    memory_used = False

    global _ACTIVE_CONTEXT
    if _ACTIVE_CONTEXT:
        context_prefix += _clip_text(
            f"USER'S ACTIVE CONTEXT (IDE/Terminal):\n{json.dumps(_ACTIVE_CONTEXT, indent=2)}\n\n",
            settings.rag_context_char_budget,
        )

    try:
        from packages.memory.memory_service import build_context

        rag_context = await build_context(req.message, user_id="default")
        if rag_context:
            context_prefix += "RETRIEVED KNOWLEDGE AND MEMORIES:\n" + rag_context + "\n"
            memory_used = True
    except Exception as exc:
        logger.warning("Memory layer unavailable, proceeding without context: %s", exc)

    async with AsyncSessionLocal() as session:
        messages = await _build_thread_messages(session, req.thread_id, system_context=context_prefix)

    try:
        response = await chat(messages, model=req.model, temperature=req.temperature)
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
        from packages.memory.consolidation import consolidate_memories, increment_turn, should_consolidate

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


# ── Extended Memory Endpoints (5-Layer System) ────────────────────────


@app.get("/memory/sessions")
async def list_sessions():
    """List all session transcripts."""
    try:
        from packages.memory.jsonl_store import list_sessions
        session_ids = await list_sessions()
        return {"sessions": session_ids, "count": len(session_ids)}
    except Exception as exc:
        logger.error("List sessions error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/memory/sessions/{session_id}")
async def get_session_transcript(session_id: str, limit: int = 100):
    """Get session transcript with optional limit."""
    try:
        from packages.memory.jsonl_store import load_transcript
        entries = await load_transcript(session_id)
        
        # Apply limit
        if limit and len(entries) > limit:
            entries = entries[-limit:]
        
        return {
            "session_id": session_id,
            "entries": entries,
            "count": len(entries),
        }
    except Exception as exc:
        logger.error("Get session error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/memory/bootstrap")
async def get_bootstrap_files():
    """Get bootstrap file contents."""
    try:
        from packages.memory.bootstrap import load_bootstrap_files, get_bootstrap_summary
        summary = await get_bootstrap_summary()
        content = await load_bootstrap_files(agent_type="main")
        
        return {
            "summary": summary,
            "content": content,
        }
    except Exception as exc:
        logger.error("Get bootstrap error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/memory/compaction/history")
async def get_compaction_history(session_id: str | None = None):
    """Get compaction history."""
    try:
        from packages.memory.jsonl_store import list_sessions, load_transcript
        
        if session_id:
            # Get compactions for specific session
            entries = await load_transcript(session_id)
            compactions = [e for e in entries if e.type == "compaction"]
            return {
                "session_id": session_id,
                "compactions": compactions,
                "count": len(compactions),
            }
        else:
            # Get summary across all sessions
            session_ids = await list_sessions()
            total_compactions = 0
            
            for sid in session_ids[:10]:  # Limit to 10 sessions
                entries = await load_transcript(sid)
                compactions = [e for e in entries if e.type == "compaction"]
                total_compactions += len(compactions)
            
            return {
                "total_sessions": len(session_ids),
                "total_compactions": total_compactions,
                "recent_sessions": session_ids[:10],
            }
    except Exception as exc:
        logger.error("Get compaction error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/memory/search")
async def search_ltm(query: str, k: int = 10):
    """Search across all memory layers (Mem0 + Qdrant)."""
    try:
        from packages.memory.memory_service import build_context
        
        # Use build_context which already does hybrid search
        context = await build_context(query, user_id="default", k=k)
        
        return {
            "query": query,
            "context": context,
            "k": k,
        }
    except Exception as exc:
        logger.error("Search LTM error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── A2A Agent Endpoints ───────────────────────────────────────────────


@app.get("/agents/a2a/list")
async def list_a2a_agents():
    """List all registered A2A agents."""
    try:
        from packages.agents.a2a import get_registry
        
        registry = get_registry()
        agents = registry.list_agents()
        
        return {
            "agents": [agent.model_dump() for agent in agents],
            "count": len(agents),
        }
    except Exception as exc:
        logger.error("List A2A agents error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/agents/a2a/{agent_id}")
async def get_agent_card(agent_id: str):
    """Get agent card details."""
    try:
        from packages.agents.a2a import get_registry
        
        registry = get_registry()
        agent = registry.get_agent(agent_id)
        
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        return agent.model_dump()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Get agent error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/agents/a2a/{agent_id}/delegate")
async def delegate_task(agent_id: str, task: dict):
    """Delegate task to an A2A agent."""
    try:
        from packages.agents.a2a import get_registry
        
        registry = get_registry()
        
        # Delegate task
        task_handle = await registry.delegate(agent_id, task)
        
        return {
            "task_id": task_handle.task_id,
            "agent_id": agent_id,
            "status": task_handle.status.value,
        }
    except Exception as exc:
        logger.error("Delegate task error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/agents/a2a/task/{task_id}")
async def get_task_status(task_id: str):
    """Get task status."""
    try:
        from packages.agents.a2a import get_registry
        
        registry = get_registry()
        task_handle = await registry.get_task_status(task_id)
        
        if not task_handle:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return task_handle.model_dump()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Get task status error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/agents/a2a/capabilities")
async def list_capabilities():
    """List all available capabilities."""
    try:
        from packages.agents.a2a import get_registry
        
        registry = get_registry()
        capabilities = registry.list_capabilities()
        
        return {
            "capabilities": capabilities,
            "count": len(capabilities),
        }
    except Exception as exc:
        logger.error("List capabilities error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Telegram Endpoints ────────────────────────────────────────────────


@app.get("/telegram/config")
async def get_telegram_config():
    """Get Telegram configuration."""
    try:
        import os
        return {
            "bot_token_set": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
            "dm_policy": os.getenv("TELEGRAM_DM_POLICY", "pairing"),
            "bot_username": None,  # Would need to fetch from Telegram API
        }
    except Exception as exc:
        logger.error("Get Telegram config error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/telegram/config")
async def update_telegram_config(config: dict):
    """Update Telegram configuration."""
    try:
        # Note: In production, this would update a config file or database
        # For now, we'll just validate the input
        bot_token = config.get("bot_token")
        dm_policy = config.get("dm_policy", "pairing")
        
        if dm_policy not in ["pairing", "allowlist", "open"]:
            raise HTTPException(status_code=400, detail="Invalid DM policy")
        
        return {
            "status": "updated",
            "dm_policy": dm_policy,
            "message": "Configuration updated. Restart required for bot token changes.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Update Telegram config error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/telegram/users")
async def list_telegram_users():
    """List all Telegram users."""
    try:
        from packages.messaging.telegram_bot import get_auth_store
        
        auth_store = get_auth_store()
        users = auth_store.list_users()
        
        return {
            "users": users,
            "count": len(users),
        }
    except Exception as exc:
        logger.error("List Telegram users error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/telegram/users/pending")
async def list_pending_approvals():
    """List pending approval requests."""
    try:
        from packages.messaging.telegram_bot import get_auth_store
        
        auth_store = get_auth_store()
        users = auth_store.list_users()
        pending = [u for u in users if not u.get("approved", False)]
        
        return {
            "pending_users": pending,
            "count": len(pending),
        }
    except Exception as exc:
        logger.error("List pending approvals error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/telegram/users/{telegram_id}/approve")
async def approve_telegram_user(telegram_id: str):
    """Approve Telegram user."""
    try:
        from packages.messaging.telegram_bot import get_auth_store
        
        auth_store = get_auth_store()
        success = auth_store.approve_user(telegram_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "status": "approved",
            "telegram_id": telegram_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Approve Telegram user error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/telegram/test")
async def send_test_message():
    """Send test message to verify bot."""
    try:
        # This would actually send a test message via Telegram API
        # For now, we'll just verify the bot token is set
        import os
        
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            return {
                "status": "error",
                "message": "Bot token not configured",
            }
        
        return {
            "status": "success",
            "message": "Test message would be sent (Telegram API integration required)",
        }
    except Exception as exc:
        logger.error("Send test message error: %s", exc)
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

# ── Static Test Pages ────────────────────────────────────────────────


@app.get("/test")
async def serve_test_page():
    """Serve the original test page."""
    return FileResponse(_STATIC_DIR / "test.html")


@app.get("/prototype")
async def serve_prototype():
    """Serve the full prototype test page."""
    return FileResponse(_STATIC_DIR / "test_prototype.html")






