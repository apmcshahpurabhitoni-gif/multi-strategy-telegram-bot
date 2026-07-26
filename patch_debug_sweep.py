import re

with open("main.py", "r") as f:
    content = f.read()

old_debug_sweep = """def debug_sweep(ticker):
    try:
        df = yf.download(ticker, period="10d", interval="1h", progress=False, auto_adjust=True)
        df = normalise_cols(df)
        if df.empty or len(df) < 30:
            return msg_indi_debug_header(ticker, "Sweep + Engulfing") + \\
                   f"├ ⚠️ Not enough 1H data (`{len(df)}` candles, need 30)\\n" + BR2

        atr = float(calculate_atr(df, 10).iloc[-2])
        price = float(df["Close"].iloc[-1])
        vol = (atr / price * 100)
        vol_icon = "🟢" if vol >= MIN_VOLATILITY else "🔴"

        df_4h = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
        if len(df_4h) < 4:
            return msg_indi_debug_header(ticker, "Sweep + Engulfing") + \\
                   f"├ ⚠️ Not enough 4H data\\n" + BR2

        df_4h["ATR"] = calculate_atr(df_4h, 10)
        curr = df_4h.iloc[-2]
        mother = df_4h.iloc[-3]

        sweep_low  = curr["Low"] < mother["Low"]
        sweep_high = curr["High"] > mother["High"]
        engulf_up  = curr["Close"] > mother["High"]
        engulf_dn  = curr["Close"] < mother["Low"]

        low_icon  = "🟢" if sweep_low else "⚪"
        high_icon = "🟢" if sweep_high else "⚪"
        up_icon   = "🟢" if engulf_up else "⚪"
        dn_icon   = "🟢" if engulf_dn else "⚪"

        res = (
            f"{msg_indi_debug_header(ticker, 'Sweep + Engulfing')}"
            f"├ {vol_icon} *Volatility:* `{vol:.2f}%` (min `{MIN_VOLATILITY}%`)\\n"
            f"├ 📊 *Current 4H:*  H=`{curr['High']:.2f}`  L=`{curr['Low']:.2f}`  C=`{curr['Close']:.2f}`\\n"
            f"├ 📊 *Mother 4H:*   H=`{mother['High']:.2f}`  L=`{mother['Low']:.2f}`  C=`{mother['Close']:.2f}`\\n"
            f"{BR}\\n"
            f"├ {low_icon}  Sweep Low:  Curr L `{curr['Low']:.2f}` {'<' if sweep_low else '>='} Mother L `{mother['Low']:.2f}`\\n"
            f"├ {high_icon} Sweep High: Curr H `{curr['High']:.2f}` {'>' if sweep_high else '<='} Mother H `{mother['High']:.2f}`\\n"
            f"├ {up_icon}   Engulf Up:  Curr C `{curr['Close']:.2f}` {'>' if engulf_up else '<='} Mother H `{mother['High']:.2f}`\\n"
            f"└ {dn_icon}   Engulf Dn:  Curr C `{curr['Close']:.2f}` {'<' if engulf_dn else '>='} Mother L `{mother['Low']:.2f}`\\n"
            f"{BR}\\n"
        )

        if vol < MIN_VOLATILITY:
            res += "⛔ *RESULT:* Failed Volatility Check\\n"
        elif sweep_low and engulf_up:
            res += "✅ *RESULT:* 🟢 BULLISH Sweep + Engulfing Triggered\\n"
        elif sweep_high and engulf_dn:
            res += "✅ *RESULT:* 🔴 BEARISH Sweep + Engulfing Triggered\\n"
        else:
            res += "⚪ *RESULT:* No Sweep + Engulfing Condition Met\\n"

        res += BR2
        return res
    except Exception as e:
        return msg_error(f"Debug Sweep {ticker}", str(e))"""

new_debug_sweep = """def debug_sweep(ticker):
    try:
        df = yf.download(ticker, period="10d", interval="1h", progress=False, auto_adjust=True)
        df = normalise_cols(df)
        if df.empty or len(df) < 30:
            return msg_indi_debug_header(ticker, "Sweep + Reverse") + \\
                   f"├ ⚠️ Not enough 1H data (`{len(df)}` candles, need 30)\\n" + BR2

        df_4h = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
        if len(df_4h) < 4:
            return msg_indi_debug_header(ticker, "Sweep + Reverse") + \\
                   f"├ ⚠️ Not enough 4H data\\n" + BR2

        curr = df_4h.iloc[-2]
        mother = df_4h.iloc[-3]

        # Bullish conditions
        bull_break_low = curr["Low"] < mother["Low"]
        bull_break_high = curr["High"] > mother["High"]
        bull_close_above = curr["Close"] > mother["High"]

        # Bearish conditions
        bear_break_high = curr["High"] > mother["High"]
        bear_break_low = curr["Low"] < mother["Low"]
        bear_close_below = curr["Close"] < mother["Low"]

        b_low_icon  = "🟢" if bull_break_low else "⚪"
        b_high_icon = "🟢" if bull_break_high else "⚪"
        b_close_icon = "🟢" if bull_close_above else "⚪"

        br_high_icon = "🔴" if bear_break_high else "⚪"
        br_low_icon = "🔴" if bear_break_low else "⚪"
        br_close_icon = "🔴" if bear_close_below else "⚪"

        res = (
            f"{msg_indi_debug_header(ticker, 'Sweep + Reverse (4H)')}"
            f"├ 📊 *Candle 2:*  H=`{curr['High']:.2f}`  L=`{curr['Low']:.2f}`  C=`{curr['Close']:.2f}`\\n"
            f"├ 📊 *Candle 1:*  H=`{mother['High']:.2f}`  L=`{mother['Low']:.2f}`  C=`{mother['Close']:.2f}`\\n"
            f"{BR}\\n"
            f"🟢 *BULLISH LOGIC:*\\n"
            f"├ {b_low_icon}  Break Low:  C2 L `{curr['Low']:.2f}` < C1 L `{mother['Low']:.2f}`\\n"
            f"├ {b_high_icon} Break High: C2 H `{curr['High']:.2f}` > C1 H `{mother['High']:.2f}`\\n"
            f"├ {b_close_icon} Close Abv:  C2 C `{curr['Close']:.2f}` > C1 H `{mother['High']:.2f}`\\n"
            f"{BR}\\n"
            f"🔴 *BEARISH LOGIC:*\\n"
            f"├ {br_high_icon} Break High: C2 H `{curr['High']:.2f}` > C1 H `{mother['High']:.2f}`\\n"
            f"├ {br_low_icon} Break Low:  C2 L `{curr['Low']:.2f}` < C1 L `{mother['Low']:.2f}`\\n"
            f"├ {br_close_icon} Close Blw:  C2 C `{curr['Close']:.2f}` < C1 L `{mother['Low']:.2f}`\\n"
            f"{BR}\\n"
        )

        if bull_break_low and bull_break_high and bull_close_above:
            res += f"✅ *RESULT:* 🟢 BULLISH Sweep Triggered (SL: {curr['Low']:.2f})\\n"
        elif bear_break_high and bear_break_low and bear_close_below:
            res += f"✅ *RESULT:* 🔴 BEARISH Sweep Triggered (SL: {curr['High']:.2f})\\n"
        else:
            res += "⚪ *RESULT:* No Setup\\n"

        res += BR2
        return res
    except Exception as e:
        return msg_error(f"Debug Sweep {ticker}", str(e))"""

content = content.replace(old_debug_sweep, new_debug_sweep)

with open("main.py", "w") as f:
    f.write(content)
