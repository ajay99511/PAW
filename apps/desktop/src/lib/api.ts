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

export interface IngestReport {
  files_processed: number;
  chunks_created: number;
  errors: string[];
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

// ── Ingestion ──────────────────────────────────────────────────────

export async function ingestDocument(
  path: string,
  recursive: boolean = true,
  globPatterns?: string[]
): Promise<{ status: string; report: IngestReport }> {
  return api("/ingest", {
    method: "POST",
    body: JSON.stringify({
      path,
      recursive,
      glob_patterns: globPatterns,
    }),
  });
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

// ── Tools ──────────────────────────────────────────────────────────

export interface ToolInfo {
  name: string;
  category: string;
  description: string;
}

export interface FileResult {
  path: string;
  content?: string;
  size_bytes?: number;
  line_count?: number;
  truncated?: boolean;
  error?: string;
}

export interface FileSearchResult {
  directory: string;
  pattern: string;
  matches: Array<{
    path: string;
    name: string;
    extension: string;
    size_bytes?: number;
    modified?: string;
  }>;
  total_found: number;
  truncated: boolean;
}

export interface DirEntry {
  name: string;
  type: "file" | "directory";
  size_bytes?: number;
  modified?: string;
  child_count?: number;
}

export interface DirListResult {
  path: string;
  items: DirEntry[];
  total_items: number;
}

export interface GitStatusResult {
  repo_path: string;
  branch: string;
  modified: string[];
  staged: string[];
  untracked: string[];
  clean: boolean;
}

export interface GitLogResult {
  repo_path: string;
  commits: Array<{ hash: string; message: string; author?: string; date?: string }>;
  count: number;
}

export interface GitDiffResult {
  repo_path: string;
  staged: boolean;
  stat: string;
  diff: string;
  files_changed: number;
}

export interface RepoSummaryResult {
  repo_path: string;
  status: GitStatusResult;
  recent_commits: Array<{ hash: string; message: string }>;
  branches: { current: string; local: string[]; remote: string[] };
}

export interface CommandResult {
  command: string;
  stdout?: string;
  stderr?: string;
  returncode?: number;
  success: boolean;
  timed_out?: boolean;
  blocked?: boolean;
  status?: string;
  message?: string;
  error?: string;
}

export interface CommandCheckResult {
  command: string;
  allowed: boolean;
  blocked: boolean;
  requires_approval: boolean;
}

// Tool discovery
export async function listTools(): Promise<{ tools: ToolInfo[]; count: number }> {
  return api("/tools/list");
}

// File system
export async function toolReadFile(
  path: string, maxLines?: number
): Promise<FileResult> {
  return api("/tools/fs/read", {
    method: "POST",
    body: JSON.stringify({ path, max_lines: maxLines }),
  });
}

export async function toolWriteFile(
  path: string, content: string
): Promise<{ path: string; bytes_written: number; created: boolean }> {
  return api("/tools/fs/write", {
    method: "POST",
    body: JSON.stringify({ path, content }),
  });
}

export async function toolSearchFiles(
  directory: string, pattern: string = "*", recursive: boolean = true
): Promise<FileSearchResult> {
  return api("/tools/fs/search", {
    method: "POST",
    body: JSON.stringify({ directory, pattern, recursive }),
  });
}

export async function toolListDir(path: string): Promise<DirListResult> {
  return api("/tools/fs/list", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

// Git
export async function toolGitStatus(repoPath: string): Promise<GitStatusResult> {
  return api("/tools/git/status", {
    method: "POST",
    body: JSON.stringify({ repo_path: repoPath }),
  });
}

export async function toolGitLog(
  repoPath: string, maxCommits: number = 10
): Promise<GitLogResult> {
  return api("/tools/git/log", {
    method: "POST",
    body: JSON.stringify({ repo_path: repoPath, max_commits: maxCommits }),
  });
}

export async function toolGitDiff(
  repoPath: string, staged: boolean = false
): Promise<GitDiffResult> {
  return api("/tools/git/diff", {
    method: "POST",
    body: JSON.stringify({ repo_path: repoPath, staged }),
  });
}

export async function toolRepoSummary(
  repoPath: string
): Promise<RepoSummaryResult> {
  return api("/tools/git/summary", {
    method: "POST",
    body: JSON.stringify({ repo_path: repoPath }),
  });
}

// Execution
export async function toolExecCommand(
  command: string,
  cwd?: string,
  timeout: number = 30,
  forceApprove: boolean = false
): Promise<CommandResult> {
  return api("/tools/exec", {
    method: "POST",
    body: JSON.stringify({
      command, cwd, timeout, force_approve: forceApprove,
    }),
  });
}

export async function toolCheckCommand(
  command: string
): Promise<CommandCheckResult> {
  return api("/tools/exec/check", {
    method: "POST",
    body: JSON.stringify({ command }),
  });
}

// ── Podcast ────────────────────────────────────────────────────────

export interface PodcastRequest {
  topic: string;
  duration_minutes: number;
  level: "beginner" | "intermediate" | "advanced";
  model?: string;
}

export interface PodcastJob {
  job_id: string;
  topic: string;
  status: string;
  progress_pct: number;
  output_path?: string;
  error?: string;
  created_at: string;
  duration_minutes: number;
  level: string;
}

export async function generatePodcast(
  req: PodcastRequest
): Promise<{ job_id: string; status_url: string }> {
  return api("/api/podcast/generate", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function getPodcastStatus(
  jobId: string
): Promise<PodcastJob> {
  return api(`/api/podcast/status/${jobId}`);
}

export async function listPodcastJobs(): Promise<{ jobs: PodcastJob[]; count: number }> {
  return api("/api/podcast/jobs");
}

export async function* streamPodcastProgress(
  jobId: string
): AsyncGenerator<PodcastJob, void, undefined> {
  const res = await fetch(`${API_BASE}/api/podcast/status/${jobId}/stream`);
  if (!res.ok) throw new Error(`Podcast stream error: ${res.status}`);
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
          yield JSON.parse(data) as PodcastJob;
        } catch {
          // non-JSON line
        }
      }
    }
  }
}

