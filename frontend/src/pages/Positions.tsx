import { useEffect, useState } from "react";
import { manualTradingApi, positionsApi } from "../api/endpoints";
import type { Position } from "../api/types";
import { Badge, Button, Card, fmtPct, fmtUsd, Table } from "../components/ui";
import { ConfirmDialog } from "../components/ConfirmDialog";

export function Positions() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [toClose, setToClose] = useState<Position | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setPositions(await positionsApi.list());
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  async function closePosition() {
    if (!toClose) return;
    setBusy(true);
    try {
      await manualTradingApi.confirmSell(toClose.id);
      await load();
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(false);
      setToClose(null);
    }
  }

  return (
    <Card title="Posiciones">
      <Table headers={["Símbolo", "Estado", "Entrada", "Cantidad", "Stop", "Target", "P&L", "Estrategia", "Modo", ""]}>
        {positions.map((p) => (
          <tr key={p.id}>
            <td className="py-2 px-2 font-medium">{p.symbol}</td>
            <td className="py-2 px-2">
              <Badge tone={p.status === "OPEN" ? "good" : "neutral"}>{p.status}</Badge>
            </td>
            <td className="py-2 px-2">{fmtUsd(p.entry_price)}</td>
            <td className="py-2 px-2">{p.quantity}</td>
            <td className="py-2 px-2 text-slate-400">{fmtUsd(p.stop_loss)}</td>
            <td className="py-2 px-2 text-slate-400">{fmtUsd(p.take_profit)}</td>
            <td className={`py-2 px-2 ${(p.status === "OPEN" ? (p.unrealized_pnl_pct ?? 0) : p.realized_pnl) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {p.status === "OPEN" ? fmtPct(p.unrealized_pnl_pct) : fmtUsd(p.realized_pnl)}
            </td>
            <td className="py-2 px-2 text-slate-400">{p.strategy_name ?? "manual"}</td>
            <td className="py-2 px-2 text-slate-400">{p.mode}</td>
            <td className="py-2 px-2">
              {p.status === "OPEN" && (
                <Button variant="danger" onClick={() => setToClose(p)}>
                  Cerrar
                </Button>
              )}
            </td>
          </tr>
        ))}
      </Table>

      {toClose && (
        <ConfirmDialog title={`Cerrar posición ${toClose.symbol}`} danger onConfirm={closePosition} onCancel={() => setToClose(null)}>
          <p>
            Se venderá {toClose.quantity} {toClose.symbol} al precio de mercado actual.
          </p>
        </ConfirmDialog>
      )}
    </Card>
  );
}
