import { useCallback, useEffect, useRef, useState } from "react";
import {
  HISTORY_THREADS_API_URL,
  HISTORY_THREAD_API_URL,
  HISTORY_ASSETS_API_URL,
  HISTORY_PRUNE_API_URL,
} from "../lib/config";

export interface HistoryThreadSummary {
  thread_id: string;
  message_count: number;
  first_at: string;
  last_at: string;
}

export interface HistoryMessageRecord {
  role: string;
  content: string;
  created_at: string;
}

export interface HistoryAssetRecord {
  asset_id: string;
  thread_id: string | null;
  prompt?: string | null;
  image_path?: string | null;
  metadata?: Record<string, any>;
  created_at: string;
}

export function useHistory() {
  const [threads, setThreads] = useState<HistoryThreadSummary[]>([]);
  const [selectedThread, setSelectedThread] = useState<string | null>(null);
  const [messages, setMessages] = useState<HistoryMessageRecord[]>([]);
  const [assets, setAssets] = useState<HistoryAssetRecord[]>([]);
  const [loadingThreads, setLoadingThreads] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingAssets, setLoadingAssets] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchThreads = useCallback(async () => {
    setLoadingThreads(true);
    setError(null);
    try {
      const res = await fetch(`${HISTORY_THREADS_API_URL}?limit=100`);
      if (!res.ok) throw new Error(`Failed threads (${res.status})`);
      const payload = await res.json();
      setThreads(Array.isArray(payload.threads) ? payload.threads : []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingThreads(false);
    }
  }, []);

  const fetchMessages = useCallback(async (threadId: string) => {
    setLoadingMessages(true);
    setError(null);
    try {
      const res = await fetch(`${HISTORY_THREAD_API_URL(threadId)}?limit=500`);
      if (!res.ok) throw new Error(`Failed messages (${res.status})`);
      const payload = await res.json();
      setMessages(Array.isArray(payload.messages) ? payload.messages : []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingMessages(false);
    }
  }, []);

  const fetchAssets = useCallback(async () => {
    setLoadingAssets(true);
    setError(null);
    try {
      const res = await fetch(`${HISTORY_ASSETS_API_URL}?limit=200`);
      if (!res.ok) throw new Error(`Failed assets (${res.status})`);
      const payload = await res.json();
      setAssets(Array.isArray(payload.assets) ? payload.assets : []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingAssets(false);
    }
  }, []);

  useEffect(() => {
    void fetchThreads();
    void fetchAssets();
  }, [fetchThreads, fetchAssets]);

  useEffect(() => {
    if (selectedThread) {
      void fetchMessages(selectedThread);
    } else {
      setMessages([]);
    }
  }, [selectedThread, fetchMessages]);

  const selectThread = useCallback((threadId: string) => {
    setSelectedThread(threadId);
  }, []);

  const prune = useCallback(async (days: number) => {
    setError(null);
    try {
      const res = await fetch(`${HISTORY_PRUNE_API_URL}?days=${days}&vacuum=true`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`Failed prune (${res.status})`);
      await res.json();
      // Refresh summaries after pruning
      void fetchThreads();
      void fetchAssets();
      if (selectedThread) {
        void fetchMessages(selectedThread);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, [fetchThreads, fetchAssets, selectedThread, fetchMessages]);

  return {
    threads,
    selectedThread,
    selectThread,
    messages,
    assets,
    loadingThreads,
    loadingMessages,
    loadingAssets,
    error,
    refreshThreads: fetchThreads,
    refreshAssets: fetchAssets,
    prune,
  };
}