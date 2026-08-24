import { useEffect, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from "recharts";
import { portfolioApi } from "../api/endpoints";
import type { PortfolioSummary, Snapshot } from "../api/types";
import { Card, fmtPct, fmtUsd, Stat, Table } from "../components/ui";

export function Portfolio() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [breakdown, setBreakdown] = useState<any[]>([]);

  useEffect(() => {
    portfolioApi.summary().then(setSummary);
    portfolioApi.snapshots(30).then(setSnapshots);
    portfolioApi.breakdown().then(setBreakdown);
  }, []);

  const chartData = snapshots.map((s) => ({ time: new Date(s.taken_at).toLocaleDateString(), equity: s.total_equity }));

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card><Stat label="Capital total" value={fmtUsd(summary?.total_equity)} /></Card>
        <Card><Stat label="P&L total" value={fmtUsd(summary?.pnl_total)} tone={(summary?.pnl_total ?? 0) >= 0 ? "good" : "bad"} /></Card>
        <Card><Stat label="ROI" value={fmtPct(summary?.roi_pct)} tone={(summary?.roi_pct ?? 0) >= 0 ? "good" : "bad"} /></Card>
        <Card><Stat label="Drawdown" value={fmtPct(summary?.drawdown_pct)} tone="bad" /></Card>
      </div>

      <Card title="Curva de equity (30 días)">
        {chartData.length === 0 ? (
          <p className="text-sm text-slate-500">Sin historial suficiente todavía.</p>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData}>
              <CartesianGrid stroke="#1e293b" />
              <XAxis dataKey="time" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} domain={["auto", "auto"]} />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
              <Line type="monotone" dataKey="equity" stroke="#3b82f6" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>

      <Card title="Exposición por activo">
        <Table headers={["Símbolo", "Exposición", "% del portfolio", "P&L no realizado", "P&L realizado hoy"]}>
          {breakdown.map((b) => (
            <tr key={b.symbol}>
              <td className="py-2 px-2 font-medium">{b.symbol}</td>
              <td className="py-2 px-2">{fmtUsd(b.exposure_value)}</td>
              <td className="py-2 px-2">{b.exposure_pct.toFixed(1)}%</td>
              <td className={`py-2 px-2 ${b.unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmtUsd(b.unrealized_pnl)}</td>
              <td className={`py-2 px-2 ${b.realized_pnl_today >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmtUsd(b.realized_pnl_today)}</td>
            </tr>
          ))}
        </Table>
        {breakdown.length > 3 && (
          <p className="text-xs text-amber-400 mt-3">
            Atención: el portfolio tiene {breakdown.length} activos abiertos; revisar concentración y correlación entre ellos.
          </p>
        )}
      </Card>
    </div>
  );
}
