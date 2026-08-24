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
      <Table headers={["Fecha", "Símbolo", "Lado", "Tipo", "Estado", "Cantidad", "Precio prom.", "Comisión", "Modo", "Manual"]}>
        {orders.map((o) => (
          <tr key={o.id}>
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
            <td className="py-2 px-2 text-slate-400">{o.mode}</td>
            <td className="py-2 px-2">{o.is_manual ? "Sí" : "No"}</td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}
