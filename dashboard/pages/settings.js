import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import Layout from "../components/Layout";
import {
  getStreamSettings,
  addAuthorizedSender,
  removeAuthorizedSender,
} from "../lib/api";

export default function SettingsPage() {
  const router = useRouter();
  const streamId = router.query.stream || "1";

  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [newEmail, setNewEmail] = useState("");
  const [adding, setAdding] = useState(false);
  const [removingEmail, setRemovingEmail] = useState(null);
  const [addError, setAddError] = useState(null);

  async function loadSettings() {
    setLoading(true);
    setError(null);
    try {
      const data = await getStreamSettings(streamId);
      setSettings(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (router.isReady) loadSettings();
  }, [streamId, router.isReady]);

  async function handleAdd(e) {
    e.preventDefault();
    const email = newEmail.trim().toLowerCase();
    if (!email) return;
    setAdding(true);
    setAddError(null);
    try {
      const res = await addAuthorizedSender(streamId, email);
      setSettings((s) => ({ ...s, authorized_senders: res.authorized_senders }));
      setNewEmail("");
    } catch (err) {
      setAddError(err.message);
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(email) {
    setRemovingEmail(email);
    try {
      const res = await removeAuthorizedSender(streamId, email);
      setSettings((s) => ({ ...s, authorized_senders: res.authorized_senders }));
    } catch (err) {
      alert(`Error: ${err.message}`);
    } finally {
      setRemovingEmail(null);
    }
  }

  return (
    <Layout streamId={streamId}>
      <div className="max-w-2xl mx-auto">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Stream Settings</h1>
        {settings && (
          <p className="text-sm text-gray-500 mb-6">
            {settings.display_name || settings.name}
            {settings.inbound_email && (
              <span className="ml-2 font-mono bg-gray-100 text-gray-600 px-2 py-0.5 rounded text-xs">
                {settings.inbound_email}
              </span>
            )}
          </p>
        )}

        {loading && <p className="text-gray-500">Loading…</p>}
        {error && <p className="text-red-600">{error}</p>}

        {settings && !loading && (
          <>
            {/* Stream info */}
            <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 mb-6">
              <h2 className="text-base font-semibold text-gray-800 mb-4">Stream Info</h2>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                <div>
                  <dt className="text-gray-500">Name</dt>
                  <dd className="font-medium text-gray-900">{settings.display_name || settings.name}</dd>
                </div>
                <div>
                  <dt className="text-gray-500">Staff email</dt>
                  <dd className="font-medium text-gray-900">{settings.staff_email || "—"}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-gray-500 mb-0.5">Inbound address</dt>
                  <dd className="font-mono text-gray-900 text-xs bg-gray-50 px-3 py-2 rounded border border-gray-200 break-all">
                    {settings.inbound_email}
                  </dd>
                </div>
                <div>
                  <dt className="text-gray-500">Signal digest</dt>
                  <dd className="font-medium text-gray-900">
                    {settings.signal_enabled
                      ? `${settings.signal_frequency} at ${settings.signal_send_time}`
                      : "Disabled"}
                  </dd>
                </div>
                {settings.signal_recipients && settings.signal_recipients.length > 0 && (
                  <div>
                    <dt className="text-gray-500">Signal recipients</dt>
                    <dd className="font-medium text-gray-900 text-xs">
                      {settings.signal_recipients.join(", ")}
                    </dd>
                  </div>
                )}
              </dl>
            </section>

            {/* Authorized Senders */}
            <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
              <div className="flex items-start justify-between mb-1">
                <h2 className="text-base font-semibold text-gray-800">Authorized Senders</h2>
                <span
                  className={`text-xs rounded-full px-2 py-0.5 font-medium ${
                    settings.authorized_senders.length === 0
                      ? "bg-green-100 text-green-700"
                      : "bg-amber-100 text-amber-700"
                  }`}
                >
                  {settings.authorized_senders.length === 0
                    ? "Open — all senders accepted"
                    : `${settings.authorized_senders.length} allowlisted`}
                </span>
              </div>
              <p className="text-sm text-gray-500 mb-5">
                When this list is non-empty, only emails from these addresses will be
                processed by this stream. Leave empty to accept all inbound email.
              </p>

              {settings.authorized_senders.length === 0 ? (
                <p className="text-sm text-gray-400 italic mb-5">
                  No senders added — stream is open to all.
                </p>
              ) : (
                <ul className="mb-5 space-y-2">
                  {settings.authorized_senders.map((email) => (
                    <li
                      key={email}
                      className="flex items-center justify-between bg-gray-50 rounded-lg px-4 py-2.5 border border-gray-200"
                    >
                      <span className="text-sm font-mono text-gray-800">{email}</span>
                      <button
                        onClick={() => handleRemove(email)}
                        disabled={removingEmail === email}
                        className="text-xs text-red-500 hover:text-red-700 disabled:opacity-40 ml-4 font-medium"
                      >
                        {removingEmail === email ? "Removing…" : "Remove"}
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <form onSubmit={handleAdd} className="flex gap-2">
                <input
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  placeholder="guest@example.com"
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent"
                  disabled={adding}
                />
                <button
                  type="submit"
                  disabled={adding || !newEmail.trim()}
                  className="bg-brand-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-brand-700 disabled:opacity-40 transition-colors"
                >
                  {adding ? "Adding…" : "Add"}
                </button>
              </form>
              {addError && (
                <p className="text-xs text-red-600 mt-1">{addError}</p>
              )}
            </section>
          </>
        )}
      </div>
    </Layout>
  );
}
