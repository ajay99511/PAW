"""
Local memory client backed only by Qdrant + Ollama.

This module preserves the historical `mem0_*` API surface so the rest of the
codebase does not need to change, but there is no Mem0 dependency anymore.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    SearchParams,
    VectorParams,
)

from packages.shared.config import settings
from packages.shared.redaction import redact_text

logger = logging.getLogger(__name__)

VECTOR_DIM = 768
COLLECTION = (
    (settings.local_memory_collection or "").strip()
    or (settings.mem0_collection or "").strip()
    or settings.qdrant_collection
)
MEMORY_CONTENT_TYPE = "memory"
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_FIRST_PERSON_RE = re.compile(r"\b(i|i'm|i am|my|we|our)\b", re.IGNORECASE)
_UNCERTAINTY_RE = re.compile(r"\b(maybe|perhaps|guess|not sure|i think)\b", re.IGNORECASE)
_QUESTION_RE = re.compile(r"\?$")
_EMOTION_RE = re.compile(
    r"\b("
    r"happy|sad|angry|upset|anxious|worried|stressed|overwhelmed|burned out|"
    r"excited|frustrated|afraid|lonely|grateful|tired|exhausted|calm|proud|"
    r"depressed|nervous|hopeful|motivated|confident"
    r")\b",
    re.IGNORECASE,
)

_client: QdrantClient | None = None
_client_lock = threading.Lock()

_collection_initialized = False
_indexes_initialized = False
_collection_lock = threading.Lock()

_embed_cache: OrderedDict[str, list[float]] = OrderedDict()
_embed_cache_lock = threading.Lock()

_query_cache: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
_query_cache_lock = threading.Lock()


def _qdrant_client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if (settings.qdrant_url or "").strip():
        kwargs["url"] = settings.qdrant_url.strip()
    else:
        kwargs["host"] = settings.qdrant_host
        kwargs["port"] = settings.qdrant_port
    if (settings.qdrant_api_key or "").strip():
        kwargs["api_key"] = settings.qdrant_api_key.strip()
    return kwargs


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _get_client() -> QdrantClient:
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            _client = QdrantClient(**_qdrant_client_kwargs())
    return _client


def _embed_cache_key(text: str) -> str:
    return f"{settings.embedding_model}\n{text}"


def _get_cached_embedding(text: str) -> list[float] | None:
    key = _embed_cache_key(text)
    with _embed_cache_lock:
        hit = _embed_cache.get(key)
        if hit is None:
            return None
        _embed_cache.move_to_end(key)
        return list(hit)


def _set_cached_embedding(text: str, vector: list[float]) -> None:
    key = _embed_cache_key(text)
    max_entries = max(64, settings.local_memory_embedding_cache_size)
    with _embed_cache_lock:
        _embed_cache[key] = list(vector)
        _embed_cache.move_to_end(key)
        while len(_embed_cache) > max_entries:
            _embed_cache.popitem(last=False)


def _embed(text: str) -> list[float]:
    cached = _get_cached_embedding(text)
    if cached is not None:
        return cached

    url = f"{settings.ollama_api_base}/api/embed"
    payload = {"model": settings.embedding_model, "input": text}
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    embeddings = data.get("embeddings", [])
    if not embeddings:
        raise ValueError("No embeddings returned by Ollama embed endpoint")
    vector = embeddings[0]
    _set_cached_embedding(text, vector)
    return vector


def _ensure_payload_indexes(client: QdrantClient) -> None:
    global _indexes_initialized
    if _indexes_initialized:
        return

    index_fields: list[tuple[str, PayloadSchemaType | str]] = [
        ("content_type", PayloadSchemaType.KEYWORD),
        ("user_id", PayloadSchemaType.KEYWORD),
        ("memory_type", PayloadSchemaType.KEYWORD),
        ("source_role", PayloadSchemaType.KEYWORD),
        ("normalized_hash", PayloadSchemaType.KEYWORD),
        ("timestamp", PayloadSchemaType.DATETIME),
        ("confidence", PayloadSchemaType.FLOAT),
        ("emotional_signal", PayloadSchemaType.BOOL),
        # Full-text payload indexes are best-effort (gracefully skipped if unsupported).
        ("memory", "text"),
        ("content", "text"),
    ]

    for field_name, field_type in index_fields:
        try:
            client.create_payload_index(
                collection_name=COLLECTION,
                field_name=field_name,
                field_schema=field_type,
                wait=True,
            )
        except Exception as exc:
            logger.debug("Payload index setup skipped for %s: %s", field_name, exc)

    _indexes_initialized = True


def _ensure_collection(vector_dim: int = VECTOR_DIM) -> None:
    global _collection_initialized
    if _collection_initialized and _indexes_initialized:
        return

    with _collection_lock:
        if _collection_initialized and _indexes_initialized:
            return

        client = _get_client()
        collections = client.get_collections().collections
        existing = {c.name for c in collections}
        if COLLECTION not in existing:
            client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=vector_dim, distance=Distance.COSINE),
            )
            logger.info("Created local-memory Qdrant collection: %s", COLLECTION)
        else:
            try:
                info = client.get_collection(collection_name=COLLECTION)
                vectors_cfg = getattr(getattr(info, "config", None), "params", None)
                vectors_cfg = getattr(vectors_cfg, "vectors", None)

                existing_dim: int | None = None
                if vectors_cfg is not None:
                    if hasattr(vectors_cfg, "size"):
                        existing_dim = int(getattr(vectors_cfg, "size"))
                    elif isinstance(vectors_cfg, dict):
                        first = (
                            vectors_cfg.get("") if "" in vectors_cfg else next(iter(vectors_cfg.values()), None)
                        )
                        if hasattr(first, "size"):
                            existing_dim = int(getattr(first, "size"))
                        elif isinstance(first, dict) and "size" in first:
                            existing_dim = int(first["size"])

                if existing_dim and existing_dim != vector_dim:
                    logger.warning(
                        "Qdrant vector dim mismatch for %s: collection=%s embedding=%s. "
                        "Use matching EMBEDDING_MODEL or rebuild this collection.",
                        COLLECTION,
                        existing_dim,
                        vector_dim,
                    )
            except Exception as exc:
                logger.debug("Could not validate vector dimensions for %s: %s", COLLECTION, exc)

        _collection_initialized = True
        _ensure_payload_indexes(client)


def _normalize_text(text: str) -> str:
    lowered = (text or "").lower()
    lowered = re.sub(r"\s+", " ", lowered)
    lowered = re.sub(r"[^\w\s]", "", lowered)
    return lowered.strip()


def _tokenize(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall((text or "").lower()) if token}


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _sanitize_text_for_storage(text: str) -> tuple[str, int]:
    redacted, redaction_count = redact_text(text.strip())
    return redacted.strip(), redaction_count


def _serialize_messages(messages: list[dict[str, str]] | str, *, user_only: bool) -> str:
    if isinstance(messages, str):
        return messages.strip()

    lines: list[str] = []
    for msg in messages:
        role = str(msg.get("role", "user")).strip() or "user"
        if user_only and role.lower() != "user":
            continue
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines).strip()


def _infer_memory_type(text: str) -> str:
    lowered = text.lower()
    if any(k in lowered for k in ("prefer", "favorite", "i like", "i am", "i'm", "my name")):
        return "PROFILE"
    if any(k in lowered for k in ("project", "repo", "workspace", "building", "working on")):
        return "PROJECT"
    if any(k in lowered for k in ("completed", "finished", "resolved", "fixed", "shipped")):
        return "TASK_OUTCOME"
    return "EPISODE"


def _is_emotional_text(text: str) -> bool:
    return bool(_EMOTION_RE.search(text or ""))


def _is_emotional_query(text: str) -> bool:
    return _is_emotional_text(text)


def _estimate_confidence(memory_text: str, memory_type: str, source_role: str = "user") -> float:
    score = 0.52
    lowered = (memory_text or "").lower().strip()

    if _FIRST_PERSON_RE.search(lowered):
        score += 0.18
    if any(k in lowered for k in ("always", "usually", "prefer", "need", "working on", "my ")):
        score += 0.12
    if memory_type in {"PROFILE", "PROJECT"}:
        score += 0.06
    if source_role == "user":
        score += 0.08
    if _UNCERTAINTY_RE.search(lowered):
        score -= 0.12
    if _QUESTION_RE.search(lowered):
        score -= 0.18
    if len(lowered) < 18:
        score -= 0.07
    if len(lowered) > 260:
        score -= 0.05

    return _clamp(score, 0.0, 1.0)


def _parse_json_payload(raw: str) -> dict[str, Any] | list[Any] | None:
    text = (raw or "").strip()
    if not text:
        return None

    candidates: list[str] = [text]

    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1).strip())

    first_obj = text.find("{")
    last_obj = text.rfind("}")
    if first_obj != -1 and last_obj > first_obj:
        candidates.append(text[first_obj : last_obj + 1])

    first_arr = text.find("[")
    last_arr = text.rfind("]")
    if first_arr != -1 and last_arr > first_arr:
        candidates.append(text[first_arr : last_arr + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            continue
    return None


def _extract_with_local_model(conversation: str, limit: int = 6) -> list[dict[str, Any]]:
    model = settings.default_local_model.replace("ollama/", "")
    prompt = (
        "Extract durable user/project memories from the USER conversation snippets.\n"
        "Return strict JSON only in this exact schema:\n"
        '{"memories":[{"memory":"...", "memory_type":"PROFILE|PROJECT|EPISODE|TASK_OUTCOME", '
        '"confidence":0.0, "emotional_signal":false, "evidence":"..."}]}\n'
        "Rules:\n"
        "- Keep only stable or high-value facts likely useful in future conversations.\n"
        "- Ignore questions, uncertain speculation, and assistant-generated assumptions.\n"
        "- Keep memory text under 180 characters.\n"
        f"- Return at most {limit} memories.\n\n"
        f"USER conversation snippets:\n{_clip_text(conversation, 6000)}"
    )

    url = f"{settings.ollama_api_base}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }

    try:
        with httpx.Client(timeout=45) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.debug("Local memory extraction model unavailable: %s", exc)
        return []

    parsed = _parse_json_payload(str(data.get("response", "")).strip())
    if parsed is None:
        return []

    raw_memories: list[Any] = list(parsed.get("memories", [])) if isinstance(parsed, dict) else list(parsed)

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_memories:
        if isinstance(item, str):
            text = item.strip()
            mem_type = _infer_memory_type(text)
            confidence = _estimate_confidence(text, mem_type, source_role="user")
            emotional_signal = _is_emotional_text(text)
            evidence = text
        elif isinstance(item, dict):
            text = str(item.get("memory", item.get("content", ""))).strip()
            mem_type = str(item.get("memory_type", _infer_memory_type(text))).strip().upper()
            confidence = float(item.get("confidence", _estimate_confidence(text, mem_type, source_role="user")))
            emotional_signal = bool(item.get("emotional_signal", _is_emotional_text(text)))
            evidence = str(item.get("evidence", text)).strip()
        else:
            continue

        if not text:
            continue
        if len(text) < 12:
            continue
        if _QUESTION_RE.search(text):
            continue
        if len(text) > 260:
            text = _clip_text(text, 260)
        if mem_type not in {"PROFILE", "PROJECT", "EPISODE", "TASK_OUTCOME"}:
            mem_type = _infer_memory_type(text)
        confidence = _clamp(confidence, 0.0, 1.0)

        key = _normalize_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "memory": text,
                "memory_type": mem_type,
                "confidence": confidence,
                "emotional_signal": emotional_signal,
                "source_role": "user",
                "evidence": _clip_text(evidence or text, 220),
            }
        )
        if len(out) >= limit:
            break

    return out


def _extract_with_heuristics(messages: list[dict[str, str]] | str, limit: int = 6) -> list[dict[str, Any]]:
    if isinstance(messages, str):
        candidates = re.split(r"[\n\r]+|(?<=[.!?])\s+", messages)
    else:
        user_lines = [
            str(msg.get("content", "")).strip()
            for msg in messages
            if str(msg.get("role", "")).lower() == "user" and str(msg.get("content", "")).strip()
        ]
        candidates: list[str] = []
        for line in user_lines:
            candidates.extend(re.split(r"[\n\r]+|(?<=[.!?])\s+", line))

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sentence in candidates:
        text = sentence.strip(" \t-•")
        if not text:
            continue
        if len(text) < 14 or len(text) > 240:
            continue
        if _QUESTION_RE.search(text):
            continue
        lowered = text.lower()
        if not any(
            token in lowered
            for token in (
                "i ",
                "i'm",
                "i am",
                "my ",
                "we ",
                "project",
                "repo",
                "working on",
                "prefer",
                "like",
                "need",
            )
        ):
            continue

        key = _normalize_text(text)
        if key in seen:
            continue
        seen.add(key)

        mem_type = _infer_memory_type(text)
        out.append(
            {
                "memory": text,
                "memory_type": mem_type,
                "confidence": _estimate_confidence(text, mem_type, source_role="user"),
                "emotional_signal": _is_emotional_text(text),
                "source_role": "user",
                "evidence": _clip_text(text, 220),
            }
        )
        if len(out) >= limit:
            break

    return out


def _extract_candidate_memories(messages: list[dict[str, str]] | str, limit: int = 6) -> list[dict[str, Any]]:
    # Safety: memory extraction should prefer user-authored statements.
    conversation = _serialize_messages(messages, user_only=True)
    if not conversation:
        return []

    extracted = _extract_with_local_model(conversation, limit=limit)
    if not extracted:
        extracted = _extract_with_heuristics(messages, limit=limit)

    # Dedupe candidates by normalized text, keep the highest-confidence version.
    by_key: dict[str, dict[str, Any]] = {}
    for item in extracted:
        text = str(item.get("memory", "")).strip()
        key = _normalize_text(text)
        if not key:
            continue
        existing = by_key.get(key)
        if existing is None or float(item.get("confidence", 0.0)) > float(existing.get("confidence", 0.0)):
            by_key[key] = item
    return list(by_key.values())[:limit]


def _memory_filter(user_id: str) -> Filter:
    return Filter(
        must=[
            FieldCondition(key="content_type", match=MatchValue(value=MEMORY_CONTENT_TYPE)),
            FieldCondition(key="user_id", match=MatchValue(value=user_id)),
        ]
    )


def _memory_hash_filter(user_id: str, normalized_hash: str) -> Filter:
    return Filter(
        must=[
            FieldCondition(key="content_type", match=MatchValue(value=MEMORY_CONTENT_TYPE)),
            FieldCondition(key="user_id", match=MatchValue(value=user_id)),
            FieldCondition(key="normalized_hash", match=MatchValue(value=normalized_hash)),
        ]
    )


def _point_id(user_id: str, text: str, memory_type: str) -> str:
    norm = _normalize_text(text)
    seed = f"{user_id}|{memory_type}|{norm}"
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def _memory_recency_score(timestamp_iso: str | None, half_life_days: float) -> float:
    if not timestamp_iso:
        return 1.0
    try:
        ts = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
    except Exception:
        return 1.0

    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    if half_life_days <= 0:
        return 1.0
    return math.exp(-(math.log(2) / half_life_days) * age_days)


def _memory_type_weight(memory_type: str) -> float:
    mapping = {
        "PROFILE": 1.06,
        "PROJECT": 1.03,
        "TASK_OUTCOME": 1.0,
        "EPISODE": 0.98,
    }
    return mapping.get(memory_type.upper(), 1.0)


def _apply_mmr(results: list[dict[str, Any]], limit: int, lambda_weight: float) -> list[dict[str, Any]]:
    if len(results) <= 1:
        return results[:limit]

    selected: list[dict[str, Any]] = []
    remaining = list(results)
    lambda_weight = _clamp(lambda_weight, 0.0, 1.0)

    token_cache = {
        item["id"]: _tokenize(str(item.get("memory", item.get("content", "")))) for item in remaining
    }

    while remaining and len(selected) < limit:
        best: dict[str, Any] | None = None
        best_score = -float("inf")

        for candidate in remaining:
            rel = float(candidate.get("_hybrid_score", candidate.get("score", 0.0)))
            max_sim = 0.0
            c_tokens = token_cache.get(candidate["id"], set())
            for chosen in selected:
                s_tokens = token_cache.get(chosen["id"], set())
                max_sim = max(max_sim, _jaccard_similarity(c_tokens, s_tokens))

            mmr_score = lambda_weight * rel - (1 - lambda_weight) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best = candidate

        if best is None:
            break
        selected.append(best)
        remaining = [row for row in remaining if row["id"] != best["id"]]

    return selected


_PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore (all|any|previous|above|prior) instructions", re.IGNORECASE),
    re.compile(r"do not follow (the )?(system|developer)", re.IGNORECASE),
    re.compile(r"system prompt", re.IGNORECASE),
    re.compile(r"developer message", re.IGNORECASE),
    re.compile(r"<\s*(system|assistant|developer|tool|function)\b", re.IGNORECASE),
    re.compile(r"\b(run|execute|call|invoke)\b.{0,40}\b(tool|command)\b", re.IGNORECASE),
)


def _looks_like_prompt_injection(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _PROMPT_INJECTION_PATTERNS)


def _query_cache_key(user_id: str, query: str, limit: int) -> str:
    return f"{user_id}\n{max(1, limit)}\n{_normalize_text(query)}"


def _get_cached_query(cache_key: str) -> list[dict[str, Any]] | None:
    ttl = max(1, settings.local_memory_query_cache_ttl_seconds)
    with _query_cache_lock:
        cached = _query_cache.get(cache_key)
        if cached is None:
            return None
        ts, results = cached
        if (time.time() - ts) > ttl:
            _query_cache.pop(cache_key, None)
            return None
        _query_cache.move_to_end(cache_key)
        # Deep copy to avoid external mutation of cached entries.
        return json.loads(json.dumps(results))


def _set_cached_query(cache_key: str, results: list[dict[str, Any]]) -> None:
    max_entries = max(32, settings.local_memory_query_cache_size)
    with _query_cache_lock:
        _query_cache[cache_key] = (time.time(), json.loads(json.dumps(results)))
        _query_cache.move_to_end(cache_key)
        while len(_query_cache) > max_entries:
            _query_cache.popitem(last=False)


def _invalidate_user_query_cache(user_id: str) -> None:
    prefix = f"{user_id}\n"
    with _query_cache_lock:
        stale_keys = [key for key in _query_cache.keys() if key.startswith(prefix)]
        for key in stale_keys:
            _query_cache.pop(key, None)


def _sanitize_metadata(metadata: dict[str, Any] | None, *, max_depth: int = 3) -> dict[str, Any]:
    if not metadata:
        return {}

    def _sanitize(value: Any, depth: int) -> Any:
        if depth > max_depth:
            return str(value)[:200]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return _clip_text(value.strip(), 500)
        if isinstance(value, list):
            return [_sanitize(item, depth + 1) for item in value[:30]]
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for idx, (k, v) in enumerate(value.items()):
                if idx >= 40:
                    break
                key = _clip_text(str(k).strip(), 80)
                if not key:
                    continue
                out[key] = _sanitize(v, depth + 1)
            return out
        return _clip_text(str(value), 200)

    return _sanitize(metadata, 0) if isinstance(metadata, dict) else {}


def _normalize_vector_score(raw_score: float) -> float:
    value = float(raw_score)
    if -1.0 <= value <= 1.0:
        return (value + 1.0) / 2.0
    if 0.0 <= value <= 2.0:
        return value / 2.0
    if value <= 0.0:
        return 0.0
    return _clamp(math.tanh(value / 4.0), 0.0, 1.0)


def _search_points(
    query_vector: list[float],
    *,
    user_id: str,
    limit: int,
) -> list[Any]:
    client = _get_client()
    safe_limit = max(1, min(200, limit))
    ef = max(16, settings.local_memory_search_ef)

    try:
        return client.search(
            collection_name=COLLECTION,
            query_vector=query_vector,
            query_filter=_memory_filter(user_id),
            limit=safe_limit,
            with_payload=True,
            with_vectors=False,
            search_params=SearchParams(hnsw_ef=ef, exact=False),
        )
    except TypeError:
        # Backward compatibility with older client signatures.
        return client.search(
            collection_name=COLLECTION,
            query_vector=query_vector,
            query_filter=_memory_filter(user_id),
            limit=safe_limit,
            with_payload=True,
            with_vectors=False,
        )


def _payload_to_memory_result(
    *,
    point_id: str,
    payload: dict[str, Any],
    score: float | None,
    vector_score: float | None = None,
    lexical_score: float | None = None,
) -> dict[str, Any]:
    memory_text = str(payload.get("memory", payload.get("content", ""))).strip()
    metadata = {
        "memory_type": payload.get("memory_type", "EPISODE"),
        "timestamp": payload.get("timestamp"),
        "confidence": float(payload.get("confidence", 0.5)),
        "content_type": payload.get("content_type", MEMORY_CONTENT_TYPE),
        "source_role": payload.get("source_role", "user"),
        "emotional_signal": bool(payload.get("emotional_signal", False)),
        "agent_id": payload.get("agent_id"),
        "evidence": payload.get("evidence"),
        "redaction_count": int(payload.get("redaction_count", 0) or 0),
        "metadata": payload.get("metadata", {}),
    }
    if vector_score is not None:
        metadata["vector_score"] = vector_score
    if lexical_score is not None:
        metadata["lexical_score"] = lexical_score

    return {
        "id": point_id,
        "memory": memory_text,
        "content": memory_text,
        "user_id": str(payload.get("user_id", "default")),
        "score": score,
        "metadata": metadata,
        "created_at": payload.get("timestamp"),
    }


def _find_existing_hash(client: QdrantClient, *, user_id: str, normalized_hash: str) -> Any | None:
    points, _ = client.scroll(
        collection_name=COLLECTION,
        scroll_filter=_memory_hash_filter(user_id, normalized_hash),
        limit=1,
        with_payload=True,
        with_vectors=False,
    )
    return points[0] if points else None


def mem0_add(
    messages: list[dict[str, str]] | str,
    user_id: str = "default",
    agent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Extract and store durable memories in local Qdrant.

    Keeps API compatibility with legacy mem0-based call sites.
    """
    _ensure_collection(vector_dim=settings.local_memory_vector_dim)
    client = _get_client()

    max_extract = max(1, settings.local_memory_max_extract_per_add)
    candidates = _extract_candidate_memories(messages, limit=max_extract)
    if not candidates and isinstance(messages, str):
        text = messages.strip()
        if text and not _QUESTION_RE.search(text):
            fallback_type = _infer_memory_type(text)
            candidates = [
                {
                    "memory": text,
                    "memory_type": fallback_type,
                    "confidence": _estimate_confidence(text, fallback_type, source_role="user"),
                    "emotional_signal": _is_emotional_text(text),
                    "source_role": "user",
                    "evidence": _clip_text(text, 220),
                }
            ]

    if not candidates:
        return {
            "status": "ok",
            "extracted": 0,
            "stored": 0,
            "duplicates": 0,
            "skipped_low_confidence": 0,
            "skipped_injection": 0,
            "skipped_embedding_errors": 0,
            "results": [],
        }

    min_conf = _clamp(settings.local_memory_min_confidence, 0.0, 1.0)
    dedupe_threshold = _clamp(settings.local_memory_semantic_dedupe_threshold, 0.0, 1.0)
    sanitized_metadata = _sanitize_metadata(metadata)

    stored: list[dict[str, Any]] = []
    duplicates = 0
    skipped_low_confidence = 0
    skipped_injection = 0
    skipped_embedding_errors = 0

    for candidate in candidates:
        raw_text = str(candidate.get("memory", "")).strip()
        if not raw_text:
            continue
        if _looks_like_prompt_injection(raw_text):
            skipped_injection += 1
            continue

        raw_text = _clip_text(raw_text, settings.local_memory_max_chars)
        redacted_text, redaction_count = _sanitize_text_for_storage(raw_text)
        if not redacted_text:
            continue
        if len(redacted_text) < 8:
            continue
        if _QUESTION_RE.search(redacted_text):
            continue

        memory_type = str(candidate.get("memory_type", _infer_memory_type(redacted_text))).upper().strip()
        if memory_type not in {"PROFILE", "PROJECT", "EPISODE", "TASK_OUTCOME"}:
            memory_type = _infer_memory_type(redacted_text)

        source_role = str(candidate.get("source_role", "user")).strip().lower() or "user"
        confidence = float(
            candidate.get(
                "confidence",
                _estimate_confidence(redacted_text, memory_type, source_role=source_role),
            )
        )
        confidence = _clamp(confidence, 0.0, 1.0)
        if confidence < min_conf:
            skipped_low_confidence += 1
            continue

        norm_text = _normalize_text(redacted_text)
        if not norm_text:
            continue
        normalized_hash = hashlib.sha256(norm_text.encode()).hexdigest()

        if _find_existing_hash(client, user_id=user_id, normalized_hash=normalized_hash):
            duplicates += 1
            continue

        try:
            vector = _embed(redacted_text)
        except Exception as exc:
            logger.warning("Skipping memory candidate due to embed failure: %s", exc)
            skipped_embedding_errors += 1
            continue
        near_hits = _search_points(
            vector,
            user_id=user_id,
            limit=max(2, settings.local_memory_dedupe_probe_limit),
        )
        is_semantic_duplicate = False
        new_tokens = _tokenize(redacted_text)
        for hit in near_hits:
            hit_payload = hit.payload or {}
            existing_text = str(hit_payload.get("memory", hit_payload.get("content", ""))).strip()
            if not existing_text:
                continue
            sim = _normalize_vector_score(float(getattr(hit, "score", 0.0) or 0.0))
            lexical = _jaccard_similarity(new_tokens, _tokenize(existing_text))
            if sim >= dedupe_threshold and lexical >= 0.72:
                is_semantic_duplicate = True
                break
            if _normalize_text(existing_text) == norm_text:
                is_semantic_duplicate = True
                break
        if is_semantic_duplicate:
            duplicates += 1
            continue

        now_iso = _now_iso()
        memory_id = _point_id(user_id, redacted_text, memory_type)
        payload: dict[str, Any] = {
            "content_type": MEMORY_CONTENT_TYPE,
            "user_id": user_id,
            "agent_id": agent_id or "",
            "memory": redacted_text,
            "content": redacted_text,
            "memory_type": memory_type,
            "timestamp": now_iso,
            "updated_at": now_iso,
            "confidence": confidence,
            "emotional_signal": bool(candidate.get("emotional_signal", _is_emotional_text(redacted_text))),
            "source_role": source_role,
            "normalized_hash": normalized_hash,
            "evidence": _clip_text(str(candidate.get("evidence", redacted_text)).strip(), 220),
            "redaction_count": int(redaction_count),
            "metadata": sanitized_metadata,
        }

        client.upsert(
            collection_name=COLLECTION,
            points=[PointStruct(id=memory_id, vector=vector, payload=payload)],
            wait=True,
        )

        stored.append(
            _payload_to_memory_result(
                point_id=memory_id,
                payload=payload,
                score=None,
            )
        )

    if stored:
        _invalidate_user_query_cache(user_id)

    return {
        "status": "ok",
        "extracted": len(candidates),
        "stored": len(stored),
        "duplicates": duplicates,
        "skipped_low_confidence": skipped_low_confidence,
        "skipped_injection": skipped_injection,
        "skipped_embedding_errors": skipped_embedding_errors,
        "results": stored,
    }


def mem0_search(
    query: str,
    user_id: str = "default",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Hybrid memory search over local Qdrant-only long-term memory.
    """
    query = (query or "").strip()
    if not query:
        return []

    _ensure_collection(vector_dim=settings.local_memory_vector_dim)

    safe_limit = max(1, min(30, limit))
    cache_key = _query_cache_key(user_id, query, safe_limit)
    cached = _get_cached_query(cache_key)
    if cached is not None:
        return cached[:safe_limit]

    try:
        query_vector = _embed(query)
    except Exception as exc:
        logger.warning("Local memory search embedding failed: %s", exc)
        return []
    candidate_multiplier = max(1, settings.local_memory_candidate_multiplier)
    candidate_limit = max(safe_limit, min(200, safe_limit * candidate_multiplier))
    query_tokens = _tokenize(query)
    emotional_query = _is_emotional_query(query)

    vector_weight = _clamp(settings.local_memory_vector_weight, 0.0, 1.0)
    lexical_weight = _clamp(settings.local_memory_lexical_weight, 0.0, 1.0)
    recency_weight = _clamp(settings.local_memory_recency_weight, 0.0, 1.0)
    confidence_weight = _clamp(settings.local_memory_confidence_weight, 0.0, 1.0)
    weight_sum = max(0.0001, vector_weight + lexical_weight + recency_weight + confidence_weight)

    try:
        hits = _search_points(query_vector, user_id=user_id, limit=candidate_limit)
    except Exception as exc:
        logger.warning("Local memory search failed against Qdrant: %s", exc)
        return []
    ranked: list[dict[str, Any]] = []

    for hit in hits:
        payload = hit.payload or {}
        memory_text = str(payload.get("memory", payload.get("content", ""))).strip()
        if not memory_text:
            continue

        confidence = _clamp(float(payload.get("confidence", 0.5)), 0.0, 1.0)
        if confidence < (settings.local_memory_min_confidence * 0.6):
            continue

        vector_score = _normalize_vector_score(float(getattr(hit, "score", 0.0) or 0.0))
        lexical_score = _jaccard_similarity(query_tokens, _tokenize(memory_text))
        recency_score = _memory_recency_score(
            payload.get("timestamp"),
            max(1.0, float(settings.local_memory_recency_half_life_days)),
        )
        type_weight = _memory_type_weight(str(payload.get("memory_type", "EPISODE")))
        emotional_bonus = 0.05 if emotional_query and bool(payload.get("emotional_signal", False)) else 0.0

        blended = (
            (vector_weight * vector_score)
            + (lexical_weight * lexical_score)
            + (recency_weight * recency_score)
            + (confidence_weight * confidence)
        ) / weight_sum
        hybrid_score = _clamp((blended * type_weight) + emotional_bonus, 0.0, 1.2)

        row = _payload_to_memory_result(
            point_id=str(hit.id),
            payload=payload,
            score=hybrid_score,
            vector_score=vector_score,
            lexical_score=lexical_score,
        )
        row["_hybrid_score"] = hybrid_score
        ranked.append(row)

    ranked.sort(key=lambda item: float(item.get("_hybrid_score", 0.0)), reverse=True)

    if settings.local_memory_mmr_enabled:
        ranked = _apply_mmr(
            ranked,
            limit=safe_limit,
            lambda_weight=float(settings.local_memory_mmr_lambda),
        )

    final = ranked[:safe_limit]
    for item in final:
        item.pop("_hybrid_score", None)
    _set_cached_query(cache_key, final)
    return final


def mem0_get_all(user_id: str = "default") -> list[dict[str, Any]]:
    """
    Get all stored memories for a user (most recent first).
    """
    _ensure_collection(vector_dim=settings.local_memory_vector_dim)
    client = _get_client()

    offset: Any = None
    collected: list[dict[str, Any]] = []
    page_size = max(32, min(256, settings.local_memory_scroll_page_size))

    while True:
        points, next_offset = client.scroll(
            collection_name=COLLECTION,
            scroll_filter=_memory_filter(user_id),
            with_payload=True,
            with_vectors=False,
            limit=page_size,
            offset=offset,
        )
        for point in points:
            payload = point.payload or {}
            collected.append(
                _payload_to_memory_result(
                    point_id=str(point.id),
                    payload=payload,
                    score=None,
                )
            )

        if next_offset is None:
            break
        offset = next_offset

    collected.sort(
        key=lambda item: str(item.get("metadata", {}).get("timestamp") or item.get("created_at") or ""),
        reverse=True,
    )
    return collected


def mem0_update(memory_id: str, data: str) -> dict[str, Any]:
    """
    Update memory content and vector for a specific memory ID.
    """
    _ensure_collection(vector_dim=settings.local_memory_vector_dim)
    client = _get_client()

    memory_id = str(memory_id).strip()
    if not memory_id:
        raise ValueError("memory_id is required")

    redacted_text, redaction_count = _sanitize_text_for_storage(str(data or ""))
    if not redacted_text:
        raise ValueError("Memory update text is empty after sanitization")
    if _looks_like_prompt_injection(redacted_text):
        raise ValueError("Memory update rejected due to prompt-injection pattern")

    found = client.retrieve(
        collection_name=COLLECTION,
        ids=[memory_id],
        with_payload=True,
        with_vectors=False,
    )
    if not found:
        return {"status": "not_found", "memory_id": memory_id}

    current = found[0]
    payload = dict(current.payload or {})
    user_id = str(payload.get("user_id", "default"))
    memory_type = str(payload.get("memory_type", _infer_memory_type(redacted_text)))
    source_role = str(payload.get("source_role", "user"))
    confidence = _estimate_confidence(redacted_text, memory_type, source_role=source_role)
    confidence = _clamp(confidence, settings.local_memory_min_confidence, 1.0)

    try:
        vector = _embed(redacted_text)
    except Exception as exc:
        logger.warning("Memory update embedding failed: %s", exc)
        return {"status": "error", "memory_id": memory_id, "error": str(exc)}
    now_iso = _now_iso()
    payload.update(
        {
            "memory": _clip_text(redacted_text, settings.local_memory_max_chars),
            "content": _clip_text(redacted_text, settings.local_memory_max_chars),
            "memory_type": memory_type,
            "confidence": confidence,
            "emotional_signal": _is_emotional_text(redacted_text),
            "normalized_hash": hashlib.sha256(_normalize_text(redacted_text).encode()).hexdigest(),
            "updated_at": now_iso,
            "timestamp": payload.get("timestamp") or now_iso,
            "redaction_count": int(payload.get("redaction_count", 0) or 0) + int(redaction_count),
        }
    )

    client.upsert(
        collection_name=COLLECTION,
        points=[PointStruct(id=memory_id, vector=vector, payload=payload)],
        wait=True,
    )
    _invalidate_user_query_cache(user_id)
    return {"status": "updated", "memory_id": memory_id}


def mem0_delete(memory_id: str) -> dict[str, Any]:
    """
    Delete a memory by ID.
    """
    _ensure_collection(vector_dim=settings.local_memory_vector_dim)
    client = _get_client()

    memory_id = str(memory_id).strip()
    if not memory_id:
        raise ValueError("memory_id is required")

    found = client.retrieve(
        collection_name=COLLECTION,
        ids=[memory_id],
        with_payload=True,
        with_vectors=False,
    )
    user_id = "default"
    if found:
        user_id = str((found[0].payload or {}).get("user_id", "default"))

    client.delete(
        collection_name=COLLECTION,
        points_selector=PointIdsList(points=[memory_id]),
        wait=True,
    )
    _invalidate_user_query_cache(user_id)
    return {"status": "deleted", "memory_id": memory_id}
