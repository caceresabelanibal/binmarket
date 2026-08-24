import { useEffect, useState } from "react";
import { logsApi } from "../api/endpoints";
import type { BotEvent, DecisionLogEntry, SystemLog } from "../api/types";
import { ActionBadge, Badge, Card, Table } from "../components/ui";

type Tab = "decisions" | "system" | "bot";

export function Logs() {
  const [tab, setTab] = useState<Tab>("decisions");
  const [decisions, setDecisions] = useState<DecisionLogEntry[]>([]);
  const [systemLogs, setSystemLogs] = useState<SystemLog[]>([]);
  const [botEvents, setBotEvents] = useState<BotEvent[]>([]);

  useEffect(() => {
    logsApi.decisions().then(setDecisions);
    logsApi.system().then(setSystemLogs);
    logsApi.botEvents().then(setBotEvents);
    const id = setInterval(() => {
      logsApi.decisions().then(setDecisions);
      logsApi.system().then(setSystemLogs);
      logsApi.botEvents().then(setBotEvents);
    }, 15000);
    return () => clearInterval(id);
  }, []);

  return (
    <Card>
      <div className="flex gap-2 mb-4">
        {(["decisions", "system", "bot"] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`px-3 py-1.5 rounded text-sm ${tab === t ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"}`}>
            {t === "decisions" ? "Decision Log" : t === "system" ? "System Logs" : "Bot Events"}
          </button>
        ))}
      </div>

      {tab === "decisions" && (
        <Table headers={["Fecha", "Símbolo", "Acción", "Score", "Estrategia", "Razones"]}>
          {decisions.map((d) => (
            <tr key={d.id}>
              <td className="py-2 px-2 text-slate-500 whitespace-nowrap">{new Date(d.created_at).toLocaleString()}</td>
              <td className="py-2 px-2 font-medium">{d.symbol}</td>
              <td className="py-2 px-2">
                <ActionBadge action={d.action} />
              </td>
              <td className="py-2 px-2">{d.opportunity_score.toFixed(0)}</td>
              <td className="py-2 px-2 text-slate-400">{d.strategy_name}</td>
              <td className="py-2 px-2 text-xs text-slate-400 max-w-md">{d.reasons.join(" · ")}</td>
            </tr>
          ))}
        </Table>
      )}

      {tab === "system" && (
        <Table headers={["Fecha", "Servicio", "Nivel", "Mensaje"]}>
          {systemLogs.map((l) => (
            <tr key={l.id}>
              <td className="py-2 px-2 text-slate-500 whitespace-nowrap">{new Date(l.occurred_at).toLocaleString()}</td>
              <td className="py-2 px-2">{l.service}</td>
              <td className="py-2 px-2">
                <Badge tone={l.level === "ERROR" ? "bad" : l.level === "WARNING" ? "warn" : "neutral"}>{l.level}</Badge>
              </td>
              <td className="py-2 px-2 text-slate-300">{l.message}</td>
            </tr>
          ))}
        </Table>
      )}

      {tab === "bot" && (
        <Table headers={["Fecha", "Acción", "Usuario", "Motivo"]}>
          {botEvents.map((b) => (
            <tr key={b.id}>
              <td className="py-2 px-2 text-slate-500 whitespace-nowrap">{new Date(b.occurred_at).toLocaleString()}</td>
              <td className="py-2 px-2">{b.action}</td>
              <td className="py-2 px-2">{b.performed_by}</td>
              <td className="py-2 px-2 text-slate-400">{b.reason ?? "—"}</td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}
