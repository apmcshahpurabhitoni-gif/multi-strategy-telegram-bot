with open("main.py", "r") as f:
    content = f.read()

# Update scanner_loop unpacks
content = content.replace(
    'execute_trade(symbol, mtype, "utbot_novol", "UT Bot (No-Vol)", ut[0], ut[1], ut[2], ut[3])',
    'execute_trade(symbol, mtype, "utbot_novol", "UT Bot (No-Vol)", ut[0], ut[1], ut[2], ut[3], ut[4])'
)
content = content.replace(
    'execute_trade(symbol, mtype, target, "UT Bot Signals", ut[0], ut[1], ut[2], ut[3])',
    'execute_trade(symbol, mtype, target, "UT Bot Signals", ut[0], ut[1], ut[2], ut[3], ut[4])'
)
content = content.replace(
    'execute_trade(symbol, mtype, "sweep_novol", "Sweep (No-Vol)", sweep[0], sweep[1], sweep[2], sweep[3])',
    'execute_trade(symbol, mtype, "sweep_novol", "Sweep (No-Vol)", sweep[0], sweep[1], sweep[2], sweep[3], sweep[4])'
)
content = content.replace(
    'execute_trade(symbol, mtype, account, "Sweep + Engulfing", sweep[0], sweep[1], sweep[2], sweep[3])',
    'execute_trade(symbol, mtype, account, "Sweep + Engulfing", sweep[0], sweep[1], sweep[2], sweep[3], sweep[4])'
)

# Update check_sweep_engulfing condition in scanner_loop (always execute, ignore vol toggle)
old_sweep_exec = """                sweep = check_sweep_engulfing(symbol)
                if sweep:
                    # Execute on novol tracker
                    execute_trade(symbol, mtype, "sweep_novol", "Sweep (No-Vol)", sweep[0], sweep[1], sweep[2], sweep[3], sweep[4])

                    if not vol_filter_on or sweep[4]:
                        execute_trade(symbol, mtype, account, "Sweep + Engulfing", sweep[0], sweep[1], sweep[2], sweep[3], sweep[4])"""

new_sweep_exec = """                sweep = check_sweep_engulfing(symbol)
                if sweep:
                    # Strategy 1 executes on pure logic (no volatility filters apply)
                    execute_trade(symbol, mtype, "sweep_novol", "Sweep (No-Vol)", sweep[0], sweep[1], sweep[2], sweep[3], sweep[4])
                    execute_trade(symbol, mtype, account, "Sweep + Engulfing", sweep[0], sweep[1], sweep[2], sweep[3], sweep[4])"""
content = content.replace(old_sweep_exec, new_sweep_exec)

# Update ut[4] check in check_ut_bot
content = content.replace(
    'if not vol_filter_on or ut[4]:',
    'if not vol_filter_on or ut[5]:'
)

with open("main.py", "w") as f:
    f.write(content)
