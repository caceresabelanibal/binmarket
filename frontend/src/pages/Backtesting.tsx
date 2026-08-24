import { useEffect, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from "recharts";
import { backtestsApi, strategiesApi, symbolsApi } from "../api/endpoints";
import type { Backtest, Strategy, SymbolInfo } from "../api/types";
import { Badge, Button, Card, fmtPct, fmtUsd, Stat, Table } from "../components/ui";

const TIMEFRAMES = ["15m", "30m", "1h", "4h", "1d"];

export function Backtesting() {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [backtests, setBacktests] = useState<Backtest[]>([]);
  const [selected, setSelected] = useState<Backtest | null>(null);
  const [busy, setBusy] = useState(false);

  const [form, setForm] = useState({
    symbol: "",
    timeframe: "1h",
    strategy_name: "",
    days: 60,
    initial_capital: 10000,
    fee_pct: 0.1,
    slippage_pct: 0.05,
    is_walk_forward: false,
  });

  async function loadLists() {
    const [symResponse, strat, bt] = await Promise.all([
      symbolsApi.list({ selected_only: true, page_size: 200 }),
      strategiesApi.list(),
      backtestsApi.list(),
    ]);
    const sym = symResponse.items;
    setSymbols(sym);
    setStrategies(strat);
    setBacktests(bt);
    if (!form.symbol && sym.length) setForm((f) => ({ ...f, symbol: sym[0].symbol }));
    if (!form.strategy_name && strat.length) setForm((f) => ({ ...f, strategy_name: strat[0].name }));
  }

  useEffect(() => {
    loadLists();
  }, []);

  async function runBacktest() {
    setBusy(true);
    try {
      const end = new Date();
      const start = new Date();
      start.setDate(start.getDate() - form.days);
      const result = await backtestsApi.create({
        name: `${form.strategy_name} ${form.symbol} ${form.timeframe}`,
        symbol: form.symbol,
        timeframe: form.timeframe,
        strategy_name: form.strategy_name,
        start_date: start.toISOString(),
        end_date: end.toISOString(),
        initial_capital: form.initial_capital,
        fee_pct: form.fee_pct,
        slippage_pct: form.slippage_pct,
        is_walk_forward: form.is_walk_forward,
      });
      setBacktests((prev) => [result, ...prev]);
      setSelected(result);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  }

  const chartData = (selected?.equity_curve ?? []).map((p: any) => ({ t: new Date(p.t).toLocaleString(), equity: p.equity }));

  return (
    <div className="space-y-6">
      <Card title="Nuevo backtest">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <label className="text-xs text-slate-500">Símbolo</label>
            <select className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })}>
              {symbols.map((s) => <option key={s.symbol} value={s.symbol}>{s.symbol}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-500">Timeframe</label>
            <select className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={form.timeframe} onChange={(e) => setForm({ ...form, timeframe: e.target.value })}>
              {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-500">Estrategia</label>
            <select className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={form.strategy_name} onChange={(e) => setForm({ ...form, strategy_name: e.target.value })}>
              {strategies.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-500">Días hacia atrás</label>
            <input type="number" className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={form.days} onChange={(e) => setForm({ ...form, days: Number(e.target.value) })} />
          </div>
          <div>
            <label className="text-xs text-slate-500">Capital inicial</label>
            <input type="number" className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={form.initial_capital} onChange={(e) => setForm({ ...form, initial_capital: Number(e.target.value) })} />
          </div>
          <div>
            <label className="text-xs text-slate-500">Comisión %</label>
            <input type="number" step="0.01" className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={form.fee_pct} onChange={(e) => setForm({ ...form, fee_pct: Number(e.target.value) })} />
          </div>
          <div>
            <label className="text-xs text-slate-500">Slippage %</label>
            <input type="number" step="0.01" className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={form.slippage_pct} onChange={(e) => setForm({ ...form, slippage_pct: Number(e.target.value) })} />
          </div>
          <label className="flex items-center gap-2 text-sm mt-5">
            <input type="checkbox" checked={form.is_walk_forward} onChange={(e) => setForm({ ...form, is_walk_forward: e.target.checked })} />
            Walk-forward (ventanas OOS)
          </label>
        </div>
        <Button className="mt-4" onClick={runBacktest} disabled={busy || !form.symbol || !form.strategy_name}>
          {busy ? "Ejecutando..." : "Ejecutar backtest"}
        </Button>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card title="Historial" className="lg:col-span-1">
          <div className="space-y-2 max-h-96 overflow-auto">
            {backtests.map((b) => (
              <button
                key={b.id}
                onClick={() => setSelected(b)}
                className={`w-full text-left px-3 py-2 rounded text-sm ${selected?.id === b.id ? "bg-blue-600 text-white" : "bg-slate-800 hover:bg-slate-700"}`}
              >
                <div className="flex justify-between">
                  <span>{b.name}</span>
                  <Badge tone={b.status === "DONE" ? "good" : b.status === "FAILED" ? "bad" : "neutral"}>{b.status}</Badge>
                </div>
                <div className="text-xs text-slate-400">{new Date(b.created_at).toLocaleString()}</div>
              </button>
            ))}
          </div>
        </Card>

        <Card title="Resultado" className="lg:col-span-2">
          {!selected ? (
            <p className="text-sm text-slate-500">Seleccionar un backtest del historial.</p>
          ) : selected.status === "FAILED" ? (
            <p className="text-red-400 text-sm">{selected.error_message}</p>
          ) : selected.is_walk_forward ? (
            <Table headers={["Ventana", "Desde", "Hasta", "ROI", "Win rate", "Drawdown", "Trades", "Sharpe"]}>
              {(selected.results.windows ?? []).map((w: any) => (
                <tr key={w.window_index}>
                  <td className="py-2 px-2">{w.window_index + 1}</td>
                  <td className="py-2 px-2 text-xs">{w.start?.slice(0, 16)}</td>
                  <td className="py-2 px-2 text-xs">{w.end?.slice(0, 16)}</td>
                  <td className={`py-2 px-2 ${w.roi_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmtPct(w.roi_pct)}</td>
                  <td className="py-2 px-2">{w.win_rate_pct.toFixed(0)}%</td>
                  <td className="py-2 px-2 text-red-400">{fmtPct(w.max_drawdown_pct)}</td>
                  <td className="py-2 px-2">{w.total_trades}</td>
                  <td className="py-2 px-2">{w.sharpe_ratio?.toFixed(2) ?? "—"}</td>
                </tr>
              ))}
            </Table>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-3 md:grid-cols-4 gap-4">
                <Stat label="Capital final" value={fmtUsd(selected.results.final_capital)} />
                <Stat label="ROI" value={fmtPct(selected.results.roi_pct)} tone={selected.results.roi_pct >= 0 ? "good" : "bad"} />
                <Stat label="Win rate" value={`${selected.results.win_rate_pct?.toFixed(1)}%`} />
                <Stat label="Profit factor" value={selected.results.profit_factor?.toFixed(2) ?? "—"} />
                <Stat label="Max drawdown" value={fmtPct(selected.results.max_drawdown_pct)} tone="bad" />
                <Stat label="Sharpe" value={selected.results.sharpe_ratio?.toFixed(2) ?? "—"} />
                <Stat label="Operaciones" value={selected.results.total_trades} />
                <Stat label="Mejor / peor" value={`${fmtPct(selected.results.best_trade_pct)} / ${fmtPct(selected.results.worst_trade_pct)}`} />
              </div>
              {chartData.length > 0 && (
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={chartData}>
                    <CartesianGrid stroke="#1e293b" />
                    <XAxis dataKey="t" stroke="#64748b" fontSize={10} tick={false} />
                    <YAxis stroke="#64748b" fontSize={11} domain={["auto", "auto"]} />
                    <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
                    <Line type="monotone" dataKey="equity" stroke="#3b82f6" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
