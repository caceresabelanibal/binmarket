import { useEffect, useState } from "react";
import { ordersApi } from "../api/endpoints";
import type { Order } from "../api/types";
import { Badge, Card, fmtUsd, Table } from "../components/ui";

export function Orders() {
  const [orders, setOrders] = useState<Order[]>([]);

  useEffect(() => {
    ordersApi.list({ limit: 200 }).then(setOrders);
    const id = setInterval(() => ordersApi.list({ limit: 200 }).then(setOrders), 15000);
    return () => clearInterval(id);
  }, []);

  return (
    <Card title="Órdenes">
      <Table
        headers={["Fecha", "Símbolo", "Lado", "Tipo", "Estado", "Cantidad", "Precio prom.", "Comisión", "Resultado", "Modo", "Manual"]}
      >
        {orders.map((o) => (
          <tr key={o.id} className={o.position_id ? "border-l-2 border-l-slate-700" : ""}>
            <td className="py-2 px-2 text-slate-500 whitespace-nowrap">{new Date(o.created_at).toLocaleString()}</td>
            <td className="py-2 px-2 font-medium">{o.symbol}</td>
            <td className={`py-2 px-2 ${o.side === "BUY" ? "text-emerald-400" : "text-red-400"}`}>{o.side}</td>
            <td className="py-2 px-2">{o.type}</td>
            <td className="py-2 px-2">
              <Badge tone={o.status === "FILLED" ? "good" : o.status === "REJECTED" ? "bad" : "neutral"}>{o.status}</Badge>
            </td>
            <td className="py-2 px-2">{o.filled_quantity} / {o.quantity}</td>
            <td className="py-2 px-2">{fmtUsd(o.avg_fill_price)}</td>
            <td className="py-2 px-2">{fmtUsd(o.commission_total)}</td>
            <td className="py-2 px-2">{resultBadge(o)}</td>
            <td className="py-2 px-2 text-slate-400">{o.mode}</td>
            <td className="py-2 px-2">{o.is_manual ? "Sí" : "No"}</td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

function resultBadge(o: Order) {
  // Both legs (the BUY that opened the position and the SELL that closed
  // it) carry the same position_id and the same final result, so whichever
  // row you're looking at - "compró a 3" or "vendió a 3.1" - shows the
  // outcome of that same execution, not just its own half.
  if (!o.position_id) return <span className="text-slate-600">—</span>;
  if (o.position_status !== "CLOSED" || o.position_realized_pnl === null) {
    return <Badge tone="neutral">Abierta</Badge>;
  }
  const won = o.position_realized_pnl >= 0;
  return (
    <Badge tone={won ? "good" : "bad"}>
      {won ? "GANÓ" : "PERDIÓ"} {won ? "+" : ""}
      {fmtUsd(o.position_realized_pnl)}
    </Badge>
  );
}
