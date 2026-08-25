"""Production entry point.

Loads the existing bot in the __main__ namespace, installs the canonical sweep
engine, then starts the same services as the original main.py. This keeps the
existing dashboard/Telegram/paper-trading system intact while making the sweep
rules deterministic and testable.
"""
import os
import time

_original_name = globals().get("__name__", "__main__")
_original_file = globals().get("__file__", os.path.abspath(__file__))
_source_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")

globals()["__name__"] = "mavis_source"
globals()["__file__"] = _source_file
with open(_source_file, "r", encoding="utf-8") as _f:
    _source = _f.read()
exec(compile(_source, _source_file, "exec"), globals(), globals())
globals()["__name__"] = _original_name
globals()["__file__"] = _original_file

from sweep_runtime import install as install_sweep_runtime
install_sweep_runtime(__import__("__main__"))

if __name__ == "__main__":
    print("[INIT] Starting bot through run_bot.py")
    init_accounts()
    history = load_json(HISTORY_FILE, [])
    sent_signals = load_json(SENT_SIGNALS_FILE, {})
    muted_assets = set(load_json(MUTE_FILE, []))
    start_time_str = datetime.now(IST).strftime("%d-%b-%Y %H:%M IST")
    start_msg = (
        f"✅ *BOT STARTED — SWEEP ENGINE V2*\n{BR}\n"
        f"🕒 *Started At:* `{start_time_str}`\n"
        f"🔒 *Sweep Rule:* Closed candle must break BOTH previous High and Low.\n"
        f"📌 *Close:* Above = BUY · Inside/equal = NEUTRAL · Below = SELL.\n"
        f"⚠️ *Data mismatch warnings:* ENABLED\n"
        f"🔔 *Reminder:* One hour after signal; maximum 2 messages/candle.\n"
        f"{BR2}"
    )
    send_to_personal_only(start_msg, parse_mode="Markdown")
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=scanner, daemon=True).start()
    threading.Thread(target=daily_reset, daemon=True).start()
    threading.Thread(target=weekly_digest_loop, daemon=True).start()
    threading.Thread(target=warm_news_cache, daemon=True).start()
    from sweep_reminder import start as start_sweep_reminders
    start_sweep_reminders(__import__("__main__"))
    print("[INIT] Bot running with canonical Sweep Engine V2")
    while True:
        time.sleep(3600)
