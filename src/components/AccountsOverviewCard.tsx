import React from 'react';
import { Wallet, ShieldCheck, Activity, Key, CheckCircle, TrendingUp, Layers } from 'lucide-react';
import { TradingAccount } from '../types';
import { formatInr } from '../utils/formatters';

interface AccountsOverviewCardProps {
  accounts: TradingAccount[];
  selectedAccountId: string | null;
  onSelectAccount: (accountId: string | null) => void;
}

export const AccountsOverviewCard: React.FC<AccountsOverviewCardProps> = ({
  accounts,
  selectedAccountId,
  onSelectAccount,
}) => {
  const totalBalanceInr = accounts.reduce((acc, a) => acc + a.balanceInr, 0);
  const totalLivePnlInr = accounts.reduce((acc, a) => acc + a.unrealizedPnlInr, 0);
  const totalActivePositions = accounts.reduce((acc, a) => acc + a.activePositionsCount, 0);

  return (
    <div className="bg-[#1e293b] border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-sky-500/20 text-sky-400 flex items-center justify-center font-bold">
              <Wallet className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                4 Active Exchange Accounts
                <span className="text-[10px] bg-sky-500/10 text-sky-400 px-2 py-0.5 rounded border border-sky-500/20 font-mono">
                  ALL INR PAIRS
                </span>
              </h2>
              <p className="text-xs text-slate-400">
                Live multi-account balance monitoring and strategy execution engine
              </p>
            </div>
          </div>
        </div>

        {/* Aggregated Totals */}
        <div className="flex items-center gap-4 bg-slate-900/80 px-4 py-2 rounded-xl border border-slate-800/80">
          <div>
            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider block">Total Portfolio Balance</span>
            <span className="text-sm sm:text-base font-extrabold font-mono text-emerald-400">
              {formatInr(totalBalanceInr)}
            </span>
          </div>
          <div className="h-6 w-px bg-slate-800" />
          <div>
            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider block">Live Open P&L</span>
            <span className="text-xs sm:text-sm font-bold font-mono text-emerald-400 flex items-center gap-1">
              <TrendingUp className="w-3.5 h-3.5" />
              {formatInr(totalLivePnlInr, { showSign: true })}
            </span>
          </div>
        </div>
      </div>

      {/* Account Switcher Bar */}
      <div className="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1">
        <button
          onClick={() => onSelectAccount(null)}
          className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all whitespace-nowrap flex items-center gap-1.5 border ${
            selectedAccountId === null
              ? 'bg-sky-500 text-white border-sky-400 shadow-md shadow-sky-500/20'
              : 'bg-slate-900/60 text-slate-400 hover:text-white border-slate-800 hover:bg-slate-800'
          }`}
        >
          <Layers className="w-3.5 h-3.5" />
          All 4 Accounts Combined ({accounts.length})
        </button>

        {accounts.map((acc) => {
          const isSelected = selectedAccountId === acc.id;
          return (
            <button
              key={acc.id}
              onClick={() => onSelectAccount(acc.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all whitespace-nowrap flex items-center gap-1.5 border ${
                isSelected
                  ? 'bg-sky-500 text-white border-sky-400 shadow-md shadow-sky-500/20'
                  : 'bg-slate-900/60 text-slate-400 hover:text-white border-slate-800 hover:bg-slate-800'
              }`}
            >
              <span className={`w-2 h-2 rounded-full ${acc.accountType === 'PAPER' ? 'bg-amber-400' : 'bg-emerald-400'}`} />
              {acc.name.split('-')[0].trim()}
              <span className="font-mono text-[11px] opacity-90">({formatInr(acc.balanceInr, { compact: true })})</span>
            </button>
          );
        })}
      </div>

      {/* 4 Accounts Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {accounts.map((acc) => {
          const isSelected = selectedAccountId === acc.id;
          return (
            <div
              key={acc.id}
              onClick={() => onSelectAccount(acc.id)}
              className={`rounded-xl p-4 transition-all cursor-pointer border relative flex flex-col justify-between ${
                isSelected
                  ? 'bg-slate-900 border-sky-500 shadow-lg shadow-sky-500/10 ring-1 ring-sky-500/50'
                  : 'bg-slate-900/70 border-slate-800 hover:border-slate-700 hover:bg-slate-900'
              }`}
            >
              <div>
                {/* Account Header */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-1.5">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase tracking-wider ${
                      acc.accountType === 'PAPER'
                        ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                        : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    }`}>
                      {acc.accountType}
                    </span>
                    <span className="text-[11px] text-slate-500 font-mono">{acc.accountNumber}</span>
                  </div>
                  <div className="flex items-center gap-1 text-[10px] text-emerald-400 font-semibold bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20">
                    <CheckCircle className="w-3 h-3" /> API OK
                  </div>
                </div>

                {/* Account Title */}
                <h3 className="font-bold text-sm text-slate-100 truncate mb-1" title={acc.name}>
                  {acc.name}
                </h3>
                <p className="text-[11px] text-slate-400 truncate mb-3">
                  Exchange: <span className="text-slate-200 font-medium">{acc.exchange}</span>
                </p>

                {/* Balance & Live Profit */}
                <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800/80 space-y-1.5 mb-3">
                  <div className="flex justify-between items-baseline">
                    <span className="text-[11px] text-slate-400">Balance:</span>
                    <span className="text-sm font-extrabold font-mono text-slate-100">
                      {formatInr(acc.balanceInr)}
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-xs">
                    <span className="text-[11px] text-slate-400">Live P&L:</span>
                    <span className="font-mono font-bold text-emerald-400">
                      {formatInr(acc.unrealizedPnlInr, { showSign: true })}
                    </span>
                  </div>
                </div>
              </div>

              {/* Footer info */}
              <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400">
                <span className="flex items-center gap-1 text-slate-300">
                  <Activity className="w-3 h-3 text-sky-400" />
                  {acc.activePositionsCount} Active Pos
                </span>
                <span className="font-mono text-emerald-400 font-semibold">
                  Win {acc.dailyWinRate}%
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
