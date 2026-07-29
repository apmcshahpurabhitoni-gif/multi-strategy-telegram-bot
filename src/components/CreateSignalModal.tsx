import React, { useState } from 'react';
import { X, Send, Zap } from 'lucide-react';
import { TradingSignal, SignalDirection, StrategyType, TimeFrame } from '../types';

interface CreateSignalModalProps {
  onClose: () => void;
  onSubmitSignal: (signal: Partial<TradingSignal>) => void;
}

export const CreateSignalModal: React.FC<CreateSignalModalProps> = ({
  onClose,
  onSubmitSignal
}) => {
  const [symbol, setSymbol] = useState('BTC/INR');
  const [direction, setDirection] = useState<SignalDirection>('BUY');
  const [strategy, setStrategy] = useState<StrategyType>('RSI_MACD_Confluence');
  const [accountId, setAccountId] = useState<string>('acc-1');
  const [timeframe, setTimeframe] = useState<TimeFrame>('15m');
  const [entryPrice, setEntryPrice] = useState(5842100);
  const [targetPrice, setTargetPrice] = useState(6150000);
  const [stopLoss, setStopLoss] = useState(5710000);
  const [confidence, setConfidence] = useState(94);
  const [estimatedProfitInr, setEstimatedProfitInr] = useState(18200);
  const [reasoning, setReasoning] = useState('RSI bullish divergence on 15m confluence with MACD histogram crossover and 2.15x volume surge in INR pair.');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmitSignal({
      symbol,
      direction,
      strategy,
      accountId,
      timeframe,
      entryPrice: Number(entryPrice),
      currentPrice: Number(entryPrice),
      targetPrice: Number(targetPrice),
      stopLoss: Number(stopLoss),
      takeProfit1: Number(entryPrice) + (Number(targetPrice) - Number(entryPrice)) * 0.5,
      takeProfit2: Number(targetPrice),
      confidence: Number(confidence),
      estimatedProfitInr: Number(estimatedProfitInr),
      reasoning,
      riskRewardRatio: 2.85
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div className="bg-[#1e293b] border border-slate-800 rounded-2xl max-w-lg w-full p-5 space-y-4 shadow-2xl">
        
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-sky-400" />
            <h3 className="font-bold text-white text-base">Simulate Trading Signal (Rupees - INR)</h3>
          </div>
          <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-white bg-slate-900 rounded-lg border border-slate-800">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-slate-300 font-semibold mb-1">Target Account (1 of 4)</label>
              <select
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 rounded-xl p-2 text-slate-200 font-mono focus:outline-none focus:border-sky-500"
              >
                <option value="acc-1">Account 1 - WazirX / Binance IN</option>
                <option value="acc-2">Account 2 - Delta Exchange</option>
                <option value="acc-3">Account 3 - Telegram Auto Dispatcher</option>
                <option value="acc-4">Account 4 - Paper Trading Sandbox</option>
              </select>
            </div>

            <div>
              <label className="block text-slate-300 font-semibold mb-1">Trading Pair (INR)</label>
              <select
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 rounded-xl p-2 text-slate-200 font-mono focus:outline-none focus:border-sky-500"
              >
                <option value="BTC/INR">BTC/INR</option>
                <option value="ETH/INR">ETH/INR</option>
                <option value="SOL/INR">SOL/INR</option>
                <option value="BNB/INR">BNB/INR</option>
                <option value="XRP/INR">XRP/INR</option>
                <option value="DOGE/INR">DOGE/INR</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-slate-300 font-semibold mb-1">Direction & Strategy</label>
              <div className="grid grid-cols-2 gap-2">
                <select
                  value={direction}
                  onChange={(e: any) => setDirection(e.target.value)}
                  className="bg-slate-900 border border-slate-800 rounded-xl p-2 text-slate-200 font-bold focus:outline-none focus:border-sky-500"
                >
                  <option value="BUY">BUY 🟢</option>
                  <option value="SELL">SELL 🔴</option>
                </select>

                <select
                  value={timeframe}
                  onChange={(e: any) => setTimeframe(e.target.value)}
                  className="bg-slate-900 border border-slate-800 rounded-xl p-2 text-slate-200 font-mono focus:outline-none focus:border-sky-500"
                >
                  <option value="5m">5m</option>
                  <option value="15m">15m</option>
                  <option value="1h">1h</option>
                  <option value="4h">4h</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-slate-300 font-semibold mb-1">Core Strategy</label>
              <select
                value={strategy}
                onChange={(e: any) => setStrategy(e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 rounded-xl p-2 text-slate-200 focus:outline-none focus:border-sky-500"
              >
                <option value="RSI_MACD_Confluence">Strategy 1: RSI + MACD Confluence</option>
                <option value="Volume_Profile_Spike">Strategy 2: Volume Spike Breakout</option>
                <option value="Bollinger_Breakout">Bollinger Squeeze</option>
                <option value="Grid_Scalper">Grid Scalper</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-slate-300 font-semibold mb-1">Entry Price (₹)</label>
              <input
                type="number"
                value={entryPrice}
                onChange={(e) => setEntryPrice(Number(e.target.value))}
                className="w-full bg-slate-900 border border-slate-800 rounded-xl p-2 text-slate-200 font-mono focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="block text-slate-300 font-semibold mb-1">Target Price (₹)</label>
              <input
                type="number"
                value={targetPrice}
                onChange={(e) => setTargetPrice(Number(e.target.value))}
                className="w-full bg-slate-900 border border-slate-800 rounded-xl p-2 text-emerald-400 font-mono focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="block text-slate-300 font-semibold mb-1">Stop Loss (₹)</label>
              <input
                type="number"
                value={stopLoss}
                onChange={(e) => setStopLoss(Number(e.target.value))}
                className="w-full bg-slate-900 border border-slate-800 rounded-xl p-2 text-rose-400 font-mono focus:outline-none focus:border-rose-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-slate-300 font-semibold mb-1">Signal Rationale / Indicators</label>
            <textarea
              rows={2}
              value={reasoning}
              onChange={(e) => setReasoning(e.target.value)}
              className="w-full bg-slate-900 border border-slate-800 rounded-xl p-2 text-slate-200 focus:outline-none focus:border-sky-500"
            />
          </div>

          <div className="pt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-slate-900 text-slate-300 rounded-xl font-semibold border border-slate-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-5 py-2 bg-sky-500 hover:bg-sky-400 text-white font-bold rounded-xl flex items-center gap-1.5 shadow-lg shadow-sky-500/20"
            >
              <Send className="w-3.5 h-3.5" /> Broadcast Signal (INR)
            </button>
          </div>

        </form>

      </div>
    </div>
  );
};
