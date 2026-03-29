/**
 * Custom React Query Hooks
 * 
 * Hooks for data fetching with TanStack Query.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as api from './api';
import * as workspaceApi from './workspace-api';

// ─────────────────────────────────────────────────────────────────────
// Chat Hooks
// ─────────────────────────────────────────────────────────────────────

export function useChatThreads() {
  return useQuery({
    queryKey: ['chat', 'threads'],
    queryFn: () => api.getChatThreads(),
    staleTime: 1000 * 60, // 1 minute
  });
}

export function useChatThread(threadId: string | null) {
  return useQuery({
    queryKey: ['chat', 'thread', threadId],
    queryFn: () => threadId ? api.getChatThread(threadId) : null,
    enabled: !!threadId,
    staleTime: 1000 * 60,
  });
}

// ─────────────────────────────────────────────────────────────────────
// Memory Hooks
// ─────────────────────────────────────────────────────────────────────

export function useMemories(userId: string = 'default') {
  return useQuery({
    queryKey: ['memory', 'all', userId],
    queryFn: () => api.getAllMemories(userId),
    staleTime: 1000 * 60 * 5,
  });
}

export function useMemoryHealth() {
  return useQuery({
    queryKey: ['memory', 'health'],
    queryFn: () => api.checkMemoryHealth(),
    staleTime: 1000 * 30, // 30 seconds
    retry: 1,
  });
}

// ─────────────────────────────────────────────────────────────────────
// Models Hooks
// ─────────────────────────────────────────────────────────────────────

export function useModels() {
  return useQuery({
    queryKey: ['models'],
    queryFn: () => api.listModels(),
    staleTime: 1000 * 60 * 10, // 10 minutes
  });
}

export function useActiveModel() {
  return useQuery({
    queryKey: ['models', 'active'],
    queryFn: () => api.getActiveModel(),
    staleTime: 1000 * 60 * 5,
  });
}

// ─────────────────────────────────────────────────────────────────────
// Workspace Hooks
// ─────────────────────────────────────────────────────────────────────

export function useWorkspaces() {
  return useQuery({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.listWorkspaces(),
    staleTime: 1000 * 60 * 5,
  });
}

export function useWorkspace(projectId: string | null) {
  return useQuery({
    queryKey: ['workspaces', projectId],
    queryFn: () => projectId ? workspaceApi.getWorkspace(projectId) : null,
    enabled: !!projectId,
    staleTime: 1000 * 60 * 5,
  });
}

export function useWorkspaceAuditLog(projectId: string | null, limit: number = 100) {
  return useQuery({
    queryKey: ['workspaces', projectId, 'audit', limit],
    queryFn: () => projectId ? workspaceApi.getAuditLog(projectId, limit) : null,
    enabled: !!projectId,
    staleTime: 1000 * 30,
  });
}

// ─────────────────────────────────────────────────────────────────────
// Jobs Hooks
// ─────────────────────────────────────────────────────────────────────

export function useJobs(limit: number = 50) {
  return useQuery({
    queryKey: ['jobs', 'list', limit],
    queryFn: () => api.listJobs(limit),
    staleTime: 1000 * 30,
    refetchInterval: 5000, // Refetch every 5 seconds
  });
}

export function useJobStats() {
  return useQuery({
    queryKey: ['jobs', 'stats'],
    queryFn: () => api.getJobStats(),
    staleTime: 1000 * 30,
    refetchInterval: 5000,
  });
}

// ─────────────────────────────────────────────────────────────────────
// Mutation Hooks
// ─────────────────────────────────────────────────────────────────────

export function useDeleteChatThread() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (threadId: string) => api.deleteChatThread(threadId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chat', 'threads'] });
    },
  });
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (workspace: Partial<workspaceApi.Workspace>) => 
      workspaceApi.createWorkspace(workspace),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
}

export function useDeleteWorkspace() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (projectId: string) => workspaceApi.deleteWorkspace(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
}

export function useConsolidateMemories() {
  return useMutation({
    mutationFn: (userId: string = 'default') => api.consolidateMemories(userId),
  });
}
