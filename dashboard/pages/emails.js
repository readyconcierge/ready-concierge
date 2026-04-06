import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/router";
import Layout from "../components/Layout";
import StatCard from "../components/StatCard";
import { getEmails } from "../lib/api";

const INTENT_LABELS = {
  dining:          "🍽️ Dining",
  transportation:  "🚗 Transport",
  arrival:         "🛬 Arrival",
  departure:       "🛫 Departure",
  celebration:     "🎉 Celebration",
  spa:             "💆 Spa",
  golf:            "⛳ Golf",
  complaint:       "😠 Complaint",
  vip_request:     "⭐ VIP",
  general_inquiry: "💬 Inquiry",
};

function IntentBadge({ intent }) {
  const label = INTENT_LABELS[intent] || intent;
  const isComplaint = intent === "complaint";
  return (
    <span className={`text-xs rounded-full px-2 py-0.5 font-medium ${isComplaint ? "bg-red-100 text-red-800" : "bg-blue-50 text-blue-700"}`}>
      {label}
    </span>
  );
}

function StatusBadge({ draftSent, needsReview }) {
  if (needsReview) return <span className="text-xs rounded-full px-2 py-0.5 font-medium bg-orange-100 text-orange-800">⏳ Held for review</span>;
  if (draftSent)   return <span className="text-xs rounded-full px-2 py-0.5 font-medium bg-green-100 text-green-800">✓ Draft sent</span>;
  return <span className="text-xs rounded-full px-2 py-0.5 font-medium bg-gray-100 text-gray-600">No draft</span>;
}

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function EmailsPage() {
  const router = useRouter();
  const streamId = router.query.stream || "1";

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getEmails(streamId, 50));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [streamId]);

  useEffect(() => { load(); }, [load]);

  const emails = data?.emails || [];
  const sentCount      = emails.filter((e) => e.draft_sent).length;
  const reviewCount    = emails.filter((e) => e.needs_review).length;
  const complaintCount = emails.filter((e) => (e.intents || []).includes("complaint")).length;

  return (
    <Layout streamId={streamId}>
      <div className="max-w-5xl">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Email History</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              All guest emails processed by Ready Concierge
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

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          <StatCard label="Total Emails"     value={loading ? "…" : emails.length} />
          <StatCard label="Drafts Sent"      value={loading ? "…" : sentCount}      color="green" />
          <StatCard label="Held for Review"  value={loading ? "…" : reviewCount}    color={reviewCount > 0 ? "yellow" : "gray"} />
          <StatCard label="Complaints"       value={loading ? "…" : complaintCount} color={complaintCount > 0 ? "red" : "gray"} />
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 mb-6">
            ⚠️ {error}
          </div>
        )}

        {/* Table */}
        {!loading && !error && (
          emails.length === 0 ? (
            <div className="rounded-xl border border-gray-200 bg-white p-12 text-center">
              <p className="text-3xl mb-2">📭</p>
              <p className="font-semibold text-gray-700">No emails yet</p>
              <p className="text-sm text-gray-500 mt-1">Emails forwarded to Ready Concierge will appear here.</p>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50 text-left">
                    <th className="px-4 py-3 font-medium text-gray-500 text-xs uppercase tracking-wide">Sender</th>
                    <th className="px-4 py-3 font-medium text-gray-500 text-xs uppercase tracking-wide">Subject</th>
                    <th className="px-4 py-3 font-medium text-gray-500 text-xs uppercase tracking-wide">Intents</th>
                    <th className="px-4 py-3 font-medium text-gray-500 text-xs uppercase tracking-wide">Status</th>
                    <th className="px-4 py-3 font-medium text-gray-500 text-xs uppercase tracking-wide">Received</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {emails.map((email) => (
                    <>
                      <tr
                        key={email.id}
                        onClick={() => setExpanded(expanded === email.id ? null : email.id)}
                        className="hover:bg-gray-50 cursor-pointer transition-colors"
                      >
                        <td className="px-4 py-3">
                          <p className="font-medium text-gray-900 truncate max-w-[160px]">
                            {email.sender_name || email.sender_email || "—"}
                          </p>
                          <p className="text-gray-400 text-xs truncate max-w-[160px]">{email.sender_email}</p>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-gray-800 truncate max-w-[260px]">
                            {email.subject || "(no subject)"}
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            {(email.intents || []).map((i) => (
                              <IntentBadge key={i} intent={i} />
                            ))}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge draftSent={email.draft_sent} needsReview={email.needs_review} />
                        </td>
                        <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                          {formatDate(email.received_at)}
                        </td>
                      </tr>
                      {expanded === email.id && (
                        <tr key={`${email.id}-exp`} className="bg-gray-50">
                          <td colSpan={5} className="px-4 py-4">
                            <div className="grid grid-cols-2 gap-6">
                              <div>
                                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                                  Email Body
                                </p>
                                <p className="text-sm text-gray-700 whitespace-pre-wrap max-h-48 overflow-auto">
                                  {email.body || "(empty)"}
                                </p>
                              </div>
                              {email.draft_text && (
                                <div>
                                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                                    Draft Reply
                                  </p>
                                  <p className="text-sm text-gray-700 whitespace-pre-wrap max-h-48 overflow-auto">
                                    {email.draft_text}
                                  </p>
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}

        {loading && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-14 border-b border-gray-50 animate-pulse bg-gray-50" />
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
