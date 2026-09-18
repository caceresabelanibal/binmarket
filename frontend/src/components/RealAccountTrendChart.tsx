import { useMemo, useState } from "react";
import type { RealAccountHistoryEntry } from "../api/types";
import { fmtArs } from "./ui";

const WIDTH = 280;
const HEIGHT = 110;
const PAD = { top: 10, right: 8, bottom: 8, left: 8 };

// Wave/line chart of "Total en pesos argentinos" over time (requested
// directly by the user, for the hover tooltip on that stat): a single
// series, so per dataviz convention it needs no legend — the line color
// alone (matching this app's existing up=emerald/down=red convention,
// decided by total change over the window) carries the story, with a
// crosshair + point readout on hover for "cuándo y cuánto" changed.
export function RealAccountTrendChart({ entries }: { entries: RealAccountHistoryEntry[] }) {
  const points = useMemo(
    () =>
      [...entries]
        .filter((e) => e.total_ars != null)
        .sort((a, b) => new Date(a.taken_at).getTime() - new Date(b.taken_at).getTime())
        .map((e) => ({ date: new Date(e.taken_at), value: e.total_ars as number })),
    [entries],
  );

  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (points.length < 2) {
    return <p className="text-xs text-slate-500 w-64">Todavía no hay suficiente historial para graficar la evolución.</p>;
  }

  const values = points.map((p) => p.value);
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const span = maxV - minV || 1;

  const innerW = WIDTH - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;

  const xAt = (i: number) => PAD.left + (i / (points.length - 1)) * innerW;
  const yAt = (v: number) => PAD.top + innerH - ((v - minV) / span) * innerH;

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${xAt(i).toFixed(1)} ${yAt(p.value).toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L ${xAt(points.length - 1).toFixed(1)} ${(PAD.top + innerH).toFixed(1)} L ${xAt(0).toFixed(1)} ${(PAD.top + innerH).toFixed(1)} Z`;

  const first = points[0].value;
  const last = points[points.length - 1].value;
  const totalDeltaPct = first ? ((last - first) / first) * 100 : 0;
  const up = totalDeltaPct >= 0;
  const seriesColor = up ? "#34d399" : "#f87171"; // emerald-400 / red-400 — this app's existing up/down convention

  function handleMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = e.clientX - rect.left;
    const ratio = Math.min(1, Math.max(0, (relX - PAD.left) / innerW));
    setHoverIdx(Math.round(ratio * (points.length - 1)));
  }

  const activeIdx = hoverIdx ?? points.length - 1;
  const active = points[activeIdx];
  const prev = activeIdx > 0 ? points[activeIdx - 1].value : null;
  const pointDeltaPct = prev ? ((active.value - prev) / prev) * 100 : null;

  return (
    <div className="w-72">
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-xs text-slate-500">Últimos {points.length} registros (cada 6hs, hasta 30 días)</span>
        <span className={`text-xs font-semibold whitespace-nowrap ${up ? "text-emerald-400" : "text-red-400"}`}>
          {up ? "▲" : "▼"} {Math.abs(totalDeltaPct).toFixed(1)}%
        </span>
      </div>
      <svg
        width={WIDTH}
        height={HEIGHT}
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIdx(null)}
        className="block cursor-crosshair"
        role="img"
        aria-label="Evolución del capital total en pesos argentinos"
      >
        <line x1={PAD.left} x2={WIDTH - PAD.right} y1={PAD.top + innerH} y2={PAD.top + innerH} stroke="#334155" strokeWidth={1} />
        <path d={areaPath} fill={seriesColor} opacity={0.1} stroke="none" />
        <path d={linePath} fill="none" stroke={seriesColor} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hoverIdx !== null && (
          <line x1={xAt(hoverIdx)} x2={xAt(hoverIdx)} y1={PAD.top} y2={PAD.top + innerH} stroke="#64748b" strokeWidth={1} />
        )}
        <circle cx={xAt(activeIdx)} cy={yAt(active.value)} r={4} fill={seriesColor} stroke="#0f172a" strokeWidth={2} />
      </svg>
      <div className="text-xs mt-1 flex items-baseline justify-between gap-2">
        <span className="text-slate-500 whitespace-nowrap">
          {hoverIdx === null
            ? "Ahora"
            : active.date.toLocaleString("es-AR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
        </span>
        <span className="text-slate-200 font-medium whitespace-nowrap">{fmtArs(active.value)}</span>
        {pointDeltaPct !== null && (
          <span className={`whitespace-nowrap ${pointDeltaPct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {pointDeltaPct >= 0 ? "+" : ""}
            {pointDeltaPct.toFixed(2)}%
          </span>
        )}
      </div>
    </div>
  );
}
