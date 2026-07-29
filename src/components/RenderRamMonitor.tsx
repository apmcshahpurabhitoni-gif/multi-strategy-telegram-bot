import React from 'react';
import { Cpu, HardDrive, Zap, ShieldCheck, AlertTriangle, Trash2, CheckCircle2 } from 'lucide-react';
import { BotStatus } from '../types';

interface RenderRamMonitorProps {
  status: BotStatus | null;
  onTriggerGc: () => void;
  isGcing: boolean;
  onToggleRamSaver: () => void;
}

export const RenderRamMonitor: React.FC<RenderRamMonitorProps> = ({
  status,
  onTriggerGc,
  isGcing,
  onToggleRamSaver
}) => {
  if (!status) return null;

  const { currentRamMb, maxRamMb, ramUsagePercent, renderFreeTierHealth, cpuUsagePercent, ramSaverMode } = status;

  // Determine color status for RAM bar
  let healthBadgeColor = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
  let barColor = 'bg-emerald-500';
  let healthText = 'OPTIMAL (Render 512MB Safe)';

  if (renderFreeTierHealth === 'CRITICAL_LEAK' || ramUsagePercent > 85) {
    healthBadgeColor = 'bg-rose-500/10 text-rose-400 border-rose-500/20 animate-pulse';
    barColor = 'bg-rose-500';
    healthText = 'CRITICAL: RAM > 85% (Render OOM Risk)';
  } else if (renderFreeTierHealth === 'HIGH_MEM_WARNING' || ramUsagePercent > 70) {
    healthBadgeColor = 'bg-amber-500/10 text-amber-400 border-amber-500/20';
    barColor = 'bg-amber-500';
    healthText = 'HIGH RAM: > 70% Usage';
  } else if (renderFreeTierHealth === 'MODERATE_MEM' || ramUsagePercent > 50) {
    healthBadgeColor = 'bg-sky-500/10 text-sky-400 border-sky-500/20';
    barColor = 'bg-sky-500';
    healthText = 'MODERATE MEMORY (~40-60%)';
  }

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 sm:p-5 backdrop-blur-md shadow-lg">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-slate-800 rounded-lg text-emerald-400 border border-slate-700/50">
            <HardDrive className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-bold text-slate-100 text-sm sm:text-base">Render Free Tier RAM Watchdog</h3>
              <span className={`text-xs px-2.5 py-0.5 rounded-full border font-medium ${healthBadgeColor}`}>
                {healthText}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Container Limit: <span className="font-semibold text-slate-200">512 MB RAM</span> • Single-process Node instance
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={onToggleRamSaver}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all flex items-center gap-1.5 ${
              ramSaverMode
                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
                : 'bg-slate-800 text-slate-400 border-slate-700 hover:text-slate-200'
            }`}
            title="Trimming log buffers & lowering chart polling rate"
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            RAM Saver: {ramSaverMode ? 'ON' : 'OFF'}
          </button>

          <button
            onClick={onTriggerGc}
            disabled={isGcing}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 active:scale-95 disabled:opacity-50"
            title="Invoke manual Garbage Collector & release stale heap memory"
          >
            <Trash2 className={`w-3.5 h-3.5 text-amber-400 ${isGcing ? 'animate-spin' : ''}`} />
            {isGcing ? 'Reclaiming...' : 'Free RAM (GC)'}
          </button>
        </div>
      </div>

      {/* Progress Bars & Memory Gauges */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 bg-slate-950/60 p-3.5 rounded-lg border border-slate-800/80">
        {/* RAM Usage Gauge */}
        <div className="md:col-span-2 space-y-2">
          <div className="flex justify-between text-xs">
            <span className="text-slate-400 font-medium flex items-center gap-1">
              <Zap className="w-3.5 h-3.5 text-emerald-400" /> Allocated Memory Footprint
            </span>
            <span className="font-mono font-bold text-slate-200">
              {currentRamMb} MB <span className="text-slate-500">/ {maxRamMb} MB</span> ({ramUsagePercent}%)
            </span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-3 overflow-hidden p-0.5 border border-slate-700/50">
            <div
              className={`h-full rounded-full transition-all duration-500 ${barColor}`}
              style={{ width: `${Math.min(100, ramUsagePercent)}%` }}
            />
          </div>
          <div className="flex justify-between text-[11px] text-slate-500 font-mono">
            <span>0 MB (Idle)</span>
            <span className="text-emerald-400/80">300 MB (Ideal)</span>
            <span className="text-amber-400/80">420 MB (Threshold)</span>
            <span className="text-rose-400/80">512 MB (Max OOM)</span>
          </div>
        </div>

        {/* CPU & Optimization Stats */}
        <div className="space-y-1.5 border-t md:border-t-0 md:border-l border-slate-800 pt-2 md:pt-0 md:pl-4 text-xs">
          <div className="flex justify-between items-center">
            <span className="text-slate-400 flex items-center gap-1">
              <Cpu className="w-3.5 h-3.5 text-sky-400" /> CPU Allocation:
            </span>
            <span className="font-mono font-semibold text-slate-200">{cpuUsagePercent}%</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-slate-400 flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Heap Isolation:
            </span>
            <span className="font-mono text-emerald-400 font-semibold">Active</span>
          </div>
          <div className="flex justify-between items-center text-[11px] text-slate-500">
            <span>Render Log Buffer:</span>
            <span className="font-mono">Trimmed (Max 100)</span>
          </div>
        </div>
      </div>

      {/* Render Free Tier Optimization Highlights */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          Stateless JSON API responses
        </span>
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          Auto-purging stale signal cache
        </span>
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          Zero heavy SQLite/Postgres runtime overhead
        </span>
      </div>
    </div>
  );
};
