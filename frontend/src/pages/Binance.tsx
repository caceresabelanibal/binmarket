import { useState } from "react";
import { binanceApi } from "../api/endpoints";
import type { BinanceAccount } from "../api/types";
import { Badge, Button, Card, Table } from "../components/ui";

export function BinancePage() {
  const [connectivity, setConnectivity] = useState<any | null>(null);
  const [account, setAccount] = useState<BinanceAccount | null>(null);
  const [busy, setBusy] = useState(false);

  async function testConnection() {
    setBusy(true);
    try {
      setConnectivity(await binanceApi.testConnectivity());
    } catch (e: any) {
      setConnectivity({ error: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function loadAccount() {
    setBusy(true);
    try {
      setAccount(await binanceApi.account());
    } catch (e: any) {
      setAccount({ error: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <p className="text-sm text-amber-400 mb-4">
          Advertencia: la API Key usada para trading NUNCA debe tener habilitado el permiso de retiros (withdrawals) en
          Binance.
        </p>
        <div className="flex gap-3">
          <Button onClick={testConnection} disabled={busy}>
            Probar conectividad
          </Button>
          <Button variant="ghost" onClick={loadAccount} disabled={busy}>
            Ver cuenta y balances
          </Button>
        </div>
      </Card>

      {connectivity && (
        <Card title="Estado de conexión">
          <div className="text-sm space-y-1">
            <p>Entorno: {connectivity.environment}</p>
            <p>API Key: {connectivity.masked_api_key || "no configurada"}</p>
            <p>Ping: <Badge tone={connectivity.ping ? "good" : "bad"}>{connectivity.ping ? "OK" : "FALLÓ"}</Badge></p>
            <p>Cuenta accesible: <Badge tone={connectivity.account_reachable ? "good" : "bad"}>{connectivity.account_reachable ? "SÍ" : "NO"}</Badge></p>
            {connectivity.error && <p className="text-red-400">{connectivity.error}</p>}
          </div>
        </Card>
      )}

      {account && (
        <Card title="Cuenta">
          {account.error ? (
            <p className="text-red-400">{account.error}</p>
          ) : (
            <>
              {account.warnings?.map((w, i) => (
                <p key={i} className="text-red-400 text-sm mb-2">{w}</p>
              ))}
              <p className="text-sm mb-2">
                Tipo: {account.account_type} · Puede operar: {account.can_trade ? "Sí" : "No"} · Puede retirar:{" "}
                <span className={account.can_withdraw ? "text-red-400 font-bold" : ""}>{account.can_withdraw ? "SÍ (RIESGO)" : "No"}</span>
              </p>
              <Table headers={["Activo", "Disponible", "Bloqueado"]}>
                {(account.balances ?? []).map((b) => (
                  <tr key={b.asset}>
                    <td className="py-2 px-2 font-medium">{b.asset}</td>
                    <td className="py-2 px-2">{b.free}</td>
                    <td className="py-2 px-2 text-slate-400">{b.locked}</td>
                  </tr>
                ))}
              </Table>
            </>
          )}
        </Card>
      )}
    </div>
  );
}
