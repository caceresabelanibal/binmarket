import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Trading } from "./pages/Trading";
import { Market } from "./pages/Market";
import { Strategies } from "./pages/Strategies";
import { Backtesting } from "./pages/Backtesting";
import { Portfolio } from "./pages/Portfolio";
import { Orders } from "./pages/Orders";
import { Positions } from "./pages/Positions";
import { Signals } from "./pages/Signals";
import { Risk } from "./pages/Risk";
import { Logs } from "./pages/Logs";
import { BinancePage } from "./pages/Binance";
import { SettingsPage } from "./pages/Settings";

function ProtectedLayout() {
  const { username, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-slate-500">Cargando...</div>;
  if (!username) return <Navigate to="/login" replace />;
  return <Layout />;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<ProtectedLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/trading" element={<Trading />} />
          <Route path="/market" element={<Market />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/backtesting" element={<Backtesting />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/risk" element={<Risk />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/binance" element={<BinancePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
