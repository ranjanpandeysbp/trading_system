import { PageHeader } from '../components/ui/PageHeader'
import { DashboardTradingChatPanel } from '../components/dashboard/DashboardTradingChatPanel'

export default function TradingAgent() {
  return (
    <div>
      <PageHeader
        title="Trading Agent"
        description="Ask what to buy or sell — or open questions like which stocks, crypto, commodities, gold or silver moved a lot in 24h, fallen most, or broke recent support/resistance. Standard BB + confluence, Deep mode with backtests + Strategies catalog how-tos, or market-mover / S&R screens. Conclusions use Manage → AI Settings."
      />
      <DashboardTradingChatPanel />
    </div>
  )
}
