import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/router";
import Layout from "../components/Layout";
import StatCard from "../components/StatCard";
import { getTasks, updateTask } from "../lib/api";

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function TaskRow({ task, onToggle }) {
  const [toggling, setToggling] = useState(false);

  async function handleToggle() {
    setToggling(true);
    try {
      await onToggle(task.id, !task.completed);
    } finally {
      setToggling(false);
    }
  }

  return (
    <div
      className={`flex items-start gap-4 p-4 border-b border-gray-100 last:border-0 transition-colors ${
        task.completed ? "bg-gray-50 opacity-60" : "bg-white hover:bg-gray-50"
      }`}
    >
      {/* Checkbox */}
      <button
        onClick={handleToggle}
        disabled={toggling}
        className={`mt-0.5 w-5 h-5 flex-shrink-0 rounded border-2 flex items-center justify-center transition-colors ${
          task.completed
            ? "bg-green-500 border-green-500 text-white"
            : "border-gray-300 hover:border-brand-500"
        } ${toggling ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
        title={task.completed ? "Mark incomplete" : "Mark complete"}
      >
        {task.completed && (
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        )}
      </button>

      {/* Task content */}
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-medium ${task.completed ? "line-through text-gray-400" : "text-gray-900"}`}>
          {task.task_text}
        </p>
        {task.guest_name && (
          <p className="text-xs text-gray-500 mt-0.5">
            {task.guest_name}
            {task.email_subject ? ` — ${task.email_subject}` : ""}
          </p>
        )}
        <p className="text-xs text-gray-400 mt-1">
          Added {formatDate(task.created_at)}
          {task.completed && task.completed_via && (
            <span className="ml-2 text-green-600">
              ✓ Completed via {task.completed_via} {task.completed_at ? `on ${formatDate(task.completed_at)}` : ""}
            </span>
          )}
        </p>
      </div>

      {/* Task ID badge */}
      <span className="text-xs text-gray-300 font-mono flex-shrink-0 mt-0.5">#{task.id}</span>
    </div>
  );
}

export default function TasksPage() {
  const router = useRouter();
  const streamId = router.query.stream || "1";

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showCompleted, setShowCompleted] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getTasks(streamId);
      setData(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [streamId]);

  useEffect(() => { load(); }, [load]);

  async function handleToggle(taskId, newCompleted) {
    try {
      await updateTask(taskId, newCompleted);
      // Optimistic update
      setData((prev) => ({
        ...prev,
        tasks: prev.tasks.map((t) =>
          t.id === taskId
            ? { ...t, completed: newCompleted, completed_via: newCompleted ? "dashboard" : null }
            : t
        ),
        pending: prev.tasks.filter((t) =>
          t.id === taskId ? !newCompleted : !t.completed
        ).length,
      }));
    } catch (e) {
      alert("Failed to update task: " + e.message);
    }
  }

  const pending   = data?.tasks?.filter((t) => !t.completed) ?? [];
  const completed = data?.tasks?.filter((t) => t.completed) ?? [];

  // Build email shortcut address from stream inbound email if available
  const inboundEmail = data?.inbound_email;
  const listEmail = inboundEmail
    ? inboundEmail.replace(/^[^@]+@/, "list@")
    : null;

  return (
    <Layout streamId={streamId}>
      <div className="max-w-3xl">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Task List</h1>
            <p className="text-sm text-gray-500 mt-1">
              Commitments extracted from AI draft replies
            </p>
          </div>
          <button
            onClick={load}
            className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
          >
            ↻ Refresh
          </button>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <StatCard label="Pending"   value={loading ? "—" : pending.length} />
          <StatCard label="Completed" value={loading ? "—" : completed.length} />
          <StatCard label="Total"     value={loading ? "—" : (data?.total ?? 0)} />
        </div>

        {/* Email shortcut tip */}
        {listEmail && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 mb-6 text-sm text-blue-800">
            <strong>💡 Email shortcut:</strong> Email{" "}
            <code className="bg-blue-100 px-1 rounded">{listEmail}</code>{" "}
            to get this list in your inbox. Reply with{" "}
            <code className="bg-blue-100 px-1 rounded">"done 1 3"</code> or{" "}
            <code className="bg-blue-100 px-1 rounded">"done all"</code> to mark tasks complete.
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 text-sm text-red-700">
            ⚠ Failed to load tasks: {error}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="text-center py-16 text-gray-400 text-sm">Loading tasks…</div>
        )}

        {/* Pending tasks */}
        {!loading && !error && (
          <>
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden mb-6">
              <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                  Pending
                  <span className="ml-2 bg-amber-100 text-amber-800 text-xs px-2 py-0.5 rounded-full font-normal">
                    {pending.length}
                  </span>
                </h2>
              </div>

              {pending.length === 0 ? (
                <div className="flex flex-col items-center py-12 text-gray-400">
                  <span className="text-4xl mb-3">✅</span>
                  <p className="text-sm font-medium">All clear</p>
                  <p className="text-xs mt-1">No pending tasks</p>
                </div>
              ) : (
                pending.map((task) => (
                  <TaskRow key={task.id} task={task} onToggle={handleToggle} />
                ))
              )}
            </div>

            {/* Completed tasks (collapsible) */}
            {completed.length > 0 && (
              <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                <button
                  onClick={() => setShowCompleted((v) => !v)}
                  className="w-full px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between text-left hover:bg-gray-100 transition-colors"
                >
                  <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
                    Completed
                    <span className="ml-2 bg-green-100 text-green-800 text-xs px-2 py-0.5 rounded-full font-normal">
                      {completed.length}
                    </span>
                  </h2>
                  <span className="text-gray-400 text-xs">{showCompleted ? "▲ Hide" : "▼ Show"}</span>
                </button>

                {showCompleted && completed.map((task) => (
                  <TaskRow key={task.id} task={task} onToggle={handleToggle} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </Layout>
  );
}
