import { PageHeader } from '../components/ui/PageHeader'
import { DashboardTradingChatPanel } from '../components/dashboard/DashboardTradingChatPanel'

export default function TradingAgent() {
  return (
    <div>
      <PageHeader
        title="Trading Agent"
        description="Technical Agent — pure Price Action desk (Support/Resistance · Volume · RSI · Bollinger Bands). Ask what to buy or sell, or open questions (24h movers, S/R breaks). Save outputs or run Deep (broader universe) in the background. Conclusions use Manage → AI Settings."
      />
      <DashboardTradingChatPanel />
    </div>
  )
}
