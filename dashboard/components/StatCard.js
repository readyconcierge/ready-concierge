export default function StatCard({ label, value, sub, color = "gray" }) {
  const colors = {
    gray:   "bg-white",
    blue:   "bg-brand-50 border-brand-100",
    yellow: "bg-yellow-50 border-yellow-100",
    green:  "bg-green-50 border-green-100",
    red:    "bg-red-50 border-red-100",
  };

  return (
    <div className={`rounded-xl border p-5 ${colors[color]}`}>
      <p className="text-xs uppercase tracking-wide text-gray-500 font-medium mb-1">{label}</p>
      <p className="text-3xl font-bold text-gray-900">{value ?? "—"}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
    </div>
  );
}
