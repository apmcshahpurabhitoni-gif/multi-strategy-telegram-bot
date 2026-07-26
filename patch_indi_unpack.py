with open("main.py", "r") as f:
    content = f.read()

# Replace sweep tuple index in cmd_indi1
old_indi1 = """                    if sweep[4]:
                        signals.append(f"🟢 `{symbol}` ➔ 🔵 Sweep *{sweep[0]}*  `${sweep[1]:,.4f}`\\n   └ 🏢 Executed on *ALL* accounts")
                        execute_trade(symbol, mtype, get_account(symbol), "Sweep + Engulfing", sweep[0], sweep[1], sweep[2], sweep[3], sweep[4])
                    else:
                        signals.append(f"🟡 `{symbol}` ➔ 🔵 Sweep *{sweep[0]}*  `${sweep[1]:,.4f}`\\n   └ ⚠️ Low volatility → NO-VOL account only")"""

new_indi1 = """                    signals.append(f"🟢 `{symbol}` ➔ 🔵 Sweep *{sweep[0]}*  `${sweep[1]:,.4f}`\\n   └ 🏢 Executed on *ALL* accounts")
                    execute_trade(symbol, mtype, get_account(symbol), "Sweep + Engulfing", sweep[0], sweep[1], sweep[2], sweep[3], sweep[4])"""
content = content.replace(old_indi1, new_indi1)

# Replace ut tuple index in cmd_indi2
old_indi2 = """                    if ut[4]:
                        signals.append(f"🟢 `{symbol}` ➔ 🟣 UT Bot *{ut[0]}*  `${ut[1]:,.4f}`\\n   └ 🏢 Executed on *ALL* accounts")
                        target = "ny_session" if ny_active else "macro"
                        execute_trade(symbol, mtype, target, "UT Bot Signals", ut[0], ut[1], ut[2], ut[3], ut[4])
                    else:
                        signals.append(f"🟡 `{symbol}` ➔ 🟣 UT Bot *{ut[0]}*  `${ut[1]:,.4f}`\\n   └ ⚠️ Low volatility → NO-VOL account only")"""

new_indi2 = """                    if ut[5]:
                        signals.append(f"🟢 `{symbol}` ➔ 🟣 UT Bot *{ut[0]}*  `${ut[1]:,.4f}`\\n   └ 🏢 Executed on *ALL* accounts")
                        target = "ny_session" if ny_active else "macro"
                        execute_trade(symbol, mtype, target, "UT Bot Signals", ut[0], ut[1], ut[2], ut[3], ut[4])
                    else:
                        signals.append(f"🟡 `{symbol}` ➔ 🟣 UT Bot *{ut[0]}*  `${ut[1]:,.4f}`\\n   └ ⚠️ Low volatility → NO-VOL account only")"""
content = content.replace(old_indi2, new_indi2)

with open("main.py", "w") as f:
    f.write(content)
