with open("main.py", "r") as f:
    content = f.read()

old_ut = """        if trend_15_is_bullish and m5_buy_cross:
            return ("BULLISH", price_val, atr_val, ts, vol_ok)
        if trend_15_is_bearish and m5_sell_cross:
            return ("BEARISH", price_val, atr_val, ts, vol_ok)"""

new_ut = """        if trend_15_is_bullish and m5_buy_cross:
            sl = price_val - (atr_val * ATR_MULT_SL)
            tp = price_val + (atr_val * ATR_MULT_TP)
            return ("BULLISH", price_val, sl, tp, ts, vol_ok)
        if trend_15_is_bearish and m5_sell_cross:
            sl = price_val + (atr_val * ATR_MULT_SL)
            tp = price_val - (atr_val * ATR_MULT_TP)
            return ("BEARISH", price_val, sl, tp, ts, vol_ok)"""

content = content.replace(old_ut, new_ut)

with open("main.py", "w") as f:
    f.write(content)
