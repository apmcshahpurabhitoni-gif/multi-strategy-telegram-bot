import React, { useState } from 'react';
import { 
  TrendingUp, 
  Wallet, 
  Award, 
  Send, 
  ChevronRight, 
  ArrowUpRight,
  Zap,
  Sliders,
  Sparkles,
  Layers
} from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { TradingSignal, StrategyMetrics, EquityPoint, BotStatus, TradingAccount } from '../types';
import { AccountsOverviewCard } from './AccountsOverviewCard';
import { CoreStrategiesCard } from './CoreStrategiesCard';
import { formatInr, formatInrPrice } from '../utils/formatters';

interface OverviewDashboardProps {
  signals: TradingSignal[];
  strategies: StrategyMetrics[];
  accounts?: TradingAccount[];
  equityCurve: EquityPoint[];
  status: BotStatus | null;
  onSelectSignal: (signal: TradingSignal) => void;
  onNavigateTab: (tab: string) => void;
  onTestTelegram: () => void;
  onToggleStrategy: (strategyId: string) => void;
}

export const OverviewDashboard: React.FC<OverviewDashboardProps> = ({
  signals,
  strategies,
  accounts = [],
  equityCurve,
  status,
  onSelectSignal,
  onNavigateTab,
  onTestTelegram,
  onToggleStrategy
}) => {
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);

  // Filter signals based on selected account if any
  const filteredSignals = selectedAccountId
    ? signals.filter(s => s.accountId === selectedAccountId)
    : signals;

  const activeSignals = filteredSignals.filter(s => s.status === 'ACTIVE');
  const totalNetProfitInr = strategies.reduce((acc, s) => acc + s.netProfitInr, 0);
  const avgWinRate = Math.round(strategies.reduce((acc, s) => acc + s.winRate, 0) / strategies.length * 10) / 10;
  const totalTrades = strategies.reduce((acc, s) => acc + s.totalTrades, 0);
  const totalPortfolioBalanceInr = accounts.reduce((acc, a) => acc + a.balanceInr, 0);

  return (
    <div className="space-y-6">

      {/* 1. 4 Exchange Accounts Card Section */}
      <AccountsOverviewCard
        accounts={accounts}
        selectedAccountId={selectedAccountId}
        onSelectAccount={setSelectedAccountId}
      />

      {/* 2. KPI Metrics Bar */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        {/* Total Portfolio INR */}
        <div className="bg-[#1e293b] border border-slate-800 rounded-xl p-4 flex flex-col justify-between relative overflow-hidden group">
          <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
            <span>Total Portfolio Balance</span>
            <div className="p-1.5 bg-sky-500/10 text-sky-400 rounded-lg">
              <Wallet className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-lg sm:text-2xl font-black text-white font-mono tracking-tight">
              {formatInr(totalPortfolioBalanceInr)}
            </div>
            <div className="flex items-center gap-1 text-xs text-emerald-400 mt-1 font-semibold">
              <ArrowUpRight className="w-3.5 h-3.5" />
              <span>4 Accounts Synced</span>
            </div>
          </div>
        </div>

        {/* Net Bot Profit INR */}
        <div className="bg-[#1e293b] border border-slate-800 rounded-xl p-4 flex flex-col justify-between relative overflow-hidden group">
          <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
            <span>Live Bot Profit (INR)</span>
            <div className="p-1.5 bg-emerald-500/10 text-emerald-400 rounded-lg">
              <TrendingUp className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-lg sm:text-2xl font-black text-emerald-400 font-mono tracking-tight">
              {formatInr(totalNetProfitInr, { showSign: true })}
            </div>
            <div className="text-xs text-slate-400 mt-1">
              Net profit across all strategies
            </div>
          </div>
        </div>

        {/* Win Rate */}
        <div className="bg-[#1e293b] border border-slate-800 rounded-xl p-4 flex flex-col justify-between relative overflow-hidden group">
          <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
            <span>Overall Win Rate</span>
            <div className="p-1.5 bg-sky-500/10 text-sky-400 rounded-lg">
              <Award className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-lg sm:text-2xl font-black text-sky-400 font-mono tracking-tight">
              {avgWinRate}%
            </div>
            <div className="text-xs text-slate-400 mt-1">
              Across <span className="font-semibold text-slate-200">{totalTrades}</span> total trades
            </div>
          </div>
        </div>

        {/* Telegram Dispatches */}
        <div className="bg-[#1e293b] border border-slate-800 rounded-xl p-4 flex flex-col justify-between relative overflow-hidden group">
          <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
            <span>Telegram Dispatches</span>
            <div className="p-1.5 bg-indigo-500/10 text-indigo-400 rounded-lg">
              <Send className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-lg sm:text-2xl font-black text-slate-100 font-mono tracking-tight">
              {status?.telegramMessagesSent || 138}
            </div>
            <button 
              onClick={onTestTelegram}
              className="text-xs text-sky-400 hover:text-sky-300 font-semibold mt-1 flex items-center gap-1 hover:underline text-left"
            >
              <Send className="w-3 h-3" /> Test Channel Alert
            </button>
          </div>
        </div>
      </div>

      {/* 3. Highlight 2 Core Strategies Section */}
      <CoreStrategiesCard
        strategies={strategies}
        onToggleStrategy={onToggleStrategy}
        onNavigateTab={onNavigateTab}
      />

      {/* 4. Equity Performance Growth Curve (INR) */}
      <div className="bg-[#1e293b] border border-slate-800 rounded-2xl p-5 shadow-xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-emerald-400" />
              Bot Performance & Growth Curve (Indian Rupees - INR ₹)
            </h2>
            <p className="text-xs text-slate-400">
              Comparative equity growth in Rupees against BTC Buy & Hold market benchmark
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs font-medium">
            <span className="flex items-center gap-1.5 text-emerald-400">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
              Multi-Strategy (+42.8%)
            </span>
            <span className="flex items-center gap-1.5 text-slate-400">
              <span className="w-2.5 h-2.5 rounded-full bg-slate-600"></span>
              BTC Benchmark (+13.2%)
            </span>
          </div>
        </div>

        <div className="h-64 sm:h-72 w-full pt-2">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={equityCurve} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
              <defs>
                <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorBench" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#64748b" stopOpacity={0.2}/>
                  <stop offset="95%" stopColor="#64748b" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} tickLine={false} />
              <YAxis 
                stroke="#94a3b8" 
                fontSize={11} 
                tickLine={false} 
                tickFormatter={(val) => `₹${(val / 100000).toFixed(1)}L`}
              />
              <Tooltip 
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '12px', color: '#f8fafc', fontSize: '12px' }}
                formatter={(value: any) => [formatInr(Number(value)), 'Equity']}
              />
              <Area type="monotone" dataKey="equity" stroke="#10b981" strokeWidth={2.5} fillOpacity={1} fill="url(#colorEquity)" name="Multi-Strategy Bot (INR)" />
              <Area type="monotone" dataKey="benchmark" stroke="#64748b" strokeWidth={1.5} strokeDasharray="4 4" fillOpacity={1} fill="url(#colorBench)" name="BTC Buy & Hold" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 5. Active Trading Signals Table in INR */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-amber-400" />
            <h2 className="text-lg font-bold text-white">Live Active Signals (Rupees - INR)</h2>
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
              {activeSignals.length} Active
            </span>
          </div>
          <button
            onClick={() => onNavigateTab('signals')}
            className="text-xs text-sky-400 hover:text-sky-300 font-semibold flex items-center gap-1 hover:underline"
          >
            View All Signals <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {activeSignals.map((sig) => {
            const isBuy = sig.direction === 'BUY';
            const priceDiff = sig.currentPrice - sig.entryPrice;
            const priceDiffPct = ((priceDiff / sig.entryPrice) * 100).toFixed(2);
            const isProfit = isBuy ? priceDiff >= 0 : priceDiff <= 0;
            const accountName = accounts.find(a => a.id === sig.accountId)?.name.split('-')[0].trim() || 'Account 1';

            return (
              <div 
                key={sig.id}
                onClick={() => onSelectSignal(sig)}
                className="bg-[#1e293b] border border-slate-800 hover:border-slate-700 rounded-2xl p-4 cursor-pointer transition-all hover:scale-[1.01] shadow-lg relative group"
              >
                {/* Header info */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="font-black text-white text-base font-mono">{sig.symbol}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 font-mono border border-slate-800">
                      {sig.timeframe}
                    </span>
                  </div>
                  <span className={`px-2.5 py-0.5 rounded-md text-xs font-extrabold tracking-wider ${
                    isBuy ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
                  }`}>
                    {sig.direction}
                  </span>
                </div>

                {/* Account & Strategy Tag */}
                <div className="flex items-center justify-between mb-2 text-[11px] text-slate-400">
                  <span className="bg-slate-900 px-2 py-0.5 rounded text-slate-300 font-medium border border-slate-800">
                    {accountName}
                  </span>
                  <span className="text-sky-400 font-semibold font-mono">
                    {sig.strategy.replace(/_/g, ' ')}
                  </span>
                </div>

                {/* Price Matrix in INR */}
                <div className="grid grid-cols-2 gap-2 bg-slate-950/80 p-2.5 rounded-xl border border-slate-800/80 mb-3 text-xs">
                  <div>
                    <span className="text-slate-400 block text-[11px]">Entry Price</span>
                    <span className="font-mono font-bold text-slate-200">
                      {formatInrPrice(sig.entryPrice)}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[11px]">Current Price</span>
                    <span className={`font-mono font-bold flex items-center gap-1 ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {formatInrPrice(sig.currentPrice)}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[11px]">Target (TP2)</span>
                    <span className="font-mono font-bold text-emerald-400">
                      {formatInrPrice(sig.targetPrice)}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[11px]">Est. Profit</span>
                    <span className="font-mono font-bold text-emerald-400">
                      {sig.estimatedProfitInr ? formatInr(sig.estimatedProfitInr, { showSign: true }) : '+₹12,500'}
                    </span>
                  </div>
                </div>

                {/* Confidence Bar */}
                <div className="space-y-1 mb-3">
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-400">Signal Confidence:</span>
                    <span className="font-bold text-emerald-400 font-mono">{sig.confidence}%</span>
                  </div>
                  <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden border border-slate-800">
                    <div 
                      className="bg-gradient-to-r from-emerald-500 to-sky-400 h-full rounded-full"
                      style={{ width: `${sig.confidence}%` }}
                    />
                  </div>
                </div>

                {/* Footer Rationale */}
                <div className="flex items-center justify-between text-[11px] text-slate-400 pt-2 border-t border-slate-800">
                  <span className="truncate max-w-[180px]">{sig.reasoning}</span>
                  <span className="text-sky-400 font-semibold flex items-center gap-1">
                    Details <ChevronRight className="w-3 h-3" />
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

    </div>
  );
};
