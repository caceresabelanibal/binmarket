import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { binanceApi, portfolioApi, positionsApi, signalsApi, symbolsApi } from "../api/endpoints";
import type { BinanceTotalValue, PortfolioSummary, Position, RealAccountHistoryResponse, Signal, SymbolInfo } from "../api/types";
import { ActionBadge, Button, Card, fmtArs, fmtPct, fmtUsd, Stat, Table } from "../components/ui";
import type { Settings } from "../api/types";

const HISTORY_PAGE_SIZE = 10;

const REAL_BALANCE_REFRESH_OPTIONS = [5, 10, 15, 30, 60];

// fmtUsd's fixed 2 decimals rounds a small crypto holding (e.g. 0.00012 BTC)
// straight to 0.00 - useless for "what do I actually have". Show up to 8
// decimals (Binance's own base-asset precision) and trim trailing zeros.
function fmtQty(v: number): string {
  if (v === 0) return "0";
  const decimals = v >= 1 ? 2 : 8;
  return v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: decimals });
}

export function Dashboard() {
  const { settings } = useOutletContext<{ settings: Settings | null }>();
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [realAccountValue, setRealAccountValue] = useState<BinanceTotalValue | null>(null);
  const [refreshingRealAccount, setRefreshingRealAccount] = useState(false);
  const [realAccountUpdatedAt, setRealAccountUpdatedAt] = useState<Date | null>(null);
  const [realBalanceRefreshSec, setRealBalanceRefreshSec] = useState(15);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyPage, setHistoryPage] = useState(1);
  const [history, setHistory] = useState<RealAccountHistoryResponse | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  async function refreshRealAccountValue() {
    setRefreshingRealAccount(true);
    try {
      setRealAccountValue(await binanceApi.totalValue());
      setRealAccountUpdatedAt(new Date());
    } catch (e: any) {
      setRealAccountValue({ error: e.message });
    } finally {
      setRefreshingRealAccount(false);
    }
  }

  async function loadAll() {
    const [s, p, sig, sym] = await Promise.allSettled([
      portfolioApi.summary(),
      positionsApi.list({ status_filter: "OPEN" }),
      signalsApi.list({ limit: 8 }),
      symbolsApi.list({ selected_only: true, page_size: 200 }),
    ]);
    if (s.status === "fulfilled") setSummary(s.value);
    if (p.status === "fulfilled") setPositions(p.value);
    if (sig.status === "fulfilled") setSignals(sig.value);
    if (sym.status === "fulfilled") setSymbols(sym.value.items);
  }

  useEffect(() => {
    loadAll();
    const id = setInterval(loadAll, 10000);
    return () => clearInterval(id);
  }, []);

  // Its own cadence, separate from the rest of the dashboard's fixed 10s
  // poll, since this is the one card whose refresh rate the user wants to
  // control directly (real Binance balances, not simulated trading state).
  useEffect(() => {
    refreshRealAccountValue();
    const id = setInterval(refreshRealAccountValue, realBalanceRefreshSec * 1000);
    return () => clearInterval(id);
  }, [realBalanceRefreshSec]);

  useEffect(() => {
    if (!historyOpen) return;
    setHistoryLoading(true);
    binanceApi
      .totalValueHistory(historyPage, HISTORY_PAGE_SIZE)
      .then(setHistory)
      .catch(() => setHistory(null))
      .finally(() => setHistoryLoading(false));
  }, [historyOpen, historyPage]);

  if (!settings?.wizard_completed) {
    return (
      <Card>
        <p className="mb-3">Todavía no completaste el asistente de configuración inicial.</p>
        <Link to="/settings" className="text-blue-400 underline">
          Ir al asistente de configuración
        </Link>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card title="Capital real en tu cuenta de Binance">
        <div className="flex items-center justify-between mb-2 gap-3">
          <span className="text-xs text-slate-500">
            {realAccountUpdatedAt ? `Actualizado ${realAccountUpdatedAt.toLocaleTimeString()}` : ""}
          </span>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500" htmlFor="real-balance-refresh">
              Actualizar cada
            </label>
            <select
              id="real-balance-refresh"
              className="bg-slate-800 text-xs text-slate-300 rounded px-2 py-1 border border-slate-700"
              value={realBalanceRefreshSec}
              onChange={(e) => setRealBalanceRefreshSec(Number(e.target.value))}
            >
              {REAL_BALANCE_REFRESH_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}s
                </option>
              ))}
            </select>
            <Button variant="ghost" onClick={refreshRealAccountValue} disabled={refreshingRealAccount}>
              {refreshingRealAccount ? "Actualizando..." : "↻ Actualizar"}
            </Button>
          </div>
        </div>
        {!realAccountValue ? (
          <p className="text-sm text-slate-500">Consultando cuenta de Binance...</p>
        ) : realAccountValue.error ? (
          <p className="text-sm text-red-400">{realAccountValue.error}</p>
        ) : (
          <>
            <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
              <button
                type="button"
                className="text-left hover:opacity-80 transition-opacity"
                onClick={() => setHistoryOpen((v) => !v)}
                title="Ver histórico"
              >
                <div className="text-xs text-slate-500 uppercase tracking-wide flex items-center gap-1">
                  Total en pesos argentinos
                  <span className="text-slate-600">{historyOpen ? "▾" : "▸"}</span>
                </div>
                <div className="text-xl font-semibold text-slate-100">{fmtArs(realAccountValue.total_ars)}</div>
              </button>
              <Stat label="Total en USDT" value={fmtUsd(realAccountValue.total_usdt)} />
              <div className="text-xs text-slate-500 self-end pb-1">
                Cotización usada: 1 USDT = {realAccountValue.usdt_ars_rate?.toLocaleString("es-AR")} ARS (mercado
                USDT/ARS de Binance)
              </div>
            </div>

            {historyOpen && (
              <div className="mt-4 border-t border-slate-800 pt-3">
                <p className="text-xs text-slate-500 mb-2">
                  Histórico (un registro cada 6 horas, último mes) — {history?.total ?? 0} en total
                </p>
                {historyLoading ? (
                  <p className="text-sm text-slate-500">Cargando...</p>
                ) : !history || history.items.length === 0 ? (
                  <p className="text-sm text-slate-500">Todavía no hay registros históricos.</p>
                ) : (
                  <>
                    <Table headers={["Fecha", "Total (ARS)", "Total (USDT)"]}>
                      {history.items.map((h) => (
                        <tr key={h.id}>
                          <td className="py-2 px-2 text-slate-400 whitespace-nowrap">
                            {new Date(h.taken_at).toLocaleString()}
                          </td>
                          <td className="py-2 px-2 font-medium">{fmtArs(h.total_ars)}</td>
                          <td className="py-2 px-2 text-slate-300">{fmtUsd(h.total_usdt)}</td>
                        </tr>
                      ))}
                    </Table>
                    <div className="flex items-center justify-between mt-2">
                      <Button
                        variant="ghost"
                        disabled={historyPage <= 1}
                        onClick={() => setHistoryPage((p) => Math.max(1, p - 1))}
                      >
                        ← Anterior
                      </Button>
                      <span className="text-xs text-slate-500">
                        Página {history.page} de {Math.max(1, Math.ceil(history.total / history.page_size))}
                      </span>
                      <Button
                        variant="ghost"
                        disabled={historyPage * history.page_size >= history.total}
                        onClick={() => setHistoryPage((p) => p + 1)}
                      >
                        Siguiente →
                      </Button>
                    </div>
                  </>
                )}
              </div>
            )}
            {realAccountValue.breakdown && realAccountValue.breakdown.length > 0 && (
              <div className="mt-4">
                <p className="text-xs text-slate-500 mb-1">
                  Lo que tenés comprado ahora mismo — aparece cuando lo comprás, desaparece cuando lo vendés
                </p>
                <Table headers={["Activo", "Cantidad", "Valor (USDT)", "Valor (ARS)"]}>
                  {realAccountValue.breakdown.map((b) => (
                    <tr key={b.asset}>
                      <td className="py-2 px-2 font-medium">{b.asset}</td>
                      <td className="py-2 px-2 text-slate-300">{fmtQty(b.amount)}</td>
                      <td className="py-2 px-2">{fmtUsd(b.value_usdt)}</td>
                      <td className="py-2 px-2 text-slate-400">
                        {realAccountValue.usdt_ars_rate ? fmtArs(b.value_usdt * realAccountValue.usdt_ars_rate) : "—"}
                      </td>
                    </tr>
                  ))}
                </Table>
              </div>
            )}
          </>
        )}
        {realAccountValue?.unvalued_assets && realAccountValue.unvalued_assets.length > 0 && (
          <p className="text-xs text-amber-400 mt-2">
            No se pudo cotizar: {realAccountValue.unvalued_assets.map((a) => a.asset).join(", ")}
          </p>
        )}
        <p className="text-xs text-slate-600 mt-2">
          Suma de todos los activos en tu wallet Spot de Binance (no incluye Earn/Staking), valuados al precio de
          mercado actual. Independiente del modo de trading (PAPER/TESTNET/LIVE) — es tu cuenta real.
        </p>
      </Card>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <Stat label={`Capital total (modo ${summary?.mode ?? "..."})`} value={fmtUsd(summary?.total_equity)} />
        </Card>
        <Card>
          <Stat label="Balance disponible" value={fmtUsd(summary?.cash_balance)} />
        </Card>
        <Card>
          <Stat label="P&L hoy" value={fmtUsd(summary?.pnl_today)} tone={(summary?.pnl_today ?? 0) >= 0 ? "good" : "bad"} />
        </Card>
        <Card>
          <Stat label="ROI" value={fmtPct(summary?.roi_pct)} tone={(summary?.roi_pct ?? 0) >= 0 ? "good" : "bad"} />
        </Card>
        <Card>
          <Stat label="P&L semana" value={fmtUsd(summary?.pnl_week)} tone={(summary?.pnl_week ?? 0) >= 0 ? "good" : "bad"} />
        </Card>
        <Card>
          <Stat label="P&L mes" value={fmtUsd(summary?.pnl_month)} tone={(summary?.pnl_month ?? 0) >= 0 ? "good" : "bad"} />
        </Card>
        <Card>
          <Stat label="Win rate" value={`${(summary?.win_rate_pct ?? 0).toFixed(1)}%`} />
        </Card>
        <Card>
          <Stat label="Drawdown" value={fmtPct(summary?.drawdown_pct)} tone="bad" />
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card title={`Posiciones abiertas (${positions.length})`}>
          {positions.length === 0 ? (
            <p className="text-sm text-slate-500">Sin posiciones abiertas.</p>
          ) : (
            <Table headers={["Símbolo", "Entrada", "Cantidad", "P&L no realizado"]}>
              {positions.map((p) => (
                <tr key={p.id}>
                  <td className="py-2 px-2 font-medium">{p.symbol}</td>
                  <td className="py-2 px-2">{fmtUsd(p.entry_price)}</td>
                  <td className="py-2 px-2">{p.quantity}</td>
                  <td className={`py-2 px-2 ${((p.unrealized_pnl_pct ?? 0) >= 0) ? "text-emerald-400" : "text-red-400"}`}>
                    {fmtPct(p.unrealized_pnl_pct)}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card title="Mercado (símbolos seleccionados)">
          {symbols.length === 0 ? (
            <p className="text-sm text-slate-500">
              No hay símbolos seleccionados.{" "}
              <Link to="/market" className="text-blue-400 underline">
                Elegir en Market
              </Link>
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {symbols.map((s) => (
                <div key={s.symbol} className="flex items-center justify-between bg-slate-800/50 rounded px-3 py-2">
                  <span className="font-medium">{s.symbol}</span>
                  <span className={`text-sm ${(s.price_change_pct_24h ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {fmtUsd(s.last_price)} {(s.price_change_pct_24h ?? 0) >= 0 ? "↑" : "↓"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title="Señales recientes">
        <Table headers={["Hora", "Símbolo", "Acción", "Score", "Estrategia"]}>
          {signals.map((s) => (
            <tr key={s.id}>
              <td className="py-2 px-2 text-slate-500">{new Date(s.created_at).toLocaleTimeString()}</td>
              <td className="py-2 px-2 font-medium">{s.symbol}</td>
              <td className="py-2 px-2">
                <ActionBadge action={s.action} />
              </td>
              <td className="py-2 px-2">{s.opportunity_score.toFixed(0)}</td>
              <td className="py-2 px-2 text-slate-400">{s.strategy_name}</td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}
