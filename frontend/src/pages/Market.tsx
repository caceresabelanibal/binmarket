import { useEffect, useRef, useState } from "react";
import { marketApi, symbolsApi } from "../api/endpoints";
import type { Candle, SymbolInfo } from "../api/types";
import { Badge, Button, Card, fmtPct, fmtUsd, Table } from "../components/ui";
import { CandleChart } from "../components/CandleChart";
import { BackfillProgress } from "../components/BackfillProgress";
import { useLiveFeed } from "../ws/useLiveFeed";

const TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"];
const PAGE_SIZES = [20, 50, 100];
const SEARCH_DEBOUNCE_MS = 300;

export function Market() {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [timeframe, setTimeframe] = useState("1h");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [backfillJobId, setBackfillJobId] = useState<string | null>(null);
  const { prices } = useLiveFeed();

  // Debounce free-text typing before it becomes the actual query.
  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [searchInput]);

  // A new search always starts back at page 1 (a stale page number combined
  // with a narrower filter could otherwise show an empty page and look like
  // "the filter returned nothing").
  useEffect(() => {
    setPage(1);
  }, [search, pageSize]);

  // Guards against a real race: firing a broad query then a narrow one in
  // quick succession, where the broad one's response arrives last and
  // clobbers the narrow, correct result — which looks exactly like "the
  // filter doesn't work" from the user's side.
  const latestRequestId = useRef(0);

  async function loadSymbols() {
    const requestId = ++latestRequestId.current;
    setLoading(true);
    try {
      const result = await symbolsApi.list({ search: search || undefined, page, page_size: pageSize });
      if (requestId !== latestRequestId.current) return; // a newer request has since started; drop this one
      setSymbols(result.items);
      setTotal(result.total);
    } finally {
      if (requestId === latestRequestId.current) setLoading(false);
    }
  }

  useEffect(() => {
    loadSymbols();
  }, [search, page, pageSize]);

  useEffect(() => {
    if (!selectedSymbol) return;
    marketApi.candles(selectedSymbol, timeframe, 500).then(setCandles).catch(() => setCandles([]));
    setBackfillJobId(null);
  }, [selectedSymbol, timeframe]);

  async function sync() {
    setSyncing(true);
    try {
      const res = await symbolsApi.sync();
      alert(`Sincronizado: ${res.created} nuevos, ${res.updated} actualizados`);
      await loadSymbols();
    } catch (e: any) {
      alert(e.message);
    } finally {
      setSyncing(false);
    }
  }

  async function toggleSelect(s: SymbolInfo) {
    const updated = await symbolsApi.select(s.symbol, !s.is_selected);
    setSymbols((prev) => prev.map((x) => (x.symbol === updated.symbol ? updated : x)));
  }

  async function toggleFavorite(s: SymbolInfo) {
    const updated = await symbolsApi.favorite(s.symbol, !s.is_favorite);
    setSymbols((prev) => prev.map((x) => (x.symbol === updated.symbol ? updated : x)));
  }

  async function requestBackfill() {
    if (!selectedSymbol) return;
    const start = new Date();
    start.setDate(start.getDate() - 90);
    const job = await marketApi.backfill(selectedSymbol, timeframe, start.toISOString());
    setBackfillJobId(job.id);
  }

  function onBackfillDone() {
    if (selectedSymbol) marketApi.candles(selectedSymbol, timeframe, 500).then(setCandles).catch(() => {});
  }

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-wrap gap-3 items-center justify-between">
          <input
            className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm w-64"
            placeholder="Buscar símbolo (ej. BTC)"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
          <Button onClick={sync} disabled={syncing}>
            {syncing ? "Sincronizando..." : "Sincronizar pares desde Binance"}
          </Button>
        </div>
      </Card>

      <Card>
        <div className="flex items-center justify-between mb-3 text-sm text-slate-400">
          <span>
            {loading
              ? "Buscando..."
              : total === 0
                ? "Sin resultados"
                : `Mostrando ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} de ${total}`}
          </span>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500">Por página</label>
            <select
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm"
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </div>
        </div>

        <Table headers={["", "Símbolo", "Precio", "24h %", "Volumen 24h", "Favorito", "Analizar"]}>
          {symbols.map((s) => {
            const livePrice = prices[s.symbol] ?? s.last_price;
            return (
              <tr key={s.symbol} className="hover:bg-slate-800/40 cursor-pointer" onClick={() => setSelectedSymbol(s.symbol)}>
                <td className="py-2 px-2">{s.symbol === selectedSymbol && <Badge tone="good">viendo</Badge>}</td>
                <td className="py-2 px-2 font-medium">
                  {s.symbol} {s.is_auto_selected && <Badge tone="warn">AUTO</Badge>}
                </td>
                <td className="py-2 px-2">{fmtUsd(livePrice, livePrice && livePrice < 1 ? 6 : 2)}</td>
                <td className={`py-2 px-2 ${(s.price_change_pct_24h ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {fmtPct(s.price_change_pct_24h)}
                </td>
                <td className="py-2 px-2 text-slate-400">{s.volume_24h?.toLocaleString() ?? "—"}</td>
                <td className="py-2 px-2">
                  <button onClick={(e) => (e.stopPropagation(), toggleFavorite(s))}>{s.is_favorite ? "★" : "☆"}</button>
                </td>
                <td className="py-2 px-2">
                  <input type="checkbox" checked={s.is_selected} onChange={(e) => (e.stopPropagation(), toggleSelect(s))} onClick={(e) => e.stopPropagation()} />
                </td>
              </tr>
            );
          })}
        </Table>

        <div className="flex items-center justify-between mt-4">
          <Button variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            ← Anterior
          </Button>
          <span className="text-sm text-slate-500">
            Página {page} de {Math.max(1, Math.ceil(total / pageSize))}
          </span>
          <Button variant="ghost" disabled={page * pageSize >= total} onClick={() => setPage((p) => p + 1)}>
            Siguiente →
          </Button>
        </div>
      </Card>

      {selectedSymbol && (
        <Card title={`${selectedSymbol} — velas`}>
          <div className="flex gap-2 mb-3">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-2 py-1 rounded text-xs ${tf === timeframe ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"}`}
              >
                {tf}
              </button>
            ))}
            <Button variant="ghost" className="ml-auto" onClick={requestBackfill}>
              Descargar histórico (90 días)
            </Button>
          </div>
          {backfillJobId && (
            <div className="mb-3">
              <BackfillProgress key={backfillJobId} jobId={backfillJobId} onDone={onBackfillDone} />
            </div>
          )}
          {candles.length === 0 ? (
            <p className="text-sm text-slate-500">Sin datos históricos todavía. Usar "Descargar histórico".</p>
          ) : (
            <CandleChart candles={candles} />
          )}
        </Card>
      )}
    </div>
  );
}
