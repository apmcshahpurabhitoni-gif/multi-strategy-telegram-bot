import re
with open("main.py", "r") as f:
    content = f.read()

# Replace check_sweep_engulfing
old_check_sweep = """def check_sweep_engulfing(ticker):
    try:
        df = yf.download(ticker, period="10d", interval="1h",
                         progress=False, auto_adjust=True)
        df = normalise_cols(df)
        if df.empty or len(df) < 30:
            del df; gc.collect()
            return None

        vol_ok = True
        try:
            atr   = float(calculate_atr(df, 10).iloc[-2])
            price = float(df["Close"].iloc[-1])
            if (atr / price * 100) < MIN_VOLATILITY:
                vol_ok = False
        except Exception:
            pass

        df_4h = (
            df.resample("4h")
            .agg({"Open": "first", "High": "max",
                  "Low": "min", "Close": "last"})
            .dropna()
        )
        del df; gc.collect()

        if len(df_4h) < 4:
            return None

        df_4h["ATR"] = calculate_atr(df_4h, 10)
        atr = float(df_4h["ATR"].iloc[-2])

        curr   = df_4h.iloc[-2]
        mother = df_4h.iloc[-3]
        ts = int(df_4h.index[-2].timestamp() * 1000)

        del df_4h; gc.collect()

        if curr["Low"] < mother["Low"] and curr["Close"] > mother["High"]:
            return ("BULLISH", float(curr["Close"]), atr, ts, vol_ok)
        if curr["High"] > mother["High"] and curr["Close"] < mother["Low"]:
            return ("BEARISH", float(curr["Close"]), atr, ts, vol_ok)

    except Exception as e:
        print(f"[ERR] Sweep {ticker}: {e}")
    return None"""

new_check_sweep = """def check_sweep_engulfing(ticker):
    try:
        df = yf.download(ticker, period="10d", interval="1h",
                         progress=False, auto_adjust=True)
        df = normalise_cols(df)
        if df.empty or len(df) < 30:
            del df; gc.collect()
            return None

        df_4h = (
            df.resample("4h")
            .agg({"Open": "first", "High": "max",
                  "Low": "min", "Close": "last"})
            .dropna()
        )
        del df; gc.collect()

        if len(df_4h) < 4:
            return None

        curr   = df_4h.iloc[-2]  # Candle 2
        mother = df_4h.iloc[-3]  # Candle 1
        ts = int(df_4h.index[-2].timestamp() * 1000)

        price = float(curr["Close"])

        del df_4h; gc.collect()

        # Bullish: 2nd candle breaks low of 1st, breaks high of 1st, closes above high of 1st
        if curr["Low"] < mother["Low"] and curr["High"] > mother["High"] and curr["Close"] > mother["High"]:
            sl = float(curr["Low"])
            risk = price - sl
            if risk <= 0: return None
            tp = price + (risk * 2.0)  # 1:2 RR
            return ("BULLISH", price, sl, tp, ts, True) # True for vol_ok (always executes)

        # Bearish: 2nd candle breaks high of 1st, breaks low of 1st, closes below low of 1st
        if curr["High"] > mother["High"] and curr["Low"] < mother["Low"] and curr["Close"] < mother["Low"]:
            sl = float(curr["High"])
            risk = sl - price
            if risk <= 0: return None
            tp = price - (risk * 2.0)  # 1:2 RR
            return ("BEARISH", price, sl, tp, ts, True) # True for vol_ok (always executes)

    except Exception as e:
        print(f"[ERR] Sweep {ticker}: {e}")
    return None"""

content = content.replace(old_check_sweep, new_check_sweep)

with open("main.py", "w") as f:
    f.write(content)
