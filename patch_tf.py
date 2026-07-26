import re
with open("main.py", "r") as f:
    content = f.read()

# Update check_sweep_engulfing
old_check = """def check_sweep_engulfing(ticker):
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

        del df_4h; gc.collect()"""

new_check = """def check_sweep_engulfing(ticker):
    try:
        df = yf.download(ticker, period="10d", interval="1h",
                         progress=False, auto_adjust=True)
        df = normalise_cols(df)
        if df.empty or len(df) < 30:
            del df; gc.collect()
            return None

        is_nifty = "^NSEI" in ticker or "^NSEBANK" in ticker

        if is_nifty:
            df_target = df
        else:
            df_target = (
                df.resample("4h")
                .agg({"Open": "first", "High": "max",
                      "Low": "min", "Close": "last"})
                .dropna()
            )
            del df; gc.collect()

        if len(df_target) < 4:
            return None

        curr   = df_target.iloc[-2]  # Candle 2
        mother = df_target.iloc[-3]  # Candle 1
        ts = int(df_target.index[-2].timestamp() * 1000)

        price = float(curr["Close"])

        if not is_nifty:
            del df_target; gc.collect()"""
content = content.replace(old_check, new_check)


# Update debug_sweep
old_debug = """def debug_sweep(ticker):
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
        mother = df_4h.iloc[-3]"""

new_debug = """def debug_sweep(ticker):
    try:
        df = yf.download(ticker, period="10d", interval="1h", progress=False, auto_adjust=True)
        df = normalise_cols(df)
        if df.empty or len(df) < 30:
            return msg_indi_debug_header(ticker, "Sweep + Reverse") + \\
                   f"├ ⚠️ Not enough 1H data (`{len(df)}` candles, need 30)\\n" + BR2

        is_nifty = "^NSEI" in ticker or "^NSEBANK" in ticker
        tf_label = "1H" if is_nifty else "4H"

        if is_nifty:
            df_target = df
        else:
            df_target = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()

        if len(df_target) < 4:
            return msg_indi_debug_header(ticker, "Sweep + Reverse") + \\
                   f"├ ⚠️ Not enough {tf_label} data\\n" + BR2

        curr = df_target.iloc[-2]
        mother = df_target.iloc[-3]"""
content = content.replace(old_debug, new_debug)

# Fix msg format in debug_sweep
old_msg = """        res = (
            f"{msg_indi_debug_header(ticker, 'Sweep + Reverse (4H)')}\"
"""
new_msg = """        res = (
            f"{msg_indi_debug_header(ticker, f'Sweep + Reverse ({tf_label})')}\"
"""
content = content.replace(old_msg, new_msg)


# Update timeframe display in execute_trade
old_tf = """        tf = "4H" if "Sweep" in strat else "15m" """
new_tf = """        if "Sweep" in strat:
            tf = "1H" if ("^NSEI" in symbol or "^NSEBANK" in symbol) else "4H"
        else:
            tf = "15m" """
content = content.replace(old_tf, new_tf)

# Update guide and scanning messages
content = content.replace("├ 🔵 *Sweep + Reverse*    (4H timeframe)", "├ 🔵 *Sweep + Reverse*    (4H / 1H Nifty)")
content = content.replace("name = \"Sweep + Reverse (4H)\" if num == 1 else \"UT Bot (15m + 5m EMA)\"", "name = \"Sweep + Reverse (4H / 1H)\" if num == 1 else \"UT Bot (15m + 5m EMA)\"")
content = content.replace("🔵 Sweep + Engulfing (4H)", "🔵 Sweep + Reverse (4H / 1H)")


with open("main.py", "w") as f:
    f.write(content)
