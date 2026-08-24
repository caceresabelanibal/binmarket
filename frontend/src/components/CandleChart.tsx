import { useEffect, useRef } from "react";
import { createChart, IChartApi, ISeriesApi, SeriesMarker, Time } from "lightweight-charts";
import type { Candle } from "../api/types";

export interface TradeMarker {
  time: string;
  price: number;
  side: "BUY" | "SELL";
  text?: string;
}

function toUnixTime(iso: string): Time {
  return (Math.floor(new Date(iso).getTime() / 1000)) as Time;
}

export function CandleChart({ candles, markers = [], height = 380 }: { candles: Candle[]; markers?: TradeMarker[]; height?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      height,
      layout: { background: { color: "#0f172a" }, textColor: "#94a3b8" },
      grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    const series = chart.addCandlestickSeries({
      upColor: "#10b981",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const resize = () => chart.applyOptions({ width: containerRef.current?.clientWidth ?? 600 });
    resize();
    window.addEventListener("resize", resize);

    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [height]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.setData(
      candles.map((c) => ({
        time: toUnixTime(c.open_time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );
  }, [candles]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const seriesMarkers: SeriesMarker<Time>[] = markers.map((m) => ({
      time: toUnixTime(m.time),
      position: m.side === "BUY" ? "belowBar" : "aboveBar",
      color: m.side === "BUY" ? "#10b981" : "#ef4444",
      shape: m.side === "BUY" ? "arrowUp" : "arrowDown",
      text: m.text ?? m.side,
    }));
    series.setMarkers(seriesMarkers);
  }, [markers]);

  return <div ref={containerRef} className="w-full" />;
}
