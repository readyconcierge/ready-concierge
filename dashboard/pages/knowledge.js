import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/router";
import Layout from "../components/Layout";
import StatCard from "../components/StatCard";
import { getKnowledgeDocs, deleteKnowledgeDoc, uploadKnowledgeDoc, uploadKnowledgeFile } from "../lib/api";

function DocRow({ doc, streamId, onDelete }) {
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleDelete() {
    setLoading(true);
    try {
      await deleteKnowledgeDoc(streamId, doc.id);
      onDelete();
    } catch (e) {
      alert(`Error: ${e.message}`);
    } finally {
      setLoading(false);
      setConfirming(false);
    }
  }

  return (
    <tr className="hover:bg-gray-50 transition-colors">
      <td className="px-4 py-3">
        <p className="font-medium text-gray-900">{doc.title || doc.filename}</p>
        {doc.title && <p className="text-xs text-gray-400">{doc.filename}</p>}
      </td>
      <td className="px-4 py-3 text-sm text-gray-500 text-center">{doc.chunk_count}</td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {doc.uploaded_at
          ? new Date(doc.uploaded_at).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
              year: "numeric",
            })
          : "—"}
      </td>
      <td className="px-4 py-3 text-right">
        {confirming ? (
          <div className="flex items-center justify-end gap-2">
            <span className="text-xs text-red-600">Delete?</span>
            <button
              onClick={handleDelete}
              disabled={loading}
              className="text-xs text-white bg-red-600 hover:bg-red-700 rounded px-2 py-1 disabled:opacity-50"
            >
              {loading ? "…" : "Yes"}
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="text-xs text-gray-500 hover:text-gray-800 border border-gray-200 rounded px-2 py-1"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            className="text-xs text-red-500 hover:text-red-700 transition-colors"
          >
            Delete
          </button>
        )}
      </td>
    </tr>
  );
}

function UploadModal({ streamId, onClose, onSuccess }) {
  const [mode, setMode]       = useState("text"); // "text" | "file"
  const [title, setTitle]     = useState("");
  const [content, setContent] = useState("");
  const [file, setFile]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (mode === "text") {
        if (!content.trim()) throw new Error("Content is required.");
        await uploadKnowledgeDoc(streamId, title, content);
      } else {
        if (!file) throw new Error("Please select a file.");
        await uploadKnowledgeFile(streamId, title, file);
      }
      onSuccess();
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg">
        <div className="p-6 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900">Add Knowledge Document</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none">×</button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
          {/* Mode tabs */}
          <div className="flex rounded-lg border border-gray-200 overflow-hidden">
            {["text", "file"].map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`flex-1 py-2 text-sm font-medium transition-colors ${
                  mode === m ? "bg-brand-50 text-brand-700" : "text-gray-500 hover:text-gray-800"
                }`}
              >
                {m === "text" ? "Paste Text" : "Upload File"}
              </button>
            ))}
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Title (optional)</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Restaurant Hours, Spa Menu"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>

          {mode === "text" ? (
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Content</label>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={8}
                placeholder="Paste your hotel information, menus, policies, FAQs..."
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 resize-none"
                required
              />
            </div>
          ) : (
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">File (.txt or .md)</label>
              <input
                type="file"
                accept=".txt,.md"
                onChange={(e) => setFile(e.target.files[0])}
                className="w-full text-sm text-gray-600 border border-gray-200 rounded-lg px-3 py-2 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-brand-50 file:text-brand-700"
              />
            </div>
          )}

          {error && (
            <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
          )}

          <div className="flex justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="text-sm text-gray-500 hover:text-gray-800 border border-gray-200 rounded-lg px-4 py-2"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-lg px-5 py-2 disabled:opacity-50 transition-colors"
            >
              {loading ? "Uploading…" : "Upload"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function KnowledgePage() {
  const router = useRouter();
  const streamId = router.query.stream || "1";

  const [data, setData]             = useState(null);
  const [error, setError]           = useState(null);
  const [loading, setLoading]       = useState(true);
  const [showUpload, setShowUpload] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getKnowledgeDocs(streamId));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [streamId]);

  useEffect(() => { load(); }, [load]);

  const docs        = data?.documents || [];
  const totalChunks = docs.reduce((s, d) => s + (d.chunk_count || 0), 0);

  return (
    <Layout streamId={streamId}>
      {showUpload && (
        <UploadModal
          streamId={streamId}
          onClose={() => setShowUpload(false)}
          onSuccess={load}
        />
      )}

      <div className="max-w-4xl">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Knowledge Base</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Documents used to generate context-aware draft replies
            </p>
          </div>
          <button
            onClick={() => setShowUpload(true)}
            className="text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-lg px-4 py-2 transition-colors"
          >
            + Add Document
          </button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4 mb-8">
          <StatCard label="Documents"    value={loading ? "…" : docs.length} />
          <StatCard label="Total Chunks" value={loading ? "…" : totalChunks} sub="Searchable knowledge segments" />
          <StatCard
            label="RAG Status"
            value={docs.length > 0 ? "Active" : "Empty"}
            color={docs.length > 0 ? "green" : "yellow"}
            sub={docs.length > 0 ? "Drafts use your docs" : "Upload docs to improve drafts"}
          />
        </div>

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 mb-6">
            ⚠️ {error}
          </div>
        )}

        {!loading && !error && (
          docs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-gray-300 bg-white p-12 text-center">
              <p className="text-3xl mb-3">📚</p>
              <p className="font-semibold text-gray-700">No documents yet</p>
              <p className="text-sm text-gray-500 mt-1 mb-5">
                Add menus, policies, FAQs, and amenity details to give Claude accurate context.
              </p>
              <button
                onClick={() => setShowUpload(true)}
                className="text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-lg px-5 py-2 transition-colors"
              >
                + Add Your First Document
              </button>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50 text-left">
                    <th className="px-4 py-3 font-medium text-gray-500 text-xs uppercase tracking-wide">Document</th>
                    <th className="px-4 py-3 font-medium text-gray-500 text-xs uppercase tracking-wide text-center">Chunks</th>
                    <th className="px-4 py-3 font-medium text-gray-500 text-xs uppercase tracking-wide">Uploaded</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {docs.map((doc) => (
                    <DocRow key={doc.id} doc={doc} streamId={streamId} onDelete={load} />
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}

        {loading && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-14 border-b border-gray-50 animate-pulse bg-gray-50" />
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
