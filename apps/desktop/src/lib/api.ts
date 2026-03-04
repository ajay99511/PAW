/**
 * PersonalAssist API Client
 *
 * Type-safe HTTP client for all PersonalAssist backend endpoints.
 * Connects to the FastAPI server at localhost:8000.
 */

const API_BASE = "http://127.0.0.1:8000";

// ── Types ──────────────────────────────────────────────────────────

export interface ChatResponse {
  response: string;
  model_used: string;
  memory_used?: boolean;
  memories_extracted?: Record<string, unknown>;
}

export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  is_local: boolean;
  is_active: boolean;
  size_label?: string;
  parameter_count?: string;
}

export interface Memory {
  id: string;
  memory: string;
  content?: string;
  score?: number;
  metadata?: Record<string, unknown>;
}

export interface TraceEvent {
  run_id: string;
  agent_name: string;
  event_type: string;
  content: string;
  timestamp: string;
  metadata: Record<string, unknown>;
}

export interface AgentResult {
  response: string;
  plan: string;
  research: string;
  model_used: string;
  run_id: string;
}

export interface HealthResponse {
  status: string;
  version: string;
}

// ── Helpers ────────────────────────────────────────────────────────

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text().catch(() => "Unknown error");
    throw new Error(`API error ${res.status}: ${err}`);
  }
  return res.json() as Promise<T>;
}

// ── Health ──────────────────────────────────────────────────────────

export async function checkHealth(): Promise<HealthResponse> {
  return api<HealthResponse>("/health");
}

// ── Chat ───────────────────────────────────────────────────────────

export async function chatPlain(
  message: string,
  model: string = "local"
): Promise<ChatResponse> {
  return api<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({ message, model }),
  });
}

export async function chatSmart(
  message: string,
  model: string = "local"
): Promise<ChatResponse> {
  return api<ChatResponse>("/chat/smart", {
    method: "POST",
    body: JSON.stringify({ message, model }),
  });
}

export async function* chatStream(
  message: string,
  model: string = "local"
): AsyncGenerator<string, void, undefined> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, model }),
  });

  if (!res.ok) throw new Error(`Stream error: ${res.status}`);
  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data === "[DONE]") return;
        try {
          const parsed = JSON.parse(data);
          if (parsed.text) yield parsed.text;
          if (parsed.error) throw new Error(parsed.error);
        } catch {
          // non-JSON data line, skip
        }
      }
    }
  }
}

// ── Memory ─────────────────────────────────────────────────────────

export async function getAllMemories(
  userId: string = "default"
): Promise<{ memories: Memory[]; count: number }> {
  return api(`/memory/all?user_id=${encodeURIComponent(userId)}`);
}

export async function forgetMemory(
  memoryId: string
): Promise<{ status: string }> {
  return api("/memory/forget", {
    method: "POST",
    body: JSON.stringify({ memory_id: memoryId }),
  });
}

export async function consolidateMemories(
  userId: string = "default"
): Promise<Record<string, unknown>> {
  return api(`/memory/consolidate?user_id=${encodeURIComponent(userId)}`, {
    method: "POST",
  });
}

export async function checkMemoryHealth(): Promise<{
  status: string;
  qdrant: string;
}> {
  return api("/memory/health");
}

// ── Models ─────────────────────────────────────────────────────────

export async function listModels(): Promise<{ models: ModelInfo[] }> {
  return api("/models");
}

export async function getActiveModel(): Promise<{
  active_model: string;
  model_info: ModelInfo | null;
}> {
  return api("/models/active");
}

export async function switchModel(
  model: string
): Promise<{ status: string; active_model: string }> {
  return api("/models/switch", {
    method: "POST",
    body: JSON.stringify({ model }),
  });
}

// ── Agents ─────────────────────────────────────────────────────────

export async function runAgent(
  message: string,
  model: string = "local"
): Promise<AgentResult> {
  return api("/agents/run", {
    method: "POST",
    body: JSON.stringify({ message, model }),
  });
}

export async function* streamTrace(
  runId: string
): AsyncGenerator<TraceEvent, void, undefined> {
  const res = await fetch(`${API_BASE}/agents/trace/${runId}`);
  if (!res.ok) throw new Error(`Trace error: ${res.status}`);
  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        try {
          yield JSON.parse(data) as TraceEvent;
        } catch {
          // non-JSON line
        }
      }
    }
  }
}
