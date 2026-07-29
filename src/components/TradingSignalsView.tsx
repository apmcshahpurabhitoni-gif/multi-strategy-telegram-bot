import React, { useState } from 'react';
import { 
  Search, 
  Zap, 
  Send, 
  ChevronRight, 
  Plus
} from 'lucide-react';
import { TradingSignal } from '../types';
import { formatInr, formatInrPrice } from '../utils/formatters';

interface TradingSignalsViewProps {
  signals: TradingSignal[];
  onSelectSignal: (signal: TradingSignal) => void;
  onOpenCreateSignal: () => void;
  onSendTelegram: (signal: TradingSignal) => void;
}

export const TradingSignalsView: React.FC<TradingSignalsViewProps> = ({
  signals,
  onSelectSignal,
  onOpenCreateSignal,
  onSendTelegram
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [directionFilter, setDirectionFilter] = useState<'ALL' | 'BUY' | 'SELL'>('ALL');
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'ACTIVE' | 'TARGET_REACHED' | 'STOP_HIT'>('ALL');
  const [strategyFilter, setStrategyFilter] = useState<string>('ALL');

  // Filter signals
  const filteredSignals = signals.filter((sig) => {
    const matchesSearch = sig.symbol.toLowerCase().includes(searchTerm.toLowerCase()) ||
                          sig.strategy.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesDirection = directionFilter === 'ALL' || sig.direction === directionFilter;
    const matchesStatus = statusFilter === 'ALL' || sig.status === statusFilter;
    const matchesStrategy = strategyFilter === 'ALL' || sig.strategy === strategyFilter;

    return matchesSearch && matchesDirection && matchesStatus && matchesStrategy;
  });

  return (
    <div className="space-y-5">
      
      {/* Header & Controls */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Zap className="w-5 h-5 text-amber-400" />
            Trading Signals Feed (Rupees - INR ₹)
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Algorithmic buy & sell signals across all 4 exchange accounts
          </p>
        </div>

        <button
          onClick={onOpenCreateSignal}
          className="px-4 py-2 bg-sky-500 hover:bg-sky-400 text-white font-bold text-xs rounded-xl shadow-lg flex items-center gap-2 transition-all active:scale-95 self-start md:self-auto"
        >
          <Plus className="w-4 h-4" />
          Simulate / Broadcast Signal
        </button>
      </div>

      {/* Filter Bar */}
      <div className="bg-[#1e293b] border border-slate-800 rounded-2xl p-3.5 space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          
          {/* Search Box */}
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
            <input
              type="text"
              placeholder="Search symbol (e.g. BTC/INR)..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500"
            />
          </div>

          {/* Direction Filter */}
          <select
            value={directionFilter}
            onChange={(e: any) => setDirectionFilter(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
          >
            <option value="ALL">All Directions (BUY & SELL)</option>
            <option value="BUY">BUY / Long Only</option>
            <option value="SELL">SELL / Short Only</option>
          </select>

          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e: any) => setStatusFilter(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
          >
            <option value="ALL">All Statuses</option>
            <option value="ACTIVE">ACTIVE Signals</option>
            <option value="TARGET_REACHED">Target Reached</option>
            <option value="STOP_HIT">Stop Hit</option>
          </select>

          {/* Strategy Filter */}
          <select
            value={strategyFilter}
            onChange={(e) => setStrategyFilter(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
          >
            <option value="ALL">All Strategies</option>
            <option value="RSI_MACD_Confluence">Strategy 1: RSI + MACD Confluence</option>
            <option value="Volume_Profile_Spike">Strategy 2: Volume Spike Breakout</option>
            <option value="Bollinger_Breakout">Bollinger Squeeze</option>
            <option value="Grid_Scalper">Grid Scalper</option>
          </select>

        </div>
      </div>

      {/* Signals Grid View */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredSignals.map((sig) => {
          const isBuy = sig.direction === 'BUY';
          const priceDiff = sig.currentPrice - sig.entryPrice;
          const priceDiffPct = ((priceDiff / sig.entryPrice) * 100).toFixed(2);
          const isProfit = isBuy ? priceDiff >= 0 : priceDiff <= 0;

          return (
            <div
              key={sig.id}
              className="bg-[#1e293b] border border-slate-800 hover:border-slate-700 rounded-2xl p-4 space-y-3.5 transition-all hover:shadow-xl relative flex flex-col justify-between"
            >
              {/* Header */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-extrabold text-white text-lg font-mono">{sig.symbol}</span>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-slate-900 text-slate-300 font-mono border border-slate-800">
                      {sig.timeframe}
                    </span>
                  </div>
                  <span className={`px-2.5 py-1 rounded-lg text-xs font-black tracking-wider ${
                    isBuy ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
                  }`}>
                    {sig.direction}
                  </span>
                </div>

                <div className="text-xs text-slate-400 flex items-center gap-2 mb-3">
                  <span className="font-semibold text-sky-400">{sig.strategy.replace(/_/g, ' ')}</span>
                  <span>•</span>
                  <span className="font-mono text-[11px]">{new Date(sig.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                </div>

                {/* Price Matrix in INR */}
                <div className="grid grid-cols-2 gap-2 bg-slate-950 p-3 rounded-xl border border-slate-800/80 font-mono text-xs">
                  <div>
                    <span className="text-[11px] text-slate-500 block">Entry Price</span>
                    <span className="font-bold text-slate-200">{formatInrPrice(sig.entryPrice)}</span>
                  </div>
                  <div>
                    <span className="text-[11px] text-slate-500 block">Current</span>
                    <span className={`font-bold ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {formatInrPrice(sig.currentPrice)} <span className="text-[10px]">({priceDiffPct}%)</span>
                    </span>
                  </div>
                  <div>
                    <span className="text-[11px] text-slate-500 block">Target (TP2)</span>
                    <span className="font-bold text-emerald-400">{formatInrPrice(sig.targetPrice)}</span>
                  </div>
                  <div>
                    <span className="text-[11px] text-slate-500 block">Stop Loss</span>
                    <span className="font-bold text-rose-400">{formatInrPrice(sig.stopLoss)}</span>
                  </div>
                </div>

                {/* Indicators Pill Summary */}
                <div className="flex flex-wrap items-center gap-2 mt-3 text-[11px]">
                  <span className="bg-slate-900 text-slate-300 px-2 py-0.5 rounded border border-slate-800 font-mono">
                    RSI: <span className="text-emerald-400 font-bold">{sig.indicators.rsi}</span>
                  </span>
                  <span className="bg-slate-900 text-slate-300 px-2 py-0.5 rounded border border-slate-800 font-mono">
                    MACD: <span className="text-sky-400 font-bold">Bullish</span>
                  </span>
                  <span className="bg-slate-900 text-slate-300 px-2 py-0.5 rounded border border-slate-800 font-mono">
                    Est P&L: <span className="text-emerald-400 font-bold">{formatInr(sig.estimatedProfitInr || 12000)}</span>
                  </span>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="pt-3 border-t border-slate-800/80 flex items-center justify-between gap-2">
                <button
                  onClick={() => onSendTelegram(sig)}
                  className="px-3 py-1.5 bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 border border-sky-500/30 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all"
                  title="Send to Telegram Channel"
                >
                  <Send className="w-3.5 h-3.5" />
                  Alert Telegram
                </button>

                <button
                  onClick={() => onSelectSignal(sig)}
                  className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-slate-200 rounded-lg text-xs font-bold flex items-center gap-1 transition-all border border-slate-800"
                >
                  Inspect <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>

            </div>
          );
        })}
      </div>

      {filteredSignals.length === 0 && (
        <div className="bg-[#1e293b] border border-slate-800 rounded-2xl p-12 text-center text-slate-400">
          <Zap className="w-8 h-8 text-slate-600 mx-auto mb-2" />
          <p className="font-semibold text-slate-300">No trading signals match your search filter</p>
          <p className="text-xs text-slate-500 mt-1">Try resetting the search keywords or filters.</p>
        </div>
      )}

    </div>
  );
};
