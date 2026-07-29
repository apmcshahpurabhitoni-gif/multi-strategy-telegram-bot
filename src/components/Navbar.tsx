import React from 'react';
import { 
  Bot, 
  Activity, 
  TrendingUp, 
  Send, 
  Sliders, 
  Terminal, 
  Play, 
  Pause, 
  PlusCircle, 
  HardDrive,
  RefreshCw,
  Wallet
} from 'lucide-react';
import { BotStatus } from '../types';
import { formatInr } from '../utils/formatters';

interface NavbarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  status: BotStatus | null;
  onToggleBot: () => void;
  onOpenCreateSignal: () => void;
  onRefreshData: () => void;
  isRefreshing: boolean;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  status,
  onToggleBot,
  onOpenCreateSignal,
  onRefreshData,
  isRefreshing
}) => {
  const isRunning = status?.isRunning ?? true;

  const navItems = [
    { id: 'overview', label: 'Overview & 4 Accounts', icon: Activity },
    { id: 'signals', label: 'Live Signals Feed', icon: TrendingUp },
    { id: 'performance', label: '2 Core Strategies', icon: Bot },
  ];

  return (
    <header className="bg-[#0f172a] border-b border-slate-800 sticky top-0 z-40 shadow-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 gap-4">
          
          {/* Logo & Status */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-sky-500 p-0.5 shadow-lg shadow-sky-500/20 flex items-center justify-center">
              <Bot className="w-6 h-6 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-extrabold text-white text-base sm:text-lg tracking-tight">
                  QuantBot
                </h1>
                <span className="text-[10px] uppercase tracking-widest text-sky-400 font-semibold bg-sky-500/10 px-1.5 py-0.5 rounded border border-sky-500/20">
                  v2.4 Pro
                </span>
                <span className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${
                  isRunning 
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' 
                    : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${isRunning ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`}></span>
                  {isRunning ? 'ACTIVE' : 'PAUSED'}
                </span>
              </div>
              <p className="text-[11px] text-slate-400 hidden sm:block">
                4 Accounts • 2 Core Strategies • Indian Rupee (INR)
              </p>
            </div>
          </div>

          {/* Quick Metrics Bar on Desktop (INR Balance) */}
          <div className="hidden lg:flex items-center gap-4 bg-[#1e293b] px-3.5 py-1.5 rounded-xl border border-slate-800 text-xs">
            {status?.totalBalanceInr && (
              <div className="flex items-center gap-1.5 border-r border-slate-700 pr-3">
                <Wallet className="w-3.5 h-3.5 text-sky-400" />
                <span className="text-slate-400">Total Portfolio:</span>
                <span className="font-mono font-extrabold text-emerald-400 text-sm">
                  {formatInr(status.totalBalanceInr, { compact: true })}
                </span>
              </div>
            )}
            <div className="flex items-center gap-1.5">
              <Send className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-slate-400">Signal Alerts:</span>
              <span className="font-mono text-emerald-400 font-semibold">Live Channel Connected</span>
            </div>
          </div>

          {/* Right Action Buttons */}
          <div className="flex items-center gap-2">
            <button
              onClick={onRefreshData}
              disabled={isRefreshing}
              className="p-2 text-slate-400 hover:text-slate-200 bg-slate-800/80 hover:bg-slate-800 rounded-lg border border-slate-700/80 transition-all active:scale-95 disabled:opacity-50"
              title="Refresh Real-time Metrics"
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin text-sky-400' : ''}`} />
            </button>

            <button
              onClick={onOpenCreateSignal}
              className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 bg-sky-500 hover:bg-sky-400 text-white font-semibold text-xs rounded-lg shadow-lg shadow-sky-500/20 transition-all active:scale-95"
            >
              <PlusCircle className="w-3.5 h-3.5" />
              Simulate Signal
            </button>

            <button
              onClick={onToggleBot}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 border shadow-sm ${
                isRunning
                  ? 'bg-rose-500/10 text-rose-400 border-rose-500/30 hover:bg-rose-500/20'
                  : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20'
              }`}
            >
              {isRunning ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
              {isRunning ? 'Pause Bot' : 'Resume Bot'}
            </button>
          </div>
        </div>

        {/* Navigation Tabs (Scrollable on Mobile) */}
        <nav className="flex space-x-1 overflow-x-auto no-scrollbar py-2 border-t border-slate-800/80">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition-all ${
                  isActive
                    ? 'bg-slate-700/60 text-white border border-slate-600 shadow-sm'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40 border border-transparent'
                }`}
              >
                <Icon className={`w-4 h-4 ${isActive ? 'text-sky-400' : 'text-slate-500'}`} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
};
