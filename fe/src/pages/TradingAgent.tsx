import { PageHeader } from '../components/ui/PageHeader'
import { DashboardTradingChatPanel } from '../components/dashboard/DashboardTradingChatPanel'

export default function TradingAgent() {
  return (
    <div>
      <PageHeader
        title="Trading Agent"
        description="Ask what to buy or sell now — India, US, crypto, commodities — for scalping, intraday, swing, or investing. Standard BB + confluence, or Deep mode with backtest-ranked strategies and encyclopedia how-tos. Conclusions use Manage → AI Settings."
      />
      <DashboardTradingChatPanel />
    </div>
  )
}
