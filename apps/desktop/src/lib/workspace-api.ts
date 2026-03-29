/**
 * Workspace API Client
 * 
 * Type-safe HTTP client for workspace management endpoints.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

// ── Types ──────────────────────────────────────────────────────────

export interface WorkspacePermissions {
  read: string[];
  write: string[];
  execute: boolean;
  git_operations: boolean;
  network_access: boolean;
}

export interface Workspace {
  project_id: string;
  root: string;
  permissions: WorkspacePermissions;
  context_collection: string;
  agent_instructions: string;
  created_at: string;
  updated_at: string;
}

export interface AuditLogEntry {
  timestamp: string;
  action: string;
  target: string;
  allowed: boolean;
  reason: string;
}

export interface PermissionCheck {
  path: string;
  action: 'read' | 'write' | 'execute';
}

export interface PermissionCheckResult {
  allowed: boolean;
  reason: string;
}

// ── Helpers ────────────────────────────────────────────────────────

function buildHeaders(): Headers {
  const headers = new Headers();
  headers.set("Content-Type", "application/json");
  
  const token = import.meta.env.VITE_API_ACCESS_TOKEN;
  if (token) {
    headers.set("x-api-token", token);
  }
  
  return headers;
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = buildHeaders();
  if (options?.headers) {
    const extraHeaders = new Headers(options.headers);
    extraHeaders.forEach((value, key) => headers.set(key, value));
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  
  if (!res.ok) {
    const err = await res.text().catch(() => "Unknown error");
    throw new Error(`API error ${res.status}: ${err}`);
  }
  
  return res.json() as Promise<T>;
}

// ── Workspace Endpoints ────────────────────────────────────────────

export async function listWorkspaces(): Promise<Workspace[]> {
  return api("/workspaces/list");
}

export async function getWorkspace(projectId: string): Promise<Workspace> {
  return api(`/workspaces/${encodeURIComponent(projectId)}`);
}

export async function createWorkspace(workspace: Partial<Workspace>): Promise<Workspace> {
  return api("/workspaces/create", {
    method: "POST",
    body: JSON.stringify(workspace),
  });
}

export async function updateWorkspace(
  projectId: string,
  updates: Partial<Workspace>,
): Promise<Workspace> {
  return api(`/workspaces/${encodeURIComponent(projectId)}`, {
    method: "PUT",
    body: JSON.stringify(updates),
  });
}

export async function deleteWorkspace(projectId: string): Promise<void> {
  return api(`/workspaces/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
  });
}

export async function getAuditLog(
  projectId: string,
  limit: number = 100,
): Promise<AuditLogEntry[]> {
  const data = await api<{ entries: AuditLogEntry[] }>(
    `/workspaces/${encodeURIComponent(projectId)}/audit?limit=${limit}`
  );
  return data.entries || [];
}

export async function checkPermission(
  projectId: string,
  check: PermissionCheck,
): Promise<PermissionCheckResult> {
  return api(`/workspaces/${encodeURIComponent(projectId)}/check-permission`, {
    method: "POST",
    body: JSON.stringify(check),
  });
}

export async function getWorkspaceStats(projectId: string): Promise<Record<string, unknown>> {
  return api(`/workspaces/${encodeURIComponent(projectId)}/stats`);
}
