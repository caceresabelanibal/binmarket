import { ReactNode } from "react";

export function Card({ title, children, className = "" }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <div className={`bg-slate-900 border border-slate-800 rounded-lg p-4 ${className}`}>
      {title && <h3 className="text-sm font-semibold text-slate-400 mb-3 uppercase tracking-wide">{title}</h3>}
      {children}
    </div>
  );
}

export function Stat({ label, value, tone = "neutral" }: { label: string; value: ReactNode; tone?: "neutral" | "good" | "bad" }) {
  const color = tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-red-400" : "text-slate-100";
  return (
    <div>
      <div className="text-xs text-slate-500 uppercase tracking-wide">{label}</div>
      <div className={`text-xl font-semibold ${color}`}>{value}</div>
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  type = "button",
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "danger" | "ghost" | "success";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  const styles: Record<string, string> = {
    primary: "bg-blue-600 hover:bg-blue-500 text-white",
    danger: "bg-red-600 hover:bg-red-500 text-white",
    success: "bg-emerald-600 hover:bg-emerald-500 text-white",
    ghost: "bg-slate-800 hover:bg-slate-700 text-slate-200",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-2 rounded-md text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors ${styles[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "good" | "bad" | "warn" }) {
  const styles: Record<string, string> = {
    neutral: "bg-slate-800 text-slate-300",
    good: "bg-emerald-900 text-emerald-300",
    bad: "bg-red-900 text-red-300",
    warn: "bg-amber-900 text-amber-300",
  };
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${styles[tone]}`}>{children}</span>;
}

export function ModeBadge({ mode }: { mode: string }) {
  const styles: Record<string, string> = {
    PAPER: "bg-blue-600 text-white",
    TESTNET: "bg-amber-600 text-white",
    LIVE: "bg-red-600 text-white animate-pulse",
  };
  return <span className={`px-3 py-1 rounded-md text-xs font-bold tracking-wider ${styles[mode] ?? "bg-slate-700"}`}>{mode}</span>;
}

export function ActionBadge({ action }: { action: string }) {
  const styles: Record<string, string> = {
    BUY: "bg-emerald-900 text-emerald-300",
    SELL: "bg-red-900 text-red-300",
    HOLD: "bg-slate-800 text-slate-300",
    NO_TRADE: "bg-slate-800 text-slate-500",
  };
  return <span className={`px-2 py-0.5 rounded text-xs font-semibold ${styles[action] ?? ""}`}>{action}</span>;
}

export function Table({ headers, children }: { headers: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-500 border-b border-slate-800">
            {headers.map((h) => (
              <th key={h} className="py-2 px-2 font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60">{children}</tbody>
      </table>
    </div>
  );
}

export function fmtUsd(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}

export function fmtPct(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(decimals)}%`;
}

export function fmtArs(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ARS`;
}
