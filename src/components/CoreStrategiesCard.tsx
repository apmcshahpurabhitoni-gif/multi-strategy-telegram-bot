import React from 'react';
import { Sliders, Award, Zap, TrendingUp, CheckCircle2, Play, Pause, AlertTriangle } from 'lucide-react';
import { StrategyMetrics } from '../types';
import { formatInr } from '../utils/formatters';

interface CoreStrategiesCardProps {
  strategies: StrategyMetrics[];
  onToggleStrategy: (strategyId: string) => void;
  onNavigateTab?: (tab: string) => void;
}

export const CoreStrategiesCard: React.FC<CoreStrategiesCardProps> = ({
  strategies,
  onToggleStrategy,
  onNavigateTab
}) => {
  // Filter core strategies
  const coreStrategies = strategies.filter(s => s.isCoreStrategy || s.name === 'RSI_MACD_Confluence' || s.name === 'Volume_Profile_Spike');

  return (
    <div className="bg-[#1e293b] border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/20 text-emerald-400 flex items-center justify-center font-bold">
              <Zap className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                2 Core Running Trading Strategies
                <span className="text-[10px] bg-emerald-500/10 text-emerald-400 px-2 py-0.5 rounded border border-emerald-500/20 font-mono">
                  LIVE AUTOMATED
                </span>
              </h2>
              <p className="text-xs text-slate-400">
                Detailed side-by-side comparison of win rates, live profits in Rupees, and profit factors
              </p>
            </div>
          </div>
        </div>

        {onNavigateTab && (
          <button
            onClick={() => onNavigateTab('performance')}
            className="text-xs text-sky-400 hover:text-sky-300 font-semibold flex items-center gap-1 hover:underline"
          >
            All Strategy Analytics →
          </button>
        )}
      </div>

      {/* Side-by-Side 2 Core Strategies Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {coreStrategies.map((strat, idx) => {
          const isRunning = strat.status === 'RUNNING';
          const winRateColor = strat.winRate >= 70 ? 'text-emerald-400' : 'text-sky-400';

          return (
            <div
              key={strat.id}
              className="bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-xl p-4 flex flex-col justify-between space-y-4 relative overflow-hidden group shadow-md"
            >
              {/* Subtle gradient background accent */}
              <div className={`absolute top-0 right-0 w-32 h-32 rounded-full blur-2xl opacity-10 ${
                idx === 0 ? 'bg-sky-500' : 'bg-emerald-500'
              }`} />

              <div>
                {/* Top Badge & Status */}
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] font-black uppercase tracking-widest px-2 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20">
                    CORE STRATEGY #{idx + 1}
                  </span>

                  <button
                    onClick={() => onToggleStrategy(strat.id)}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-bold transition-all flex items-center gap-1.5 border ${
                      isRunning
                        ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20'
                        : 'bg-amber-500/10 text-amber-400 border-amber-500/30 hover:bg-amber-500/20'
                    }`}
                  >
                    {isRunning ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
                    {isRunning ? 'RUNNING' : 'PAUSED'}
                  </button>
                </div>

                {/* Title & Description */}
                <h3 className="text-base font-extrabold text-white mb-1">
                  {strat.displayName}
                </h3>
                <p className="text-xs text-slate-400 line-clamp-2 mb-4">
                  {strat.description}
                </p>

                {/* Key Metrics Matrix (Win Rate & Live Net Profit in ₹) */}
                <div className="grid grid-cols-2 gap-3 bg-slate-950/80 p-3 rounded-xl border border-slate-800 mb-3">
                  <div>
                    <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider block mb-0.5">
                      Live Win Rate
                    </span>
                    <div className="flex items-baseline gap-1">
                      <span className={`text-xl font-black font-mono ${winRateColor}`}>
                        {strat.winRate}%
                      </span>
                      <span className="text-[10px] text-slate-400">
                        ({strat.profitTrades}W / {strat.lossTrades}L)
                      </span>
                    </div>
                  </div>

                  <div>
                    <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider block mb-0.5">
                      Net Live Profit
                    </span>
                    <span className="text-xl font-black font-mono text-emerald-400">
                      {formatInr(strat.netProfitInr, { showSign: true })}
                    </span>
                  </div>
                </div>

                {/* Secondary Stats */}
                <div className="grid grid-cols-3 gap-2 text-xs border-t border-slate-800/80 pt-3">
                  <div>
                    <span className="text-[10px] text-slate-500 block">Total Trades:</span>
                    <span className="font-mono font-bold text-slate-200">{strat.totalTrades}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 block">Profit Factor:</span>
                    <span className="font-mono font-bold text-slate-200">{strat.profitFactor}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 block">Max Drawdown:</span>
                    <span className="font-mono font-bold text-rose-400">-{strat.maxDrawdown}%</span>
                  </div>
                </div>
              </div>

              {/* Active Pairs Footer */}
              <div className="flex items-center justify-between text-[11px] pt-3 border-t border-slate-800/80 text-slate-400">
                <span>Active Pairs:</span>
                <div className="flex items-center gap-1">
                  {strat.activePairs.map((pair) => (
                    <span key={pair} className="bg-slate-800 px-2 py-0.5 rounded font-mono text-[10px] font-bold text-slate-300">
                      {pair}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
