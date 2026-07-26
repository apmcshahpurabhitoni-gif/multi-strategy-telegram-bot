with open("main.py", "r") as f:
    content = f.read()

# Remove calc_sl_tp since strategies will do it now
content = content.replace("""def calc_sl_tp(sig_type, entry, atr):
    if "BULLISH" in sig_type:
        return float(entry - atr * ATR_MULT_SL), float(entry + atr * ATR_MULT_TP)
    return float(entry + atr * ATR_MULT_SL), float(entry - atr * ATR_MULT_TP)

""", "")

# Update execute_trade signature and logic
old_exec = """def execute_trade(symbol, mtype, account, strat, sig_type, price, atr, ts):
    global active_trades

    with _lock:
        key = f"{symbol}_{ts}_{sig_type}_{account}"
        if key in sent_signals:
            return
        sent_signals[key] = True
        save_json(SENT_SIGNALS_FILE, sent_signals)

        if accounts[account]["daily_trades"] >= bot_settings.get("daily_limit", 3):
            return
        if any(t["symbol"] == symbol and t["account"] == account for t in active_trades):
            return

        sl = calc_sl_tp(sig_type, price, atr)[0]
        qty = calc_position_size(account, price, sl)
        if qty <= 0:
            return

        actual_sl, actual_tp = calc_sl_tp(sig_type, price, atr)
        tf = "4H" if "Sweep" in strat else "15m\""""

new_exec = """def execute_trade(symbol, mtype, account, strat, sig_type, price, sl, tp, ts):
    global active_trades

    with _lock:
        key = f"{symbol}_{ts}_{sig_type}_{account}"
        if key in sent_signals:
            return
        sent_signals[key] = True
        save_json(SENT_SIGNALS_FILE, sent_signals)

        if accounts[account]["daily_trades"] >= bot_settings.get("daily_limit", 3):
            return
        if any(t["symbol"] == symbol and t["account"] == account for t in active_trades):
            return

        qty = calc_position_size(account, price, sl)
        if qty <= 0:
            return

        actual_sl, actual_tp = float(sl), float(tp)
        tf = "4H" if "Sweep" in strat else "15m\""""

content = content.replace(old_exec, new_exec)

with open("main.py", "w") as f:
    f.write(content)
