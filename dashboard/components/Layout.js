import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import { getProperties } from "../lib/api";

const NAV = [
  { path: "/",          label: "Review Queue", icon: "🔍" },
  { path: "/emails",    label: "Emails",        icon: "📬" },
  { path: "/tasks",     label: "Tasks",         icon: "✅" },
  { path: "/knowledge", label: "Knowledge Base", icon: "📚" },
  { path: "/settings",  label: "Settings",      icon: "⚙️" },
];

function navHref(path, streamId) {
  return streamId ? `${path}?stream=${streamId}` : path;
}

export default function Layout({ children, streamId: streamIdProp }) {
  const router = useRouter();
  const { pathname, query } = router;

  // Stream ID from prop or URL — fall back to "1"
  const activeStreamId = streamIdProp || query.stream || "1";

  const [propertiesData, setPropertiesData] = useState(null);
  const [expanded, setExpanded] = useState({}); // propertyId → boolean

  useEffect(() => {
    getProperties()
      .then((data) => {
        setPropertiesData(data);
        // Auto-expand the property that owns the active stream
        if (data?.properties) {
          const ownerProp = data.properties.find((p) =>
            (p.streams || []).some((s) => String(s.id) === String(activeStreamId))
          );
          if (ownerProp) {
            setExpanded((e) => ({ ...e, [ownerProp.id]: true }));
          } else if (data.properties.length > 0) {
            // Fall back to expanding first property
            setExpanded((e) => ({ ...e, [data.properties[0].id]: true }));
          }
        }
      })
      .catch(() => {
        // Silently fail; nav still works via hardcoded stream IDs
      });
  }, [activeStreamId]);

  // Find the active stream's display name for the header
  let activeStreamName = null;
  let activePropertyName = null;
  if (propertiesData?.properties) {
    for (const prop of propertiesData.properties) {
      const stream = (prop.streams || []).find(
        (s) => String(s.id) === String(activeStreamId)
      );
      if (stream) {
        activeStreamName = stream.display_name || stream.name;
        activePropertyName = prop.name;
        break;
      }
    }
  }

  function toggleProperty(propId) {
    setExpanded((e) => ({ ...e, [propId]: !e[propId] }));
  }

  const isNavActive = (path) => pathname === path;

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl font-semibold text-brand-600 tracking-tight">
            Ready Concierge
          </span>
          {activePropertyName && (
            <span className="text-sm text-gray-500 border-l border-gray-200 pl-3">
              {activePropertyName}
            </span>
          )}
          {activeStreamName && (
            <span className="text-sm font-medium text-brand-700 bg-brand-50 px-2 py-0.5 rounded-full">
              {activeStreamName}
            </span>
          )}
        </div>
        <span className="text-xs text-gray-400 bg-gray-100 rounded px-2 py-1">
          Hotel Admin
        </span>
      </header>

      <div className="flex flex-1">
        {/* Sidebar */}
        <nav className="w-56 bg-white border-r border-gray-200 pt-4 pb-4 flex flex-col gap-0.5 px-3 overflow-y-auto">

          {/* Property → Stream hierarchy */}
          {propertiesData?.properties?.map((prop) => {
            const isOpen = !!expanded[prop.id];
            return (
              <div key={prop.id} className="mb-2">
                {/* Property header */}
                <button
                  onClick={() => toggleProperty(prop.id)}
                  className="w-full flex items-center justify-between px-2 py-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wider hover:text-gray-600 transition-colors"
                >
                  <span className="truncate">{prop.name}</span>
                  <span className="text-gray-300 ml-1">{isOpen ? "▾" : "▸"}</span>
                </button>

                {/* Stream list */}
                {isOpen && (prop.streams || []).map((stream) => {
                  const sid = String(stream.id);
                  const isActiveStream = sid === String(activeStreamId);
                  return (
                    <button
                      key={sid}
                      onClick={() => {
                        router.push(navHref(pathname, sid));
                      }}
                      className={`w-full flex items-center gap-2 pl-4 pr-2 py-1.5 rounded-lg text-sm transition-colors mb-0.5 ${
                        isActiveStream
                          ? "bg-brand-50 text-brand-700 font-medium"
                          : "text-gray-500 hover:bg-gray-100 hover:text-gray-800"
                      }`}
                    >
                      <span className="text-base leading-none">
                        {streamIcon(stream.name)}
                      </span>
                      <span className="truncate">
                        {stream.display_name || stream.name}
                      </span>
                      {stream.pending_tasks > 0 && (
                        <span className="ml-auto text-xs bg-amber-100 text-amber-700 rounded-full px-1.5 py-0.5 font-medium">
                          {stream.pending_tasks}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}

          {/* Divider */}
          <div className="border-t border-gray-100 my-2" />

          {/* Section nav */}
          {NAV.map(({ path, label, icon }) => {
            const active = isNavActive(path);
            return (
              <Link
                key={path}
                href={navHref(path, activeStreamId)}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  active
                    ? "bg-brand-50 text-brand-700"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                }`}
              >
                <span>{icon}</span>
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Main content */}
        <main className="flex-1 p-8 overflow-auto">{children}</main>
      </div>
    </div>
  );
}

/** Pick a simple icon based on the stream name. */
function streamIcon(name = "") {
  const n = name.toLowerCase();
  if (n.includes("spa"))        return "💆";
  if (n.includes("restaurant") || n.includes("dining") || n.includes("food")) return "🍽️";
  if (n.includes("event") || n.includes("party"))  return "🎉";
  if (n.includes("golf"))       return "⛳";
  if (n.includes("concierge"))  return "🤝";
  if (n.includes("front") || n.includes("desk"))   return "🏨";
  return "📡";
}
