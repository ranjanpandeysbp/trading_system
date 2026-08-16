import { PageHeader } from '../components/ui/PageHeader'
import { DashboardTradingChatPanel } from '../components/dashboard/DashboardTradingChatPanel'

export default function TradingAgent() {
  return (
    <div>
      <PageHeader
        title="Trading Agent"
        description="Technical Agent desk — ask what to buy or sell, or open questions (24h movers, support/resistance). Save outputs or run Deep scans in the background. Conclusions use Manage → AI Settings."
      />
      <DashboardTradingChatPanel />
    </div>
  )
}
