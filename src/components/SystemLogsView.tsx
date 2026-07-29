import React, { useState } from 'react';
import { 
  Terminal, 
  Trash2, 
  Download, 
  Filter, 
  Check, 
  AlertCircle, 
  Send, 
  HardDrive, 
  Search,
  Zap,
  RefreshCw
} from 'lucide-react';
import { SystemLog, BotStatus } from '../types';

interface SystemLogsViewProps {
  logs: SystemLog[];
  status: BotStatus | null;
  onTriggerGc: () => void;
  isGcing: boolean;
}

export const SystemLogsView: React.FC<SystemLogsViewProps> = ({
  logs,
  status,
  onTriggerGc,
  isGcing
}) => {
  const [filterLevel, setFilterLevel] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredLogs = logs.filter((l) => {
    const matchesLevel = filterLevel === 'ALL' || l.level === filterLevel;
    const matchesQuery = l.message.toLowerCase().includes(searchQuery.toLowerCase()) ||
                         l.category.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesLevel && matchesQuery;
  });

  const handleExport = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(logs, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `telegram_bot_logs_${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  return (
    <div className="space-y-5">
      
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Terminal className="w-5 h-5 text-emerald-400" />
            RAM &amp; System Execution Logs
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Real-time memory watchdog alerts, strategy execution triggers, and Telegram dispatch logs
          </p>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <button
            onClick={onTriggerGc}
            disabled={isGcing}
            className="px-3 py-1.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 active:scale-95 disabled:opacity-50"
          >
            <Trash2 className={`w-3.5 h-3.5 ${isGcing ? 'animate-spin' : ''}`} />
            {isGcing ? 'Cleaning...' : 'Clear RAM (GC)'}
          </button>

          <button
            onClick={handleExport}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5"
          >
            <Download className="w-3.5 h-3.5" />
            Export Logs
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5 flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-72">
          <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
          <input
            type="text"
            placeholder="Search log messages..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
          />
        </div>

        <div className="flex items-center gap-1.5 overflow-x-auto w-full sm:w-auto no-scrollbar pb-1 sm:pb-0 text-xs">
          {['ALL', 'RAM_WATCHDOG', 'TELEGRAM', 'SIGNAL', 'INFO', 'WARN', 'ERROR'].map((lvl) => (
            <button
              key={lvl}
              onClick={() => setFilterLevel(lvl)}
              className={`px-2.5 py-1 rounded-md text-[11px] font-semibold font-mono transition-all whitespace-nowrap ${
                filterLevel === lvl
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                  : 'bg-slate-950 text-slate-400 hover:text-slate-200 border border-slate-800'
              }`}
            >
              {lvl.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      {/* Log Entries Terminal Window */}
      <div className="bg-slate-950 border border-slate-800 rounded-2xl p-4 font-mono text-xs shadow-2xl space-y-2 max-h-[550px] overflow-y-auto">
        {filteredLogs.map((log) => {
          let badgeColor = 'text-slate-400 bg-slate-900 border-slate-800';
          if (log.level === 'RAM_WATCHDOG') badgeColor = 'text-amber-400 bg-amber-500/10 border-amber-500/20';
          if (log.level === 'TELEGRAM') badgeColor = 'text-indigo-400 bg-indigo-500/10 border-indigo-500/20';
          if (log.level === 'SIGNAL') badgeColor = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
          if (log.level === 'ERROR') badgeColor = 'text-rose-400 bg-rose-500/10 border-rose-500/20';
          if (log.level === 'WARN') badgeColor = 'text-amber-400 bg-amber-500/10 border-amber-500/20';

          return (
            <div key={log.id} className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-900 hover:border-slate-800 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div className="flex items-start gap-2.5">
                <span className={`text-[10px] px-2 py-0.5 rounded font-bold border shrink-0 ${badgeColor}`}>
                  {log.level}
                </span>
                <div>
                  <span className="text-slate-500 text-[11px] mr-2">
                    [{new Date(log.timestamp).toLocaleTimeString()}]
                  </span>
                  <span className="text-slate-400 text-[11px] font-semibold mr-2 font-sans">
                    {log.category}:
                  </span>
                  <span className="text-slate-200">{log.message}</span>
                </div>
              </div>

              {log.memoryMb && (
                <span className="text-[10px] text-slate-500 font-mono shrink-0 text-right">
                  RAM: {log.memoryMb} MB
                </span>
              )}
            </div>
          );
        })}

        {filteredLogs.length === 0 && (
          <div className="text-center py-8 text-slate-500">
            No system log records found matching search filter.
          </div>
        )}
      </div>

    </div>
  );
};
