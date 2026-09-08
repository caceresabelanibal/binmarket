import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { binanceApi, marketApi, settingsApi, symbolsApi } from "../api/endpoints";
import type { BandwidthUsage, Settings as SettingsType, SymbolInfo } from "../api/types";
import { Badge, Button, Card, Stat } from "../components/ui";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { BackfillProgress } from "../components/BackfillProgress";

const TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"];

const WIZARD_STEPS = [
  { title: "Binance API", desc: "Configurar y verificar la conexión con Binance." },
  { title: "Pares de mercado", desc: "Elegir qué criptomonedas se van a analizar." },
  { title: "Datos históricos", desc: "Descargar histórico para las criptomonedas elegidas." },
  { title: "Estrategia", desc: "Revisar y habilitar las estrategias de trading." },
  { title: "Riesgo", desc: "Configurar los límites de riesgo antes de operar." },
  { title: "Backtest", desc: "Correr un backtest para validar la estrategia elegida." },
  { title: "Paper Trading", desc: "Activar Paper Trading y observar resultados." },
  { title: "Testnet", desc: "Cuando estés conforme, probar en Binance Testnet." },
  { title: "LIVE", desc: "Habilitar operaciones reales (requiere confirmación explícita)." },
];

function WizardStepHistoricalData() {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("1h");
  const [daysBack, setDaysBack] = useState(90);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    symbolsApi.list({ selected_only: true, page_size: 200 }).then(({ items }) => {
      setSymbols(items);
      if (items.length) setSymbol(items[0].symbol);
    });
  }, []);

  async function startBackfill() {
    setError(null);
    if (!symbol) {
      setError("Primero elegí al menos un símbolo en el paso anterior (Market).");
      return;
    }
    const start = new Date();
    start.setDate(start.getDate() - daysBack);
    const job = await marketApi.backfill(symbol, timeframe, start.toISOString());
    setJobId(job.id);
  }

  if (symbols.length === 0) {
    return (
      <div className="space-y-2 text-sm">
        <p className="text-amber-400">Todavía no seleccionaste ningún par en el paso anterior.</p>
        <Link to="/market" className="text-blue-400 underline">
          Ir a Market para seleccionar pares
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
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
        <div>
          <label className="text-xs text-slate-500">Timeframe</label>
          <select className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm" value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-500">Días hacia atrás</label>
          <input
            type="number"
            className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
            value={daysBack}
            onChange={(e) => setDaysBack(Number(e.target.value))}
          />
        </div>
      </div>
      {timeframe === "1m" && daysBack > 30 && (
        <p className="text-xs text-amber-400">
          Con timeframe 1m y {daysBack} días, la descarga puede tardar varios minutos (Binance limita a 1000 velas
          por request). Para probar rápido, usá menos días o un timeframe mayor (1h/4h).
        </p>
      )}
      <Button onClick={startBackfill}>Descargar histórico</Button>
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {jobId && (
        <div className="mt-2">
          <BackfillProgress key={jobId} jobId={jobId} />
        </div>
      )}
    </div>
  );
}

const BANDWIDTH_POLL_MS = 5000;

function NetworkUsagePanel({ settings, refreshSettings }: { settings: SettingsType; refreshSettings: () => void }) {
  const [usage, setUsage] = useState<BandwidthUsage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;
    async function poll() {
      try {
        const result = await marketApi.bandwidth();
        if (!stopped) {
          setUsage(result);
          setError(null);
        }
      } catch (e: any) {
        if (!stopped) setError(e.message);
      }
    }
    poll();
    const id = setInterval(poll, BANDWIDTH_POLL_MS);
    return () => {
      stopped = true;
      clearInterval(id);
    };
  }, []);

  async function toggleAllTimeframes() {
    await settingsApi.updateNetwork({ stream_all_timeframes: !settings.stream_all_timeframes });
    refreshSettings();
  }

  async function setDepthSpeed(ms: number) {
    await settingsApi.updateNetwork({ orderbook_update_speed_ms: ms });
    refreshSettings();
  }

  const categoryLabels: Record<string, string> = {
    ticker: "Precio (ticker)",
    orderbook: "Profundidad de mercado (order book)",
    klines: "Velas (klines)",
  };

  return (
    <Card title="Uso de red (WebSocket de Binance)">
      <p className="text-sm text-slate-400 mb-4">
        Medido en vivo, no estimado — se actualiza cada {BANDWIDTH_POLL_MS / 1000}s con el minuto más reciente ya
        completo.
      </p>
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
      {!usage ? (
        <p className="text-sm text-slate-500">Midiendo...</p>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <Stat label="Total ahora" value={`${usage.total_kb_per_sec.toFixed(2)} KB/s`} />
            <Stat label="Estimado por hora" value={`${usage.estimated_mb_per_hour.toFixed(1)} MB/h`} />
            <Stat label="Símbolos activos" value={usage.selected_symbols_count} />
            <Stat label="Streams abiertos" value={usage.total_streams} />
          </div>
          <div className="space-y-2 mb-4">
            {Object.entries(usage.categories).map(([category, stats]) => (
              <div key={category} className="flex items-center justify-between bg-slate-800/50 rounded px-3 py-2 text-sm">
                <span>{categoryLabels[category] ?? category}</span>
                <span className="text-slate-400">{stats.kb_per_sec.toFixed(2)} KB/s</span>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="border-t border-slate-800 pt-4 space-y-4">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="text-sm">Transmitir todos los timeframes (1m a 1d)</span>
            <Badge tone={settings.stream_all_timeframes ? "warn" : "good"}>
              {settings.stream_all_timeframes ? "SÍ (más tráfico)" : "NO (solo 1h y 5m)"}
            </Badge>
            <Button variant="ghost" onClick={toggleAllTimeframes}>
              {settings.stream_all_timeframes ? "Reducir a lo esencial" : "Activar todos"}
            </Button>
          </div>
          <p className="text-xs text-slate-500">
            El motor solo necesita 1h (régimen) y 5m (scalping) para operar. Activar todos los timeframes sirve para
            ver gráficos en vivo en cualquier timeframe en Market, pero multiplica el tráfico de velas por ~4.
          </p>
        </div>
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="text-sm">Velocidad del order book</span>
            <Badge tone={settings.orderbook_update_speed_ms === 100 ? "warn" : "good"}>
              {settings.orderbook_update_speed_ms}ms
            </Badge>
            <Button variant="ghost" onClick={() => setDepthSpeed(settings.orderbook_update_speed_ms === 100 ? 1000 : 100)}>
              Cambiar a {settings.orderbook_update_speed_ms === 100 ? "1000ms" : "100ms"}
            </Button>
          </div>
          <p className="text-xs text-slate-500">
            100ms = 10 actualizaciones por segundo por símbolo (mucho más tráfico); 1000ms = 1 por segundo. El motor
            solo usa esto para estimar el spread, no necesita más velocidad que 1s.
          </p>
        </div>
      </div>
    </Card>
  );
}

export function SettingsPage() {
  const { settings, refreshSettings } = useOutletContext<{ settings: SettingsType | null; refreshSettings: () => void }>();
  const [tab, setTab] = useState<"wizard" | "risk" | "mode" | "auto" | "network">(settings?.wizard_completed ? "risk" : "wizard");
  const [risk, setRisk] = useState<Partial<SettingsType>>({});
  const [showLiveConfirm, setShowLiveConfirm] = useState(false);
  const [connectivity, setConnectivity] = useState<any>(null);
  const [autoSelectMaxSymbols, setAutoSelectMaxSymbols] = useState(1);
  const [autoSelectMinVolume, setAutoSelectMinVolume] = useState(5_000_000);

  useEffect(() => {
    if (settings) {
      setRisk(settings);
      setAutoSelectMaxSymbols(settings.auto_select_max_symbols);
      setAutoSelectMinVolume(settings.auto_select_min_volume_usdt);
    }
  }, [settings]);

  if (!settings) return null;

  async function saveRisk() {
    await settingsApi.updateRisk(risk);
    refreshSettings();
    alert("Configuración de riesgo guardada");
  }

  async function goToStep(step: number) {
    await settingsApi.updateWizard(step);
    refreshSettings();
  }

  async function finishWizard() {
    await settingsApi.updateWizard(9, true);
    refreshSettings();
  }

  async function testConn() {
    setConnectivity(await binanceApi.testConnectivity());
  }

  async function toggleAutoSelect() {
    await settingsApi.updateAutoSelect({ enabled: !settings!.auto_select_symbols_enabled });
    refreshSettings();
  }

  async function saveAutoSelectParams() {
    await settingsApi.updateAutoSelect({ max_symbols: autoSelectMaxSymbols, min_volume_usdt: autoSelectMinVolume });
    refreshSettings();
    alert("Parámetros de selección automática guardados");
  }

  async function changeMode(mode: string, phrase?: string) {
    try {
      await settingsApi.changeMode(mode, phrase);
      refreshSettings();
    } catch (e: any) {
      alert(e.message);
    } finally {
      setShowLiveConfirm(false);
    }
  }

  const step = settings.wizard_step;

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex gap-2">
        <button onClick={() => setTab("wizard")} className={`px-3 py-1.5 rounded text-sm ${tab === "wizard" ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"}`}>
          Asistente
        </button>
        <button onClick={() => setTab("risk")} className={`px-3 py-1.5 rounded text-sm ${tab === "risk" ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"}`}>
          Riesgo y costos
        </button>
        <button onClick={() => setTab("mode")} className={`px-3 py-1.5 rounded text-sm ${tab === "mode" ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"}`}>
          Modo de operación
        </button>
        <button onClick={() => setTab("auto")} className={`px-3 py-1.5 rounded text-sm ${tab === "auto" ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"}`}>
          Selección automática
        </button>
        <button onClick={() => setTab("network")} className={`px-3 py-1.5 rounded text-sm ${tab === "network" ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"}`}>
          Red
        </button>
      </div>

      {tab === "wizard" && (
        <Card title={`Paso ${step} de 9: ${WIZARD_STEPS[step - 1]?.title}`}>
          <p className="text-sm text-slate-400 mb-4">{WIZARD_STEPS[step - 1]?.desc}</p>

          {step === 1 && (
            <div className="space-y-3">
              <p className="text-sm">Las credenciales se configuran por variables de entorno (.env), nunca desde la UI.</p>
              <Button onClick={testConn}>Probar conexión</Button>
              {connectivity && (
                <p className={connectivity.ping ? "text-emerald-400" : "text-red-400"}>
                  {connectivity.ping ? "Conexión OK" : connectivity.error}
                </p>
              )}
            </div>
          )}
          {step === 2 && (
            <Link to="/market" className="text-blue-400 underline text-sm">
              Ir a Market para sincronizar y seleccionar pares
            </Link>
          )}
          {step === 3 && <WizardStepHistoricalData />}
          {step === 4 && (
            <Link to="/strategies" className="text-blue-400 underline text-sm">
              Ir a Strategies para revisar parámetros
            </Link>
          )}
          {step === 5 && (
            <button onClick={() => setTab("risk")} className="text-blue-400 underline text-sm">
              Ir a la pestaña de Riesgo y costos
            </button>
          )}
          {step === 6 && (
            <Link to="/backtesting" className="text-blue-400 underline text-sm">
              Ir a Backtesting
            </Link>
          )}
          {step === 7 && <p className="text-sm">Verificar que el modo actual sea PAPER y encender el bot desde la barra superior.</p>}
          {step === 8 && <p className="text-sm">Cuando los resultados en Paper sean satisfactorios, cambiar el modo a TESTNET (pestaña Modo).</p>}
          {step === 9 && <p className="text-sm">Solo después de validar en Testnet, considerar activar LIVE (pestaña Modo). Requiere confirmación explícita.</p>}

          <div className="flex justify-between mt-6">
            <Button variant="ghost" disabled={step <= 1} onClick={() => goToStep(step - 1)}>
              Anterior
            </Button>
            {step < 9 ? (
              <Button onClick={() => goToStep(step + 1)}>Siguiente</Button>
            ) : (
              <Button variant="success" onClick={finishWizard}>
                Finalizar asistente
              </Button>
            )}
          </div>
        </Card>
      )}

      {tab === "risk" && (
        <Card title="Límites de riesgo y modelo de costos">
          <div className="grid grid-cols-2 gap-4">
            {([
              ["max_risk_per_trade_pct", "Riesgo máx. por operación (%)"],
              ["max_total_exposure_pct", "Exposición total máxima (%)"],
              ["max_position_size_pct", "Tamaño máx. de posición (%)"],
              ["max_daily_loss_pct", "Pérdida diaria máxima (%)"],
              ["max_weekly_loss_pct", "Pérdida semanal máxima (%)"],
              ["max_open_positions", "Máx. posiciones abiertas"],
              ["max_consecutive_losses", "Máx. pérdidas consecutivas"],
              ["min_expected_net_profit_pct", "Ganancia neta mínima esperada (%)"],
              ["taker_fee_pct", "Comisión taker (%)"],
              ["default_slippage_pct", "Slippage estimado (%)"],
              ["paper_starting_balance_usdt", "Capital inicial Paper (USDT)"],
            ] as [keyof SettingsType, string][]).map(([key, label]) => (
              <div key={key}>
                <label className="text-xs text-slate-500">{label}</label>
                <input
                  type="number"
                  className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
                  value={(risk as any)[key] ?? ""}
                  onChange={(e) => setRisk({ ...risk, [key]: Number(e.target.value) })}
                />
              </div>
            ))}
          </div>
          <Button className="mt-4" onClick={saveRisk}>
            Guardar
          </Button>
        </Card>
      )}

      {tab === "mode" && (
        <Card title="Modo de operación">
          <p className="text-sm text-slate-400 mb-4">
            Modo actual: <Badge tone={settings.mode === "LIVE" ? "bad" : settings.mode === "TESTNET" ? "warn" : "good"}>{settings.mode}</Badge>
          </p>
          <div className="flex gap-3">
            <Button variant={settings.mode === "PAPER" ? "primary" : "ghost"} onClick={() => changeMode("PAPER")}>
              PAPER
            </Button>
            <Button variant={settings.mode === "TESTNET" ? "primary" : "ghost"} onClick={() => changeMode("TESTNET")}>
              TESTNET
            </Button>
            <Button variant="danger" onClick={() => setShowLiveConfirm(true)}>
              Activar LIVE
            </Button>
          </div>
          {!settings.wizard_completed && <p className="text-amber-400 text-sm mt-3">Completar el asistente antes de activar LIVE.</p>}
        </Card>
      )}

      {tab === "auto" && (
        <Card title="Selección automática de símbolos">
          <p className="text-sm text-slate-400 mb-4">
            Cuando está activada, la herramienta elige sola qué pares USDT analizar y operar, en vez de elegirlos a
            mano en Market: cada ~15 minutos ordena todos los pares líquidos por cuánto se movieron en las últimas 24h
            y selecciona los más activos. Nunca toca un símbolo que hayas seleccionado manualmente.
          </p>
          <div className="flex items-center gap-3 mb-4">
            <span className="text-sm">Estado:</span>
            <Badge tone={settings.auto_select_symbols_enabled ? "good" : "neutral"}>
              {settings.auto_select_symbols_enabled ? "ACTIVADA" : "DESACTIVADA"}
            </Badge>
            <Button variant={settings.auto_select_symbols_enabled ? "danger" : "success"} onClick={toggleAutoSelect}>
              {settings.auto_select_symbols_enabled ? "Desactivar" : "Activar"}
            </Button>
          </div>
          <div className="grid grid-cols-2 gap-4 max-w-md">
            <div>
              <label className="text-xs text-slate-500">Cantidad máxima de símbolos</label>
              <input
                type="number"
                min={1}
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
                value={autoSelectMaxSymbols}
                onChange={(e) => setAutoSelectMaxSymbols(Number(e.target.value))}
              />
            </div>
            <div>
              <label className="text-xs text-slate-500">Volumen mínimo 24h (USDT)</label>
              <input
                type="number"
                min={0}
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
                value={autoSelectMinVolume}
                onChange={(e) => setAutoSelectMinVolume(Number(e.target.value))}
              />
            </div>
          </div>
          <Button className="mt-4" onClick={saveAutoSelectParams}>
            Guardar
          </Button>
          {autoSelectMaxSymbols > 1 && (
            <p className="text-amber-400 text-xs mt-3">
              Con el capital real actual, operar varios símbolos a la vez puede dejar cada posición al límite del
              mínimo de Binance (~US$5 por orden) o directamente por debajo. Si el capital es chico, conviene dejarlo
              en 1.
            </p>
          )}
        </Card>
      )}

      {tab === "network" && <NetworkUsagePanel settings={settings} refreshSettings={refreshSettings} />}

      {showLiveConfirm && (
        <ConfirmDialog
          title="Activar modo LIVE"
          danger
          requireText="ACTIVAR LIVE"
          confirmLabel="Activar LIVE"
          onConfirm={() => changeMode("LIVE", "ACTIVAR LIVE")}
          onCancel={() => setShowLiveConfirm(false)}
        >
          <p className="text-red-400 font-semibold">Esto habilitará operaciones con dinero real contra Binance.</p>
          <p>Asegurate de haber validado la estrategia en Paper y Testnet antes de continuar.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
