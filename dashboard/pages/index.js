import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/router";
import Layout from "../components/Layout";
import StatCard from "../components/StatCard";
import { getReviewQueue, approveDraft, rejectDraft } from "../lib/api";

const CONFIDENCE_COLORS = {
  high:   "bg-green-100 text-green-800",
  medium: "bg-yellow-100 text-yellow-800",
  low:    "bg-red-100 text-red-800",
};

const FLAG_LABELS = {
  "topic:legal_threat":      "⚖️ Legal",
  "topic:medical_emergency": "🚑 Medical",
  "topic:security_incident": "🔒 Security",
  "topic:media_inquiry":     "📰 Media",
  "topic:public_escalation": "📢 Review Site",
  "intent:complaint":        "😠 Complaint",
  "confidence:low":          "🤔 Low Confidence",
};

function FlagBadge({ flag }) {
  const label = FLAG_LABELS[flag] || flag;
  return (
    <span className="inline-block text-xs bg-orange-100 text-orange-800 rounded-full px-2 py-0.5 font-medium">
      {label}
    </span>
  );
}

function DraftCard({ item, onAction }) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(null); // "approve" | "reject"
  const [done, setDone] = useState(null);        // "approved" | "rejected"

  async function handleAction(action) {
    setLoading(action);
    try {
      if (action === "approve") await approveDraft(item.draft_id);
      else await rejectDraft(item.draft_id);
      setDone(action);
      onAction();
    } catch (e) {
      alert(`Error: ${e.message}`);
    } finally {
      setLoading(null);
    }
  }

  if (done) {
    return (
      <div className={`rounded-xl border p-5 ${done === "approved" ? "bg-green-50 border-green-200" : "bg-gray-50 border-gray-200"}`}>
        <p className="text-sm text-gray-500">
          Draft {done === "approved" ? "✅ approved and sent" : "✗ rejected"} —{" "}
          <span className="font-medium">{item.subject || "(no subject)"}</span>
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-orange-200 bg-white shadow-sm">
      {/* Header */}
      <div className="p-5 flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="font-semibold text-gray-900 truncate">
              {item.subject || "(no subject)"}
            </span>
            {item.guardrail_confidence && (
              <span className={`text-xs rounded-full px-2 py-0.5 font-medium ${CONFIDENCE_COLORS[item.guardrail_confidence] || "bg-gray-100 text-gray-700"}`}>
                {item.guardrail_confidence} confidence
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500">
            From: <span className="font-medium text-gray-700">{item.sender_name || "—"}</span>{" "}
            {item.sender_email && <span className="text-gray-400">&lt;{item.sender_email}&gt;</span>}
          </p>
          {item.review_reason && (
            <p className="text-sm text-orange-700 mt-1">
              ⚠️ {item.review_reason}
            </p>
          )}
          <div className="flex flex-wrap gap-1.5 mt-2">
            {(item.guardrail_flags || []).map((f) => (
              <FlagBadge key={f} flag={f} />
            ))}
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex gap-2 shrink-0">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-sm text-gray-500 hover:text-gray-800 border border-gray-200 rounded-lg px-3 py-1.5 transition-colors"
          >
            {expanded ? "Hide draft" : "View draft"}
          </button>
          <button
            onClick={() => handleAction("reject")}
            disabled={!!loading}
            className="text-sm font-medium text-red-700 hover:bg-red-50 border border-red-200 rounded-lg px-3 py-1.5 transition-colors disabled:opacity-50"
          >
            {loading === "reject" ? "…" : "Reject"}
          </button>
          <button
            onClick={() => handleAction("approve")}
            disabled={!!loading}
            className="text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-lg px-4 py-1.5 transition-colors disabled:opacity-50"
          >
            {loading === "approve" ? "Sending…" : "Approve & Send"}
          </button>
        </div>
      </div>

      {/* Expanded draft text */}
      {expanded && (
        <div className="border-t border-gray-100 px-5 py-4 bg-gray-50 rounded-b-xl">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
            Draft Reply
          </p>
          <pre className="text-sm text-gray-800 whitespace-pre-wrap font-sans leading-relaxed">
            {item.draft_text}
          </pre>
        </div>
      )}
    </div>
  );
}

export default function ReviewQueuePage() {
  const router = useRouter();
  const streamId = router.query.stream || "1";

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getReviewQueue(streamId);
      setData(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [streamId]);

  useEffect(() => { load(); }, [load]);

  return (
    <Layout streamId={streamId}>
      <div className="max-w-4xl">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Review Queue</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Drafts held for human review before sending
            </p>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="text-sm text-gray-500 hover:text-gray-800 border border-gray-200 rounded-lg px-3 py-1.5 transition-colors"
          >
            {loading ? "Loading…" : "↻ Refresh"}
          </button>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 gap-4 mb-8">
          <StatCard
            label="Pending Review"
            value={loading ? "…" : (data?.pending_count ?? 0)}
            color={data?.pending_count > 0 ? "yellow" : "green"}
            sub={data?.pending_count > 0 ? "Needs your attention" : "All clear"}
          />
          <StatCard
            label="Stream"
            value={data?.hotel_name ?? "—"}
            sub={`Stream ID: ${streamId}`}
          />
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 mb-6">
            ⚠️ Could not load review queue: {error}
          </div>
        )}

        {/* Queue items */}
        {!loading && !error && (
          <>
            {data?.items?.length === 0 ? (
              <div className="rounded-xl border border-gray-200 bg-white p-12 text-center">
                <p className="text-3xl mb-2">✅</p>
                <p className="font-semibold text-gray-700">Queue is empty</p>
                <p className="text-sm text-gray-500 mt-1">
                  No drafts are currently waiting for review.
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                {data.items.map((item) => (
                  <DraftCard key={item.draft_id} item={item} onAction={load} />
                ))}
              </div>
            )}
          </>
        )}

        {loading && (
          <div className="flex flex-col gap-4">
            {[1, 2].map((i) => (
              <div key={i} className="rounded-xl border border-gray-100 bg-white h-28 animate-pulse" />
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
