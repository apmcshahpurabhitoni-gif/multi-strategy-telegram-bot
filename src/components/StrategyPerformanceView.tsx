import React from 'react';
import { 
  Bot, 
  TrendingUp, 
  Award, 
  Play, 
  Pause, 
  Sliders, 
  Zap,
  CheckCircle2
} from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell } from 'recharts';
import { StrategyMetrics } from '../types';
import { formatInr } from '../utils/formatters';

interface StrategyPerformanceViewProps {
  strategies: StrategyMetrics[];
  onToggleStrategy: (strategyId: string) => void;
}

export const StrategyPerformanceView: React.FC<StrategyPerformanceViewProps> = ({
  strategies,
  onToggleStrategy
}) => {
  const chartColors = ['#10b981', '#38bdf8', '#818cf8', '#f59e0b', '#ec4899'];

  return (
    <div className="space-y-6">
      
      {/* Page Header */}
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <Bot className="w-5 h-5 text-sky-400" />
          Algorithmic Strategy Analytics & 2 Core Engines
        </h2>
        <p className="text-xs text-slate-400 mt-0.5">
          Comparative live performance metrics, Indian Rupee net profit, and win rates
        </p>
      </div>

      {/* 2 Core Strategies Spotlight */}
      <div className="bg-[#1e293b] border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
        <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
          <Zap className="w-5 h-5 text-emerald-400" />
          <h3 className="text-base font-bold text-white">Your 2 Core Live Strategies</h3>
          <span className="text-[10px] bg-emerald-500/10 text-emerald-400 px-2 py-0.5 rounded border border-emerald-500/20 font-mono">
            74.2% & 68.8% WIN RATES
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {strategies.filter(s => s.isCoreStrategy || s.name === 'RSI_MACD_Confluence' || s.name === 'Volume_Profile_Spike').map((strat, idx) => (
            <div key={strat.id} className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-[10px] font-black uppercase text-sky-400 bg-sky-500/10 px-2 py-0.5 rounded border border-sky-500/20">
                  CORE STRATEGY #{idx + 1}
                </span>
                <span className="text-xs font-mono text-emerald-400 font-bold flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5" /> ACTIVE
                </span>
              </div>
              <h4 className="text-base font-extrabold text-white">{strat.displayName}</h4>
              <p className="text-xs text-slate-400">{strat.description}</p>
              
              <div className="grid grid-cols-2 gap-3 bg-slate-950 p-3 rounded-lg border border-slate-800 text-xs">
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase font-bold">Win Rate</span>
                  <span className="text-lg font-black font-mono text-emerald-400">{strat.winRate}%</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase font-bold">Live Net Profit (INR)</span>
                  <span className="text-lg font-black font-mono text-emerald-400">{formatInr(strat.netProfitInr, { showSign: true })}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Visual Bar Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        
        {/* Net Profit Bar Chart (INR) */}
        <div className="bg-[#1e293b] border border-slate-800 rounded-2xl p-5 shadow-xl">
          <h3 className="text-sm font-bold text-white mb-1 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-emerald-400" />
            Net Profit Contribution (Rupees - INR ₹)
          </h3>
          <p className="text-xs text-slate-400 mb-4">Total net profit generated per strategy in Indian Rupees</p>

          <div className="h-60 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={strategies} margin={{ top: 10, right: 10, left: 10, bottom: 25 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis 
                  dataKey="displayName" 
                  stroke="#94a3b8" 
                  fontSize={10} 
                  tickLine={false} 
                  interval={0}
                  angle={-15}
                  textAnchor="end"
                />
                <YAxis 
                  stroke="#94a3b8" 
                  fontSize={11} 
                  tickLine={false} 
                  tickFormatter={(val) => `₹${(val / 1000).toFixed(0)}k`}
                />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '12px', color: '#f8fafc', fontSize: '12px' }}
                  formatter={(value: any) => [formatInr(Number(value)), 'Net Profit']}
                />
                <Bar dataKey="netProfitInr" radius={[6, 6, 0, 0]}>
                  {strategies.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={chartColors[index % chartColors.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Win Rate Bar Chart */}
        <div className="bg-[#1e293b] border border-slate-800 rounded-2xl p-5 shadow-xl">
          <h3 className="text-sm font-bold text-white mb-1 flex items-center gap-2">
            <Award className="w-4 h-4 text-sky-400" />
            Strategy Win Rate Comparison (%)
          </h3>
          <p className="text-xs text-slate-400 mb-4">Percentage of winning trades per algorithm</p>

          <div className="h-60 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={strategies} margin={{ top: 10, right: 10, left: -20, bottom: 25 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis 
                  dataKey="displayName" 
                  stroke="#94a3b8" 
                  fontSize={10} 
                  tickLine={false} 
                  interval={0}
                  angle={-15}
                  textAnchor="end"
                />
                <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} domain={[0, 100]} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '12px', color: '#f8fafc', fontSize: '12px' }}
                  formatter={(value: any) => [`${value}%`, 'Win Rate']}
                />
                <Bar dataKey="winRate" fill="#38bdf8" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

      </div>

      {/* Comprehensive Strategy Table */}
      <div className="bg-[#1e293b] border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <Sliders className="w-4 h-4 text-emerald-400" />
            Detailed Strategy Performance Matrix
          </h3>
          <span className="text-xs text-slate-400">
            {strategies.filter(s => s.status === 'RUNNING').length} / {strategies.length} Active
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-sans">
            <thead className="bg-slate-900 text-slate-400 uppercase font-mono text-[11px] border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">Strategy Name</th>
                <th className="py-3 px-4">Net Profit (INR ₹)</th>
                <th className="py-3 px-4">Win Rate %</th>
                <th className="py-3 px-4">Profit Factor</th>
                <th className="py-3 px-4">Max Drawdown</th>
                <th className="py-3 px-4">Sharpe Ratio</th>
                <th className="py-3 px-4">Total Trades</th>
                <th className="py-3 px-4 text-right">Status / Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80 text-slate-200">
              {strategies.map((strat) => {
                const isRunning = strat.status === 'RUNNING';
                return (
                  <tr key={strat.id} className="hover:bg-slate-900/60 transition-colors">
                    <td className="py-3.5 px-4">
                      <div className="font-bold text-white text-sm flex items-center gap-2">
                        {strat.displayName}
                        {strat.isCoreStrategy && (
                          <span className="text-[10px] bg-sky-500/10 text-sky-400 border border-sky-500/20 px-1.5 py-0.2 rounded font-mono">
                            CORE
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-400 max-w-xs line-clamp-1">{strat.description}</div>
                      <div className="flex gap-1 mt-1">
                        {strat.activePairs.map((pair) => (
                          <span key={pair} className="text-[10px] px-1.5 py-0.2 bg-slate-900 text-slate-300 rounded font-mono border border-slate-800">
                            {pair}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="py-3.5 px-4 font-mono font-bold text-emerald-400 text-sm">
                      {formatInr(strat.netProfitInr, { showSign: true })}
                    </td>
                    <td className="py-3.5 px-4 font-mono">
                      <span className="font-bold text-slate-100">{strat.winRate}%</span>
                      <span className="text-[10px] text-slate-500 block">({strat.profitTrades}W / {strat.lossTrades}L)</span>
                    </td>
                    <td className="py-3.5 px-4 font-mono font-semibold text-slate-200">
                      {strat.profitFactor}
                    </td>
                    <td className="py-3.5 px-4 font-mono text-rose-400 font-semibold">
                      -{strat.maxDrawdown}%
                    </td>
                    <td className="py-3.5 px-4 font-mono font-semibold text-sky-400">
                      {strat.sharpeRatio}
                    </td>
                    <td className="py-3.5 px-4 font-mono text-slate-300">
                      {strat.totalTrades}
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <button
                        onClick={() => onToggleStrategy(strat.id)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all inline-flex items-center gap-1 border ${
                          isRunning
                            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20'
                            : 'bg-slate-800 text-slate-400 border-slate-700 hover:bg-slate-700'
                        }`}
                      >
                        {isRunning ? <Play className="w-3 h-3 text-emerald-400" /> : <Pause className="w-3 h-3 text-slate-400" />}
                        {isRunning ? 'RUNNING' : 'PAUSED'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
};
