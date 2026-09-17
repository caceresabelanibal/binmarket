import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { settingsApi } from "../api/endpoints";
import type { Settings } from "../api/types";
import { Button, ModeBadge } from "./ui";
import { ConfirmDialog } from "./ConfirmDialog";
import { useLiveFeed } from "../ws/useLiveFeed";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard" },
  { to: "/market", label: "Market" },
  { to: "/strategies", label: "Strategies" },
  { to: "/risk", label: "Risk" },
  { to: "/logs", label: "Logs" },
  { to: "/binance", label: "Binance" },
  { to: "/settings", label: "Settings" },
];

export function Layout() {
  const { username, logout } = useAuth();
  const navigate = useNavigate();
  const { connected } = useLiveFeed();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [showToggleConfirm, setShowToggleConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setSettings(await settingsApi.get());
    } catch {
      /* ignore transient errors */
    }
  }

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  }, []);

  async function doToggle(reason?: string) {
    if (!settings) return;
    setBusy(true);
    try {
      const updated = await settingsApi.toggleBot(!settings.bot_enabled, reason);
      setSettings(updated);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(false);
      setShowToggleConfirm(false);
    }
  }

  return (
    <div className="min-h-screen flex bg-slate-950">
      <aside className="w-56 bg-slate-900 border-r border-slate-800 flex flex-col shrink-0">
        <div className="p-4 text-lg font-bold text-blue-400">BinMarket</div>
        <nav className="flex-1 px-2 space-y-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block px-3 py-2 rounded text-sm ${isActive ? "bg-blue-600 text-white" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t border-slate-800 text-xs text-slate-500">
          <div className="flex items-center gap-2 mb-2">
            <span className={`w-2 h-2 rounded-full ${connected ? "bg-emerald-500" : "bg-red-500"}`} />
            {connected ? "Conectado" : "Desconectado"}
          </div>
          <div className="flex justify-between items-center">
            <span>{username}</span>
            <button className="underline hover:text-slate-300" onClick={() => logout().then(() => navigate("/login"))}>
              Salir
            </button>
          </div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 border-b border-slate-800 bg-slate-900/60 flex items-center justify-between px-6">
          <div className="flex items-center gap-3">
            {settings && <ModeBadge mode={settings.mode} />}
            {settings?.emergency_stop_active && (
              <span className="text-xs font-bold text-red-400 animate-pulse">EMERGENCY STOP ACTIVO</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-400">TRADING AUTOMÁTICO</span>
            <Button
              variant={settings?.bot_enabled ? "danger" : "success"}
              disabled={busy || !settings}
              onClick={() => setShowToggleConfirm(true)}
            >
              {settings?.bot_enabled ? "ON — Apagar" : "OFF — Encender"}
            </Button>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">
          <Outlet context={{ settings, refreshSettings: refresh }} />
        </main>
      </div>

      {showToggleConfirm && settings && (
        <ConfirmDialog
          title={settings.bot_enabled ? "Apagar trading automático" : "Encender trading automático"}
          danger={settings.bot_enabled}
          onConfirm={() => doToggle()}
          onCancel={() => setShowToggleConfirm(false)}
        >
          <p>
            Modo actual: <strong>{settings.mode}</strong>.
          </p>
          {!settings.bot_enabled && settings.mode === "LIVE" && (
            <p className="text-red-400">Atención: en modo LIVE esto ejecutará operaciones con dinero real.</p>
          )}
          <p>¿Confirmar el cambio de estado del bot?</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
