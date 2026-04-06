const BASE = process.env.NEXT_PUBLIC_API_URL || "https://web-production-615a3.up.railway.app";

// Fallback stream ID (legacy env var kept for compat)
const DEFAULT_STREAM_ID = process.env.NEXT_PUBLIC_PROPERTY_ID || "1";

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

// ── Properties & Streams ──────────────────────────────────────────────────────

/** Returns all properties with per-stream stats. */
export function getProperties() {
  return apiFetch("/api/properties");
}

/** Returns all streams for a given property. */
export function getStreams(propertyId) {
  return apiFetch(`/api/streams/${propertyId}`);
}

// ── Review Queue ─────────────────────────────────────────────────────────────

export function getReviewQueue(streamId = DEFAULT_STREAM_ID) {
  return apiFetch(`/api/review/${streamId}`);
}

export function approveDraft(draftId) {
  return apiFetch(`/api/review/${draftId}/approve`, { method: "POST" });
}

export function rejectDraft(draftId) {
  return apiFetch(`/api/review/${draftId}/reject`, { method: "POST" });
}

// ── Emails ────────────────────────────────────────────────────────────────────

export function getEmails(streamId = DEFAULT_STREAM_ID, limit = 50) {
  return apiFetch(`/api/emails/${streamId}?limit=${limit}`);
}

// ── Knowledge Base ────────────────────────────────────────────────────────────

export function getKnowledgeDocs(streamId = DEFAULT_STREAM_ID) {
  return apiFetch(`/api/knowledge/${streamId}`);
}

export function deleteKnowledgeDoc(streamId = DEFAULT_STREAM_ID, docId) {
  return apiFetch(`/api/knowledge/${streamId}/${docId}`, { method: "DELETE" });
}

export async function uploadKnowledgeDoc(streamId = DEFAULT_STREAM_ID, title, content) {
  const form = new FormData();
  if (title) form.append("title", title);
  form.append("content", content);
  const res = await fetch(`${BASE}/api/knowledge/${streamId}/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Upload ${res.status}: ${text}`);
  }
  return res.json();
}

export async function uploadKnowledgeFile(streamId = DEFAULT_STREAM_ID, title, file) {
  const form = new FormData();
  if (title) form.append("title", title);
  form.append("file", file);
  const res = await fetch(`${BASE}/api/knowledge/${streamId}/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Upload ${res.status}: ${text}`);
  }
  return res.json();
}

// ── Tasks ─────────────────────────────────────────────────────────────────────

export function getTasks(streamId = DEFAULT_STREAM_ID, pendingOnly = false) {
  const qs = pendingOnly ? "?pending_only=true" : "";
  return apiFetch(`/api/tasks/${streamId}${qs}`);
}

export function updateTask(taskId, completed) {
  return apiFetch(`/api/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify({ completed }),
  });
}

// ── Stream Settings & Authorized Senders ─────────────────────────────────────

export function getStreamSettings(streamId) {
  return apiFetch(`/api/streams/${streamId}/settings`);
}

export function updateStreamSettings(streamId, body) {
  return apiFetch(`/api/streams/${streamId}/settings`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function addAuthorizedSender(streamId, email) {
  return apiFetch(`/api/streams/${streamId}/authorized-senders`, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function removeAuthorizedSender(streamId, email) {
  return apiFetch(
    `/api/streams/${streamId}/authorized-senders/${encodeURIComponent(email)}`,
    { method: "DELETE" }
  );
}

// ── Health / Stats ────────────────────────────────────────────────────────────

export function getHealth() {
  return apiFetch("/health");
}

export { DEFAULT_STREAM_ID };
