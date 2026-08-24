import { useEffect, useRef, useState } from "react";
import { marketApi } from "../api/endpoints";
import type { SyncJob } from "../api/types";

const POLL_INTERVAL_MS = 1500;

/** Polls a single backfill job until it finishes, showing an honest
 * indeterminate progress bar (we don't know the total candle count ahead of
 * time) plus a live count of candles synced so far and queue position — the
 * whole point is that the user can SEE it's working instead of wondering
 * whether it's stuck. */
export function BackfillProgress({ jobId, onDone }: { jobId: string; onDone?: (job: SyncJob) => void }) {
  const [job, setJob] = useState<SyncJob | null>(null);
  const [queueLength, setQueueLength] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    let stopped = false;
    let pollTimeout: ReturnType<typeof setTimeout>;
    const startedAt = Date.now();
    const tickInterval = setInterval(() => setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000)), 1000);

    async function poll() {
      try {
        const [currentJob, queue] = await Promise.all([
          marketApi.backfillJob(jobId),
          marketApi.backfillQueueLength(),
        ]);
        if (stopped) return;
        setJob(currentJob);
        setQueueLength(queue.pending_in_queue);
        if (currentJob.status === "DONE" || currentJob.status === "FAILED") {
          clearInterval(tickInterval);
          onDoneRef.current?.(currentJob);
          return;
        }
      } catch {
        // transient error reading status — keep polling, don't give up
      }
      if (!stopped) pollTimeout = setTimeout(poll, POLL_INTERVAL_MS);
    }

    poll();
    return () => {
      stopped = true;
      clearInterval(tickInterval);
      clearTimeout(pollTimeout);
    };
  }, [jobId]);

  if (!job) {
    return <p className="text-sm text-slate-500">Consultando estado del trabajo...</p>;
  }

  if (job.status === "DONE") {
    return job.candles_synced > 0 ? (
      <p className="text-emerald-400 text-sm">
        ✓ Completado: {job.candles_synced} velas descargadas para {job.symbol} ({job.timeframe}).
      </p>
    ) : (
      <p className="text-amber-400 text-sm">
        Terminó sin descargar velas nuevas para {job.symbol} ({job.timeframe}). Puede ser que ya estuvieran
        descargadas, o que el símbolo no tenga historial en el rango solicitado.
      </p>
    );
  }

  if (job.status === "FAILED") {
    return (
      <p className="text-red-400 text-sm">
        Error al descargar el histórico de {job.symbol}: {job.error_message}
      </p>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 text-sm text-slate-300">
        <span className="inline-block w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
        <span>
          {job.status === "PENDING" ? "En cola" : "Descargando"} {job.symbol} ({job.timeframe})
          {job.candles_synced > 0 && ` — ${job.candles_synced} velas hasta ahora`}
        </span>
        <span className="text-slate-500">{elapsedSeconds}s</span>
      </div>
      {queueLength !== null && queueLength > 0 && (
        <p className="text-xs text-slate-500">{queueLength} trabajo(s) más esperando su turno en la cola.</p>
      )}
      <div className="w-full h-1.5 bg-slate-800 rounded overflow-hidden relative">
        <div className="absolute inset-y-0 w-1/3 bg-blue-500 rounded progress-indeterminate" />
      </div>
      <p className="text-xs text-slate-600">
        Tiempo de descarga: velas de 1 minuto en rangos largos pueden tardar varios minutos por el límite de
        Binance de 1000 velas por request.
      </p>
    </div>
  );
}
