import { useEffect, useRef, useState } from "react";

interface LiveMessage {
  channel: string;
  data: string;
}

/** Single shared WebSocket to the backend's `/ws` fan-out. Reconnects with a
 * fixed backoff on drop; consumers read the latest price map + a rolling
 * list of raw messages (signals/orders/bot-state) they can filter as needed.
 */
export function useLiveFeed() {
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [lastMessage, setLastMessage] = useState<LiveMessage | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let stopped = false;
    let retryDelay = 1000;

    function connect() {
      if (stopped) return;
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${protocol}://${window.location.host}/ws`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        retryDelay = 1000;
      };

      ws.onmessage = (event) => {
        try {
          const parsed: LiveMessage = JSON.parse(event.data);
          setLastMessage(parsed);
          if (parsed.channel.includes("price-updates")) {
            const payload = JSON.parse(parsed.data);
            if (payload.symbol && typeof payload.price === "number") {
              setPrices((prev) => ({ ...prev, [payload.symbol]: payload.price }));
            }
          }
        } catch {
          /* ignore malformed message */
        }
      };

      ws.onclose = () => {
        setConnected(false);
        if (!stopped) {
          setTimeout(connect, retryDelay);
          retryDelay = Math.min(retryDelay * 1.5, 15000);
        }
      };

      ws.onerror = () => ws.close();
    }

    connect();
    return () => {
      stopped = true;
      wsRef.current?.close();
    };
  }, []);

  return { prices, lastMessage, connected };
}
