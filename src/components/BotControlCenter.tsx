import React, { useState } from 'react';
import { 
  Send, 
  ShieldAlert, 
  Sliders, 
  HardDrive, 
  Key, 
  Check, 
  AlertCircle, 
  Save, 
  Zap,
  Globe,
  Trash2,
  Lock,
  Cpu
} from 'lucide-react';
import { RiskSettings, BotStatus } from '../types';

interface BotControlCenterProps {
  riskSettings: RiskSettings;
  status: BotStatus | null;
  onSaveRiskSettings: (settings: RiskSettings) => void;
  onTestTelegram: () => void;
  onTriggerGc: () => void;
  isGcing: boolean;
}

export const BotControlCenter: React.FC<BotControlCenterProps> = ({
  riskSettings,
  status,
  onSaveRiskSettings,
  onTestTelegram,
  onTriggerGc,
  isGcing
}) => {
  const [formData, setFormData] = useState<RiskSettings>(riskSettings);
  const [saved, setSaved] = useState(false);
  
  // Telegram form state
  const [botToken, setBotToken] = useState('7849204819:AAH93k...8f31kQ');
  const [chatId, setChatId] = useState('-100184920491');
  
  // Exchange pairs toggle
  const [pairs, setPairs] = useState([
    { symbol: 'BTC/USDT', enabled: true },
    { symbol: 'ETH/USDT', enabled: true },
    { symbol: 'SOL/USDT', enabled: true },
    { symbol: 'BNB/USDT', enabled: true },
    { symbol: 'XRP/USDT', enabled: true },
    { symbol: 'DOGE/USDT', enabled: true },
    { symbol: 'ADA/USDT', enabled: false },
    { symbol: 'AVAX/USDT', enabled: false }
  ]);

  const handlePairToggle = (symbol: string) => {
    setPairs(pairs.map(p => p.symbol === symbol ? { ...p, enabled: !p.enabled } : p));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSaveRiskSettings(formData);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  return (
    <div className="space-y-6">
      
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
          <Sliders className="w-5 h-5 text-indigo-400" />
          Bot Control & Telegram Integration
        </h2>
        <p className="text-xs text-slate-400 mt-0.5">
          Manage Telegram bot tokens, exchange pairs, risk parameters, and Render 512MB RAM optimizations
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        
        {/* Telegram Bot Setup Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-lg space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-lg">
                <Send className="w-4 h-4" />
              </div>
              <div>
                <h3 className="font-bold text-slate-100 text-sm">Telegram Dispatcher Setup</h3>
                <p className="text-xs text-slate-400">Configure Telegram Bot Token & Target Broadcast Channel ID</p>
              </div>
            </div>
            <button
              type="button"
              onClick={onTestTelegram}
              className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold rounded-lg shadow transition-all active:scale-95 flex items-center gap-1.5"
            >
              <Send className="w-3.5 h-3.5" />
              Send Test Message
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1 flex items-center gap-1">
                <Key className="w-3.5 h-3.5 text-indigo-400" />
                Telegram Bot Token (from @BotFather)
              </label>
              <input
                type="password"
                value={botToken}
                onChange={(e) => setBotToken(e.target.value)}
                placeholder="7849204819:AAH93k..."
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1 flex items-center gap-1">
                <Globe className="w-3.5 h-3.5 text-indigo-400" />
                Target Telegram Channel / Chat ID
              </label>
              <input
                type="text"
                value={chatId}
                onChange={(e) => setChatId(e.target.value)}
                placeholder="-100184920491"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <div className="flex items-center gap-2 pt-1 text-xs text-slate-400">
            <input
              type="checkbox"
              id="telegramNotif"
              checked={formData.telegramNotifications}
              onChange={(e) => setFormData({ ...formData, telegramNotifications: e.target.checked })}
              className="rounded bg-slate-950 border-slate-700 text-indigo-500 focus:ring-0"
            />
            <label htmlFor="telegramNotif" className="cursor-pointer text-slate-300">
              Auto-broadcast new high-confidence signals (&gt; 75%) to Telegram channel instantly
            </label>
          </div>
        </div>

        {/* Render 512MB RAM Optimization Settings */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-lg space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-lg">
                <HardDrive className="w-4 h-4" />
              </div>
              <div>
                <h3 className="font-bold text-slate-100 text-sm">Render Free Tier 512MB RAM Tuning</h3>
                <p className="text-xs text-slate-400">Controls for zero out-of-memory crash reliability on Render container</p>
              </div>
            </div>
            <button
              type="button"
              onClick={onTriggerGc}
              disabled={isGcing}
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition-all"
            >
              <Trash2 className="w-3.5 h-3.5 text-amber-400" />
              {isGcing ? 'Reclaiming RAM...' : 'Trigger GC Now'}
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 flex items-center justify-between">
              <div>
                <span className="font-bold text-xs text-slate-200 block">RAM Saver Mode</span>
                <span className="text-[11px] text-slate-400 block mt-0.5">
                  Limits log buffer to 100 rows &amp; trims cached tick data
                </span>
              </div>
              <input
                type="checkbox"
                checked={formData.ramSaverMode}
                onChange={(e) => setFormData({ ...formData, ramSaverMode: e.target.checked })}
                className="w-4 h-4 rounded bg-slate-900 border-slate-700 text-emerald-500 focus:ring-0"
              />
            </div>

            <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800">
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Auto Garbage Collection Interval (Minutes)
              </label>
              <select
                value={formData.autoGcIntervalMinutes}
                onChange={(e) => setFormData({ ...formData, autoGcIntervalMinutes: Number(e.target.value) })}
                className="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              >
                <option value={5}>Every 5 Minutes (Aggressive)</option>
                <option value={10}>Every 10 Minutes (Recommended for Render)</option>
                <option value={30}>Every 30 Minutes</option>
              </select>
            </div>
          </div>
        </div>

        {/* Risk Management & Circuit Breakers */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-lg space-y-4">
          <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
            <div className="p-2 bg-rose-500/10 text-rose-400 rounded-lg">
              <ShieldAlert className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-bold text-slate-100 text-sm">Risk Management &amp; Circuit Breakers</h3>
              <p className="text-xs text-slate-400">Automated capital preservation parameters</p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Max Drawdown Cap (%)
              </label>
              <input
                type="number"
                step="0.5"
                value={formData.maxDrawdownCap}
                onChange={(e) => setFormData({ ...formData, maxDrawdownCap: Number(e.target.value) })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 font-mono focus:outline-none focus:border-rose-500"
              />
              <span className="text-[10px] text-slate-500">Pauses bot if drawdown exceeds this limit</span>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Default Stop Loss (%)
              </label>
              <input
                type="number"
                step="0.1"
                value={formData.defaultStopLoss}
                onChange={(e) => setFormData({ ...formData, defaultStopLoss: Number(e.target.value) })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 font-mono focus:outline-none focus:border-rose-500"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Default Take Profit (%)
              </label>
              <input
                type="number"
                step="0.1"
                value={formData.defaultTakeProfit}
                onChange={(e) => setFormData({ ...formData, defaultTakeProfit: Number(e.target.value) })}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 font-mono focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>
        </div>

        {/* Monitored Exchange Pairs */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-lg space-y-3">
          <h3 className="font-bold text-slate-100 text-sm">Monitored Exchange Pairs</h3>
          <p className="text-xs text-slate-400">Toggle active trading pairs for strategy signal evaluation</p>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
            {pairs.map((p) => (
              <button
                key={p.symbol}
                type="button"
                onClick={() => handlePairToggle(p.symbol)}
                className={`p-2.5 rounded-xl border text-xs font-mono font-bold flex items-center justify-between transition-all ${
                  p.enabled
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                    : 'bg-slate-950 text-slate-500 border-slate-800'
                }`}
              >
                <span>{p.symbol}</span>
                <span className={`w-2 h-2 rounded-full ${p.enabled ? 'bg-emerald-400' : 'bg-slate-700'}`}></span>
              </button>
            ))}
          </div>
        </div>

        {/* Submit Bar */}
        <div className="flex items-center justify-end gap-3 pt-2">
          {saved && (
            <span className="text-xs text-emerald-400 font-semibold flex items-center gap-1">
              <Check className="w-4 h-4" /> Settings Saved!
            </span>
          )}
          <button
            type="submit"
            className="px-6 py-2.5 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-extrabold text-xs rounded-xl shadow-lg transition-all active:scale-95 flex items-center gap-2"
          >
            <Save className="w-4 h-4" />
            Save Bot Configuration
          </button>
        </div>

      </form>

    </div>
  );
};
