import { useMemo, useState } from "react";
import { useHistory } from "../hooks/useHistory";

export function HistoryPanel() {
  const {
    threads,
    selectedThread,
    selectThread,
    messages,
    assets,
    loadingThreads,
    loadingMessages,
    loadingAssets,
    error,
    prune,
  } = useHistory();
  const [pruneDays, setPruneDays] = useState(30);

  const sortedAssets = useMemo(
    () => assets.slice().sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    [assets],
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-700 dark:text-slate-200">History</h2>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={1}
            value={pruneDays}
            onChange={(e) => setPruneDays(Number(e.target.value) || 1)}
            className="w-20 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-800"
          />
          <button
            onClick={() => prune(pruneDays)}
            className="rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white shadow hover:bg-slate-700 dark:bg-slate-700 dark:hover:bg-slate-600"
            disabled={loadingThreads || loadingAssets}
          >
            Prune
          </button>
        </div>
      </div>
      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-1">
          <h3 className="text-sm font-medium text-slate-600 dark:text-slate-300">Threads</h3>
          <div className="max-h-60 overflow-y-auto rounded-xl border border-slate-200 bg-white p-2 text-xs dark:border-slate-800 dark:bg-slate-900">
            {loadingThreads && <div className="p-2">Loading threads…</div>}
            {!loadingThreads && threads.length === 0 && <div className="p-2">No threads yet.</div>}
            <ul className="space-y-1">
              {threads.map((t) => (
                <li key={t.thread_id}>
                  <button
                    onClick={() => selectThread(t.thread_id)}
                    className={`w-full rounded-md px-2 py-1 text-left transition ${
                      selectedThread === t.thread_id
                        ? "bg-slate-900 text-white dark:bg-slate-700"
                        : "hover:bg-slate-100 dark:hover:bg-slate-800"
                    }`}
                  >
                    <span className="block truncate font-mono text-[11px]">{t.thread_id}</span>
                    <span className="flex gap-2 text-[10px] opacity-75">
                      <span>{t.message_count} msgs</span>
                      <span>{new Date(t.last_at).toLocaleDateString()}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="space-y-3 lg:col-span-1">
          <h3 className="text-sm font-medium text-slate-600 dark:text-slate-300">Messages</h3>
          <div className="max-h-60 overflow-y-auto rounded-xl border border-slate-200 bg-white p-2 text-xs dark:border-slate-800 dark:bg-slate-900">
            {loadingMessages && <div className="p-2">Loading messages…</div>}
            {!loadingMessages && selectedThread && messages.length === 0 && (
              <div className="p-2">Empty thread.</div>
            )}
            {!selectedThread && <div className="p-2">Select a thread.</div>}
            <ul className="space-y-1">
              {messages.map((m, idx) => (
                <li key={idx} className="rounded-md px-2 py-1">
                  <span
                    className={`mr-2 rounded px-1 py-[1px] font-mono text-[10px] ${
                      m.role === "user"
                        ? "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
                        : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                    }`}
                  >
                    {m.role}
                  </span>
                  {m.content.slice(0, 160)}{m.content.length > 160 ? "…" : ""}
                  <div className="mt-1 text-[9px] opacity-60">
                    {new Date(m.created_at).toLocaleTimeString()}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="space-y-3 lg:col-span-1">
          <h3 className="text-sm font-medium text-slate-600 dark:text-slate-300">Historical Assets</h3>
          <div className="max-h-60 overflow-y-auto rounded-xl border border-slate-200 bg-white p-2 text-xs dark:border-slate-800 dark:bg-slate-900">
            {loadingAssets && <div className="p-2">Loading assets…</div>}
            {!loadingAssets && sortedAssets.length === 0 && <div className="p-2">No assets archived.</div>}
            <ul className="space-y-1">
              {sortedAssets.map((a) => (
                <li key={a.asset_id} className="rounded-md px-2 py-1">
                  <span className="block truncate font-mono text-[11px]">{a.asset_id}</span>
                  {a.metadata?.headline && (
                    <div className="truncate text-[10px] opacity-75">{a.metadata.headline}</div>
                  )}
                  <div className="mt-1 flex gap-2 text-[9px] opacity-60">
                    <span>{new Date(a.created_at).toLocaleDateString()}</span>
                    {a.image_path && <span>🖼</span>}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}