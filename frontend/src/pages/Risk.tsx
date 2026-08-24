import { useEffect, useState } from "react";
import { riskApi, settingsApi } from "../api/endpoints";
import type { RiskEvent, RiskState } from "../api/types";
import { Badge, Button, Card, fmtPct, fmtUsd, Stat, Table } from "../components/ui";
import { ConfirmDialog } from "../components/ConfirmDialog";

export function Risk() {
  const [state, setState] = useState<RiskState | null>(null);
  const [events, setEvents] = useState<RiskEvent[]>([]);
  const [showClear, setShowClear] = useState(false);
  const [showTrigger, setShowTrigger] = useState(false);

  async function load() {
    setState(await riskApi.state());
    setEvents(await riskApi.events());
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="space-y-6">
      {state?.emergency_stop_active && (
        <Card className="border-red-700 bg-red-950/40">
          <p className="text-red-300 font-semibold">EMERGENCY STOP ACTIVO: {state.emergency_stop_reason}</p>
          <Button className="mt-2" onClick={() => setShowClear(true)}>
            Desactivar Emergency Stop
          </Button>
        </Card>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <Stat label="Capital disponible" value={fmtUsd(state?.available_capital)} />
        </Card>
        <Card>
          <Stat label="Posiciones abiertas" value={`${state?.open_positions_count ?? 0} / ${state?.limits.max_open_positions ?? "-"}`} />
        </Card>
        <Card>
          <Stat label="Exposición total" value={fmtPct(state?.total_exposure_pct)} tone={(state?.total_exposure_pct ?? 0) > (state?.limits.max_total_exposure_pct ?? 100) ? "bad" : "neutral"} />
        </Card>
        <Card>
          <Stat label="Pérdidas consecutivas" value={`${state?.consecutive_losing_trades ?? 0} / ${state?.limits.max_consecutive_losses ?? "-"}`} />
        </Card>
        <Card>
          <Stat label="P&L diario" value={fmtPct(state?.daily_pnl_pct)} tone={(state?.daily_pnl_pct ?? 0) >= 0 ? "good" : "bad"} />
        </Card>
        <Card>
          <Stat label="P&L semanal" value={fmtPct(state?.weekly_pnl_pct)} tone={(state?.weekly_pnl_pct ?? 0) >= 0 ? "good" : "bad"} />
        </Card>
        <Card>
          <Stat label="Límite pérdida diaria" value={fmtPct(-1 * (state?.limits.max_daily_loss_pct ?? 0))} />
        </Card>
        <Card>
          <Stat label="Riesgo máx. por operación" value={fmtPct(state?.limits.max_risk_per_trade_pct)} />
        </Card>
      </div>

      <Card title="Acciones">
        <Button variant="danger" onClick={() => setShowTrigger(true)}>
          Activar Emergency Stop manualmente
        </Button>
      </Card>

      <Card title="Eventos de riesgo">
        <Table headers={["Fecha", "Tipo", "Símbolo", "Severidad", "Detalle"]}>
          {events.map((e) => (
            <tr key={e.id}>
              <td className="py-2 px-2 text-slate-500 whitespace-nowrap">{new Date(e.occurred_at).toLocaleString()}</td>
              <td className="py-2 px-2">{e.event_type}</td>
              <td className="py-2 px-2">{e.symbol ?? "—"}</td>
              <td className="py-2 px-2">
                <Badge tone={e.severity === "CRITICAL" ? "bad" : e.severity === "WARNING" ? "warn" : "neutral"}>{e.severity}</Badge>
              </td>
              <td className="py-2 px-2 text-slate-400 text-xs">{JSON.stringify(e.details)}</td>
            </tr>
          ))}
        </Table>
      </Card>

      {showClear && (
        <ConfirmDialog title="Desactivar Emergency Stop" onConfirm={() => settingsApi.clearEmergencyStop().then(() => (setShowClear(false), load()))} onCancel={() => setShowClear(false)}>
          <p>El bot seguirá apagado; deberás encenderlo manualmente si querés reanudar el trading automático.</p>
        </ConfirmDialog>
      )}
      {showTrigger && (
        <ConfirmDialog title="Activar Emergency Stop" danger onConfirm={() => riskApi.triggerEmergencyStop("Activado manualmente").then(() => (setShowTrigger(false), load()))} onCancel={() => setShowTrigger(false)}>
          <p>Esto apagará el trading automático inmediatamente.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
