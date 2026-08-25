"""Independent reminder loop so one-hour reminders are not blocked by market-open checks."""
import threading
import time

import sweep_runtime


def start(main, interval_seconds=30):
    def loop():
        while True:
            try:
                now_ms = int(time.time() * 1000)
                for key, state in list(sweep_runtime.STATE.items()):
                    if state.get("reminder") or not state.get("initial"):
                        continue
                    try:
                        symbol, close_ts_text = key.rsplit(":", 1)
                        close_ts = int(close_ts_text)
                    except Exception:
                        continue
                    if now_ms < close_ts + 3600 * 1000:
                        continue
                    result = sweep_runtime.CONTEXT.get(key)
                    if result is None:
                        # Context may be unavailable after a restart; the main scanner
                        # will rebuild it on the next market scan.
                        continue
                    msg = sweep_runtime._signal_message(main, symbol, "NSE" if symbol.endswith(".NS") or "^NSE" in symbol else "Market", result, reminder=True)
                    main.send_sweep_to_all(msg, parse_mode="Markdown")
                    state["reminder"] = True
                    state["reminder_sent"] = now_ms
                    sweep_runtime._save()
            except Exception as e:
                try:
                    main.alert_error("Sweep reminder loop", e, cooldown_s=900)
                except Exception:
                    pass
            time.sleep(interval_seconds)
    threading.Thread(target=loop, daemon=True, name="sweep-reminders").start()
