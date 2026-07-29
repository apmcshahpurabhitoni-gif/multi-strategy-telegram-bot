import React, { useState } from 'react';
import { 
  X, 
  Send, 
  Copy, 
  Check, 
  BarChart3
} from 'lucide-react';
import { TradingSignal } from '../types';
import { formatInr, formatInrPrice } from '../utils/formatters';

interface SignalDetailModalProps {
  signal: TradingSignal | null;
  onClose: () => void;
  onSendTelegram: (signal: TradingSignal) => void;
}

export const SignalDetailModal: React.FC<SignalDetailModalProps> = ({
  signal,
  onClose,
  onSendTelegram
}) => {
  const [copied, setCopied] = useState(false);
  const [dispatched, setDispatched] = useState(false);

  if (!signal) return null;

  const isBuy = signal.direction === 'BUY';
  const priceDiff = signal.currentPrice - signal.entryPrice;
  const priceDiffPct = ((priceDiff / signal.entryPrice) * 100).toFixed(2);
  const isProfit = isBuy ? priceDiff >= 0 : priceDiff <= 0;

  // Format Telegram preview text in Indian Rupees
  const telegramPreviewText = `🚨 *NEW TRADING SIGNAL (INR)* 🚨
  
*Pair:* #${signal.symbol.replace('/', '_')} (${signal.timeframe})
*Action:* ${isBuy ? '🟢 BUY / LONG' : '🔴 SELL / SHORT'}
*Strategy:* ${signal.strategy.replace(/_/g, ' ')}
  
*Entry Zone:* ${formatInrPrice(signal.entryPrice)}
*Current Price:* ${formatInrPrice(signal.currentPrice)}
  
🎯 *Take Profit 1:* ${formatInrPrice(signal.takeProfit1)}
🎯 *Take Profit 2:* ${formatInrPrice(signal.takeProfit2)}
🛑 *Stop Loss:* ${formatInrPrice(signal.stopLoss)}
  
*Risk / Reward:* 1 : ${signal.riskRewardRatio}
*Confidence:* ${signal.confidence}%
*Estimated Profit:* ${formatInr(signal.estimatedProfitInr || 15000)}
  
💡 *Rationale:* ${signal.reasoning}
  
⚡ *Indicators:*
• RSI (14): ${signal.indicators.rsi}
• MACD Hist: ${signal.indicators.macdHist}
• Vol 24h Ratio: ${signal.indicators.volume24hRatio}x
  
🤖 *Sent via QuantBot Pro (INR)*`;

  const handleCopy = () => {
    navigator.clipboard.writeText(telegramPreviewText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDispatch = () => {
    onSendTelegram(signal);
    setDispatched(true);
    setTimeout(() => setDispatched(false), 2500);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div className="bg-[#1e293b] border border-slate-800 rounded-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto shadow-2xl">
        
        {/* Modal Header */}
        <div className="p-5 border-b border-slate-800 flex items-center justify-between sticky top-0 bg-[#1e293b]/95 backdrop-blur-md z-10">
          <div className="flex items-center gap-3">
            <span className={`px-3 py-1 rounded-lg font-black text-sm font-mono tracking-wider ${
              isBuy ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
            }`}>
              {signal.direction}
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-extrabold text-white text-lg font-mono">{signal.symbol}</h3>
                <span className="text-xs px-2 py-0.5 rounded bg-slate-900 text-slate-300 font-mono border border-slate-800">
                  {signal.timeframe}
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Generated: {new Date(signal.timestamp).toLocaleTimeString()} • Strategy: {signal.strategy.replace(/_/g, ' ')}
              </p>
            </div>
          </div>

          <button 
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white bg-slate-900 rounded-lg border border-slate-800 transition-all"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-5">
          
          {/* Key Targets Bar in INR */}
          <div className="bg-slate-950 border border-slate-800 rounded-xl p-4">
            <div className="text-xs text-slate-400 mb-2 font-medium">Price Execution Zone (Indian Rupees - INR ₹)</div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono text-center">
              <div className="bg-slate-900 p-2.5 rounded-lg border border-slate-800">
                <span className="text-[11px] text-slate-400 block">Entry</span>
                <span className="font-bold text-slate-200 text-xs">{formatInrPrice(signal.entryPrice)}</span>
              </div>
              <div className="bg-slate-900 p-2.5 rounded-lg border border-slate-800">
                <span className="text-[11px] text-slate-400 block">Current</span>
                <span className={`font-bold text-xs ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {formatInrPrice(signal.currentPrice)}
                </span>
              </div>
              <div className="bg-emerald-950/40 p-2.5 rounded-lg border border-emerald-500/30">
                <span className="text-[11px] text-emerald-400 block">TP2 Target</span>
                <span className="font-bold text-emerald-400 text-xs">{formatInrPrice(signal.targetPrice)}</span>
              </div>
              <div className="bg-rose-950/40 p-2.5 rounded-lg border border-rose-500/30">
                <span className="text-[11px] text-rose-400 block">Stop Loss</span>
                <span className="font-bold text-rose-400 text-xs">{formatInrPrice(signal.stopLoss)}</span>
              </div>
            </div>
          </div>

          {/* Technical Indicator Analysis Grid */}
          <div className="space-y-2">
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <BarChart3 className="w-4 h-4 text-sky-400" />
              Indicator Snapshot
            </h4>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs font-mono">
              <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                <span className="text-slate-400 text-[11px] block">RSI Oscillator (14)</span>
                <span className="text-white font-bold text-sm">{signal.indicators.rsi}</span>
                <span className="text-[10px] text-slate-500 block">
                  {signal.indicators.rsi < 35 ? 'Oversold Bullish' : signal.indicators.rsi > 65 ? 'Overbought' : 'Neutral'}
                </span>
              </div>
              <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                <span className="text-slate-400 text-[11px] block">MACD Histogram</span>
                <span className="text-white font-bold text-sm">{signal.indicators.macdHist}</span>
                <span className="text-[10px] text-emerald-400 block">Crossed Above Signal</span>
              </div>
              <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                <span className="text-slate-400 text-[11px] block">Volume 24h Ratio</span>
                <span className="text-emerald-400 font-bold text-sm">{signal.indicators.volume24hRatio}x</span>
                <span className="text-[10px] text-slate-500 block">Spike vs Avg</span>
              </div>
              <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                <span className="text-slate-400 text-[11px] block">Risk / Reward</span>
                <span className="text-sky-400 font-bold text-sm">1 : {signal.riskRewardRatio}</span>
                <span className="text-[10px] text-slate-500 block">Favorable</span>
              </div>
              <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                <span className="text-slate-400 text-[11px] block">Estimated Profit</span>
                <span className="text-emerald-400 font-bold text-sm">{formatInr(signal.estimatedProfitInr || 12000)}</span>
                <span className="text-[10px] text-slate-500 block">In Rupees</span>
              </div>
              <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                <span className="text-slate-400 text-[11px] block">Sentiment Score</span>
                <span className="text-white font-bold text-sm">{signal.indicators.sentimentScore}/100</span>
                <span className="text-[10px] text-slate-500 block">Strong Bullish</span>
              </div>
            </div>
          </div>

          {/* Rationale Explanation */}
          <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 text-xs">
            <span className="text-slate-400 font-semibold block mb-1">Signal Reasoning & Rationale:</span>
            <p className="text-slate-300 leading-relaxed font-sans">{signal.reasoning}</p>
          </div>

          {/* Telegram Alert Preview Box */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold text-sky-400 uppercase tracking-wider flex items-center gap-1.5">
                <Send className="w-4 h-4 text-sky-400" />
                Telegram Bot Message Preview (INR Format)
              </h4>
              <button 
                onClick={handleCopy}
                className="text-xs text-slate-400 hover:text-white flex items-center gap-1 bg-slate-900 px-2.5 py-1 rounded border border-slate-800"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                {copied ? 'Copied!' : 'Copy Text'}
              </button>
            </div>
            <pre className="bg-slate-950 border border-slate-800 p-3.5 rounded-xl font-mono text-xs text-sky-200/90 whitespace-pre-wrap overflow-x-auto leading-relaxed shadow-inner">
              {telegramPreviewText}
            </pre>
          </div>

        </div>

        {/* Modal Footer Actions */}
        <div className="p-4 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between gap-3">
          <div className="text-xs text-slate-400 font-mono">
            Telegram Status: <span className="text-emerald-400 font-semibold">{signal.telegramSent ? 'Broadcast Sent' : 'Pending'}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 bg-slate-900 hover:bg-slate-800 text-slate-300 text-xs font-semibold rounded-lg border border-slate-800"
            >
              Close
            </button>
            <button
              onClick={handleDispatch}
              className="px-4 py-2 bg-sky-500 hover:bg-sky-400 text-white text-xs font-bold rounded-lg shadow-lg shadow-sky-500/20 flex items-center gap-1.5 transition-all active:scale-95"
            >
              <Send className="w-3.5 h-3.5" />
              {dispatched ? 'Alert Dispatched!' : 'Dispatch to Telegram'}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
};
