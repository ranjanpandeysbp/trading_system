import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { ProtectedRoute } from './components/auth/ProtectedRoute'
import StrategyLab from './pages/StrategyLab'
import Seasonality from './pages/Seasonality'
import YoutubeAnalysis from './pages/YoutubeAnalysis'
import InvestingAgent from './pages/InvestingAgent'
import Alerts from './pages/Alerts'
import WatchlistPage from './pages/Watchlist'
import CommandCenter from './pages/CommandCenter'
import Dashboard from './pages/Dashboard'
import Scanner from './pages/Scanner'
import Backtester from './pages/Backtester'
import Strategies from './pages/Strategies'
import MarketPulse from './pages/MarketPulse'
import TechnicalAnalysis from './pages/TechnicalAnalysis'
import EtfTaIn from './pages/EtfTaIn'
import TradingHubs from './pages/TradingHubs'
import TradeCandidate from './pages/TradeCandidate'
import Options from './pages/Options'
import ProTrade from './pages/ProTrade'
import PaperTrading from './pages/PaperTrading'
import ManageSettings from './pages/ManageSettings'
import Login from './pages/Login'
import Register from './pages/Register'
import ForgotPassword from './pages/ForgotPassword'
import ResetPassword from './pages/ResetPassword'
import { useAuth } from './context/AuthContext'
import { Loading } from './components/ui/Feedback'

function PublicOnly({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loading message="Loading..." />
      </div>
    )
  }
  if (isAuthenticated) return <Navigate to="/" replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicOnly>
            <Login />
          </PublicOnly>
        }
      />
      <Route
        path="/register"
        element={
          <PublicOnly>
            <Register />
          </PublicOnly>
        }
      />
      <Route
        path="/forgot-password"
        element={
          <PublicOnly>
            <ForgotPassword />
          </PublicOnly>
        }
      />
      <Route path="/reset-password" element={<ResetPassword />} />

      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <AppLayout>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/command-center" element={<CommandCenter />} />
                <Route path="/strategies" element={<Strategies />} />
                <Route path="/strategies/:id" element={<Strategies />} />
                <Route path="/market-pulse" element={<MarketPulse />} />
                <Route path="/technical-analysis" element={<TechnicalAnalysis />} />
                <Route path="/strategy-lab" element={<StrategyLab />} />
                <Route path="/seasonality" element={<Seasonality />} />
                <Route path="/youtube-analysis" element={<YoutubeAnalysis />} />
                <Route path="/investing-agent" element={<InvestingAgent />} />
                <Route path="/alerts" element={<Alerts />} />
                <Route path="/watchlist" element={<WatchlistPage />} />
                <Route path="/trading-hubs" element={<TradingHubs />} />
                <Route path="/trade-candidate" element={<Navigate to="/trade-candidate/configure" replace />} />
                <Route path="/trade-candidate/:tab" element={<TradeCandidate />} />
                <Route path="/options" element={<Options />} />
                <Route path="/pro-trade" element={<Navigate to="/pro-trade/volume-profile-ce" replace />} />
                <Route path="/pro-trade/:tab" element={<ProTrade />} />
                <Route path="/etf-ta-in" element={<EtfTaIn />} />
                <Route path="/scanner" element={<Scanner />} />
                <Route path="/backtester" element={<Backtester />} />
                <Route path="/paper" element={<PaperTrading />} />
                <Route path="/settings" element={<ManageSettings />} />
              </Routes>
            </AppLayout>
          </ProtectedRoute>
        }
      />
    </Routes>
  )
}
