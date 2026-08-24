import { useState } from "react";
import { manualTradingApi, symbolsApi } from "../api/endpoints";
import { Button, Card, fmtPct, fmtUsd } from "../components/ui";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useEffect } from "react";
import type { SymbolInfo } from "../api/types";

export function Trading() {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [symbol, setSymbol] = useState("");
  const [percentOfBalance, setPercentOfBalance] = useState(10);
  const [stopLossPct, setStopLossPct] = useState(3);
  const [takeProfitPct, setTakeProfitPct] = useState(6);
  const [preview, setPreview] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    symbolsApi.list({ selected_only: true, page_size: 200 }).then(({ items: rows }) => {
      setSymbols(rows);
      if (rows.length) setSymbol(rows[0].symbol);
    });
  }, []);

  function payload() {
    return {
      symbol,
      percent_of_balance: percentOfBalance,
      stop_loss_pct: stopLossPct,
      take_profit_pct: takeProfitPct,
    };
  }

  async function doPreview() {
    setError(null);
    setPreview(null);
    try {
      setPreview(await manualTradingApi.previewBuy(payload()));
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function doConfirm() {
    setBusy(true);
    try {
      const res = await manualTradingApi.confirmBuy(payload());
      alert(`Orden ${res.status}. ID: ${res.order_id}`);
      setPreview(null);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(false);
      setShowConfirm(false);
    }
  }

  return (
    <div className="max-w-xl space-y-6">
      <Card title="Compra manual">
        <div className="space-y-3">
          <div>
            <label className="text-xs text-slate-500">Símbolo</label>
            <select className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.symbol}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-slate-500">% del balance</label>
              <input type="number" className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={percentOfBalance} onChange={(e) => setPercentOfBalance(Number(e.target.value))} />
            </div>
            <div>
              <label className="text-xs text-slate-500">Stop loss %</label>
              <input type="number" className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={stopLossPct} onChange={(e) => setStopLossPct(Number(e.target.value))} />
            </div>
            <div>
              <label className="text-xs text-slate-500">Take profit %</label>
              <input type="number" className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={takeProfitPct} onChange={(e) => setTakeProfitPct(Number(e.target.value))} />
            </div>
          </div>
          <Button onClick={doPreview} disabled={!symbol}>
            Calcular resumen
          </Button>
          {error && <p className="text-red-400 text-sm">{error}</p>}
        </div>
      </Card>

      {preview && (
        <Card title="Resumen de la operación">
          <div className="space-y-1 text-sm">
            <p>
              Comprar <strong>{preview.quantity}</strong> {preview.symbol} a ~{fmtUsd(preview.reference_price)} (
              {fmtUsd(preview.estimated_notional)} en total)
            </p>
            <p>Comisión estimada: {fmtUsd(preview.estimated_fee)}</p>
            <p>Spread estimado: {fmtPct(preview.spread_pct)}</p>
            {preview.stop_loss_price && <p>Stop loss: {fmtUsd(preview.stop_loss_price)}</p>}
            {preview.take_profit_price && <p>Take profit: {fmtUsd(preview.take_profit_price)}</p>}
            {preview.estimated_risk_usdt && <p>Riesgo estimado: {fmtUsd(preview.estimated_risk_usdt)}</p>}
            {preview.risk_reward_ratio && <p>Relación riesgo/beneficio: {preview.risk_reward_ratio.toFixed(2)}</p>}
            <p className={preview.risk_check_passed ? "text-emerald-400" : "text-red-400"}>
              {preview.risk_check_passed ? "Risk Manager: aprobado" : `Risk Manager: rechazado — ${preview.risk_check_reason}`}
            </p>
          </div>
          <Button className="mt-4" disabled={!preview.risk_check_passed || busy} onClick={() => setShowConfirm(true)}>
            Confirmar compra
          </Button>
        </Card>
      )}

      {showConfirm && preview && (
        <ConfirmDialog title={`Confirmar compra de ${preview.symbol}`} onConfirm={doConfirm} onCancel={() => setShowConfirm(false)}>
          <p>
            {preview.quantity} {preview.symbol} por ~{fmtUsd(preview.estimated_notional)}. Esta acción enviará una orden real según el modo activo.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
