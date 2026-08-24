import { useEffect, useState } from "react";
import { strategiesApi } from "../api/endpoints";
import type { Strategy } from "../api/types";
import { Badge, Button, Card } from "../components/ui";

export function Strategies() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  async function load() {
    setStrategies(await strategiesApi.list());
  }

  useEffect(() => {
    load();
  }, []);

  async function toggle(s: Strategy) {
    const updated = await strategiesApi.update(s.name, { is_enabled: !s.is_enabled });
    setStrategies((prev) => prev.map((x) => (x.name === updated.name ? updated : x)));
  }

  async function saveParams(s: Strategy) {
    const raw = drafts[s.name];
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw);
      const updated = await strategiesApi.update(s.name, { parameters: parsed });
      setStrategies((prev) => prev.map((x) => (x.name === updated.name ? updated : x)));
    } catch {
      alert("JSON inválido");
    }
  }

  return (
    <div className="space-y-4">
      {strategies.map((s) => (
        <Card key={s.name} title={s.name}>
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <p className="text-sm text-slate-400 mb-2">{s.description}</p>
              <div className="flex items-center gap-2 mb-3">
                <Badge tone={s.is_enabled ? "good" : "neutral"}>{s.is_enabled ? "Habilitada" : "Deshabilitada"}</Badge>
                <span className="text-xs text-slate-500">v{s.version}</span>
              </div>
              <textarea
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-xs font-mono h-28"
                defaultValue={JSON.stringify(s.parameters, null, 2)}
                onChange={(e) => setDrafts((prev) => ({ ...prev, [s.name]: e.target.value }))}
              />
              <Button variant="ghost" className="mt-2" onClick={() => saveParams(s)}>
                Guardar parámetros
              </Button>
            </div>
            <Button variant={s.is_enabled ? "danger" : "success"} onClick={() => toggle(s)}>
              {s.is_enabled ? "Deshabilitar" : "Habilitar"}
            </Button>
          </div>
        </Card>
      ))}
    </div>
  );
}
