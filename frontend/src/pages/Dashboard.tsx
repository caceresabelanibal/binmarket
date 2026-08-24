import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { binanceApi, portfolioApi, positionsApi, signalsApi, symbolsApi } from "../api/endpoints";
import type { BinanceTotalValue, PortfolioSummary, Position, Signal, SymbolInfo } from "../api/types";
import { ActionBadge, Button, Card, fmtArs, fmtPct, fmtUsd, Stat, Table } from "../components/ui";
import type { Settings } from "../api/types";

export function Dashboard() {
  const { settings } = useOutletContext<{ settings: Settings | null }>();
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [realAccountValue, setRealAccountValue] = useState<BinanceTotalValue | null>(null);
  const [refreshingRealAccount, setRefreshingRealAccount] = useState(false);
  const [realAccountUpdatedAt, setRealAccountUpdatedAt] = useState<Date | null>(null);

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
    const [s, p, sig, sym, real] = await Promise.allSettled([
      portfolioApi.summary(),
      positionsApi.list({ status_filter: "OPEN" }),
      signalsApi.list({ limit: 8 }),
      symbolsApi.list({ selected_only: true, page_size: 200 }),
      binanceApi.totalValue(),
    ]);
    if (s.status === "fulfilled") setSummary(s.value);
    if (p.status === "fulfilled") setPositions(p.value);
    if (sig.status === "fulfilled") setSignals(sig.value);
    if (sym.status === "fulfilled") setSymbols(sym.value.items);
    if (real.status === "fulfilled") {
      setRealAccountValue(real.value);
      setRealAccountUpdatedAt(new Date());
    }
  }

  useEffect(() => {
    loadAll();
    const id = setInterval(loadAll, 10000);
    return () => clearInterval(id);
  }, []);

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
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-slate-500">
            {realAccountUpdatedAt ? `Actualizado ${realAccountUpdatedAt.toLocaleTimeString()}` : ""}
          </span>
          <Button variant="ghost" onClick={refreshRealAccountValue} disabled={refreshingRealAccount}>
            {refreshingRealAccount ? "Actualizando..." : "↻ Actualizar"}
          </Button>
        </div>
        {!realAccountValue ? (
          <p className="text-sm text-slate-500">Consultando cuenta de Binance...</p>
        ) : realAccountValue.error ? (
          <p className="text-sm text-red-400">{realAccountValue.error}</p>
        ) : (
          <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
            <Stat label="Total en pesos argentinos" value={fmtArs(realAccountValue.total_ars)} />
            <Stat label="Total en USDT" value={fmtUsd(realAccountValue.total_usdt)} />
            <div className="text-xs text-slate-500 self-end pb-1">
              Cotización usada: 1 USDT = {realAccountValue.usdt_ars_rate?.toLocaleString("es-AR")} ARS (mercado
              USDT/ARS de Binance)
            </div>
          </div>
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
