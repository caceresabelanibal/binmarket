import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      navigate("/");
    } catch (e: any) {
      setError(e.message || "Error al iniciar sesión");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950">
      <form onSubmit={onSubmit} className="bg-slate-900 border border-slate-800 rounded-lg p-8 w-full max-w-sm space-y-4">
        <h1 className="text-2xl font-bold text-blue-400 text-center">BinMarket</h1>
        <p className="text-xs text-slate-500 text-center">Plataforma de trading automatizado — uso interno</p>
        <input
          className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
          placeholder="Usuario"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <input
          type="password"
          className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
          placeholder="Contraseña"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <p className="text-red-400 text-sm">{error}</p>}
        <Button type="submit" disabled={busy} className="w-full">
          Iniciar sesión
        </Button>
      </form>
    </div>
  );
}
