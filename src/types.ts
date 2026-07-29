export type SignalDirection = 'BUY' | 'SELL' | 'HOLD' | 'NEUTRAL';

export type SignalStatus = 'ACTIVE' | 'TRIGGERED' | 'TARGET_REACHED' | 'STOP_HIT' | 'EXPIRED';

export type TimeFrame = '1m' | '5m' | '15m' | '1h' | '4h' | '1d';

export type StrategyType = 
  | 'RSI_MACD_Confluence'
  | 'Bollinger_Breakout'
  | 'EMA_Cross_Trend'
  | 'Volume_Profile_Spike'
  | 'Grid_Scalper';

export interface IndicatorData {
  rsi: number;
  macdValue: number;
  macdSignal: number;
  macdHist: number;
  ema50: number;
  ema200: number;
  bollingerUpper: number;
  bollingerLower: number;
  volume24hRatio: number; // e.g. 1.8x average
  sentimentScore: number; // 0-100 bullish/bearish
}

export interface TradingAccount {
  id: string;
  name: string;
  exchange: string;
  accountType: 'LIVE' | 'PAPER' | 'SUB_ACCOUNT';
  balanceInr: number;
  unrealizedPnlInr: number;
  realizedPnlInr: number;
  activePositionsCount: number;
  dailyWinRate: number;
  apiKeyStatus: 'CONNECTED' | 'DISCONNECTED' | 'EXPIRING';
  isPrimary: boolean;
  assignedStrategy: string;
  accountNumber: string;
}

export interface TradingSignal {
  id: string;
  symbol: string;
  direction: SignalDirection;
  strategy: StrategyType;
  accountId?: string;
  entryPrice: number;
  currentPrice: number;
  targetPrice: number;
  stopLoss: number;
  takeProfit1: number;
  takeProfit2: number;
  confidence: number; // 0 - 100
  status: SignalStatus;
  timestamp: string;
  timeframe: TimeFrame;
  indicators: IndicatorData;
  telegramSent: boolean;
  reasoning: string;
  riskRewardRatio: number;
  estimatedProfitInr?: number;
}

export interface StrategyMetrics {
  id: string;
  name: StrategyType;
  displayName: string;
  description: string;
  winRate: number; // percentage e.g. 74.2
  totalTrades: number;
  profitTrades: number;
  lossTrades: number;
  netProfitInr: number;
  netProfitUsdt?: number;
  netProfitPercent: number;
  profitFactor: number;
  maxDrawdown: number;
  sharpeRatio: number;
  avgHoldTime: string;
  status: 'RUNNING' | 'PAUSED' | 'TESTING';
  riskPerTrade: number;
  activePairs: string[];
  isCoreStrategy?: boolean; // Highlight the 2 main strategies
  primaryAccountId?: string;
}

export interface BotStatus {
  isRunning: boolean;
  mode: 'LIVE_TRADING' | 'PAPER_TRADING' | 'SIGNAL_ONLY';
  selectedAccountId?: string;
  totalBalanceInr?: number;
  uptimeSeconds: number;
  telegramConnected: boolean;
  telegramBotUsername: string;
  telegramChatId: string;
  exchangeConnected: boolean;
  exchangeName: string;
  activePairsCount: number;
  currentRamMb: number;
  maxRamMb: number; // 512 for Render free tier
  ramUsagePercent: number;
  cpuUsagePercent: number;
  renderFreeTierHealth: 'OPTIMAL' | 'MODERATE_MEM' | 'HIGH_MEM_WARNING' | 'CRITICAL_LEAK';
  totalSignalsGenerated: number;
  telegramMessagesSent: number;
  latencyMs: number;
  lastPulse: string;
  ramSaverMode: boolean;
}

export interface SystemLog {
  id: string;
  timestamp: string;
  level: 'INFO' | 'WARN' | 'ERROR' | 'SIGNAL' | 'TELEGRAM' | 'RAM_WATCHDOG';
  category: string;
  message: string;
  memoryMb?: number;
}

export interface RiskSettings {
  maxDrawdownCap: number; // e.g. 15%
  defaultStopLoss: number; // e.g. 2%
  defaultTakeProfit: number; // e.g. 5%
  maxTradesPerDay: number; // e.g. 20
  maxPortfolioRisk: number; // e.g. 5%
  trailingStopEnabled: boolean;
  ramSaverMode: boolean;
  telegramNotifications: boolean;
  autoGcIntervalMinutes: number; // For Render 512MB RAM
}

export interface EquityPoint {
  date: string;
  equity: number; // USDT
  benchmark: number; // Buy & Hold BTC
  drawdown: number; // %
}
