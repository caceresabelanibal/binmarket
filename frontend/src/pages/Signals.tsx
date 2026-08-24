import { Fragment, useEffect, useState } from "react";
import { signalsApi } from "../api/endpoints";
import type { Signal } from "../api/types";
import { ActionBadge, Card, Table } from "../components/ui";

export function Signals() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);

  async function load() {
    setSignals(await signalsApi.list({ limit: 300 }));
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  return (
    <Card title="Señales">
      <Table headers={["Hora", "Símbolo", "Estrategia", "Régimen", "Acción", "Score", ""]}>
        {signals.map((s) => (
          <Fragment key={s.id}>
            <tr className="cursor-pointer hover:bg-slate-800/40" onClick={() => setExpanded(expanded === s.id ? null : s.id)}>
              <td className="py-2 px-2 text-slate-500 whitespace-nowrap">{new Date(s.created_at).toLocaleString()}</td>
              <td className="py-2 px-2 font-medium">{s.symbol}</td>
              <td className="py-2 px-2 text-slate-400">{s.strategy_name}</td>
              <td className="py-2 px-2 text-slate-500 text-xs">{s.regime}</td>
              <td className="py-2 px-2">
                <ActionBadge action={s.action} />
              </td>
              <td className="py-2 px-2">{s.opportunity_score.toFixed(0)}</td>
              <td className="py-2 px-2 text-slate-500">{expanded === s.id ? "▲" : "▼"}</td>
            </tr>
            {expanded === s.id && (
              <tr>
                <td colSpan={7} className="py-3 px-2 bg-slate-800/30">
                  <ul className="list-disc list-inside text-sm text-slate-300 space-y-0.5">
                    {s.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                  <div className="text-xs text-slate-500 mt-2 flex gap-4">
                    <span>Tendencia: {s.trend_score.toFixed(0)}</span>
                    <span>Momentum: {s.momentum_score.toFixed(0)}</span>
                    <span>Volumen: {s.volume_score.toFixed(0)}</span>
                    <span>Volatilidad: {s.volatility_score.toFixed(0)}</span>
                    <span>Riesgo: {s.risk_score.toFixed(0)}</span>
                    {s.risk_reward_ratio && <span>R/R: {s.risk_reward_ratio.toFixed(2)}</span>}
                  </div>
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </Table>
    </Card>
  );
}
