# Mavis Trading Bot — Nifty 50 Stocks Edition

## What's New
- **15 Nifty 50 stocks** scanned with 4H sweep logic
- **Nifty account limit = 5** (was 3)
- **Separate Telegram button** for stock prices
- **Market-hours-only scanning** for .NS stocks (9:15–15:30 IST)
- **5-second Yahoo delay** — prevents Render IP blacklisting

## Stock Universe (15 names)

| Symbol | Name |
|--------|------|
| RELIANCE.NS | Reliance |
| HDFCBANK.NS | HDFC Bank |
| ICICIBANK.NS | ICICI Bank |
| INFY.NS | Infosys |
| TCS.NS | TCS |
| ITC.NS | ITC |
| SBIN.NS | SBI |
| BHARTIARTL.NS | Bharti Airtel |
| LT.NS | L&T |
| HINDUNILVR.NS | HUL |
| AXISBANK.NS | Axis Bank |
| KOTAKBANK.NS | Kotak Bank |
| BAJFINANCE.NS | Bajaj Finance |
| MARUTI.NS | Maruti |
| SUNPHARMA.NS | Sun Pharma |

## Architecture

### Account Routing
- `.NS` stocks → `nifty` account
- Nifty indices (`^NSEI`, `^NSEBANK`) → `nifty` account
- Forex/Gold/Crypto → `macro` or `ny_session` account

### Sweep Logic
- **Nifty indices**: 1H sweep (unchanged)
- **Individual `.NS` stocks**: 4H sweep (fetch 1h, resample to 4h)
- **Forex/Gold/Crypto**: 4H sweep (unchanged)

### Rate Limit Safety
- `_yf_min_delay = 5.0` seconds between Yahoo calls
- 22 total assets = 22 calls/hour (9× safety margin vs Yahoo limit)
- Market hours guard prevents wasted calls when NSE is closed

## Telegram Commands

| Command | Action |
|---------|--------|
| `/start` | Welcome + button menu |
| `/menu` | Resend button menu |
| `/nifty` | Show 15 stock prices |
| `/check` | Scan all assets + stocks |
| `/summary` | Live prices & status |
| `/stats` | Win rate & P/L report |
| `/balance` | Virtual account balances |
| `/clear` | Reset all to ₹1,00,000 |
| `/indi1` | Diagnose Strategy 1 (Sweep) |
| `/indi2` | Diagnose Strategy 2 (UT Bot) |
| `/pending` | Show sweep setups waiting for FVG |
| `/news` | Economic calendar |

## Button Menu
```
┌─────────────┬─────────────┐
│ 📊 Dashboard │ 🔥 Live     │
├─────────────┼─────────────┤
│ 📡 Signals   │ 📜 History  │
├─────────────┼─────────────┤
│ 💰 Balances  │ 📰 News     │
├─────────────┼─────────────┤
│ 📈 Nifty     │ 🔄 Refresh  │
└─────────────┴─────────────┘
```

## Precautions (Learned from Errors)

1. **`.NS` suffix mandatory** — `RELIANCE` fails, `RELIANCE.NS` works
2. **No `XAUUSD=X`** — invalid Yahoo symbol, removed
3. **5s yfinance delay** — prevents Render IP blacklisting
4. **Market hours guard** — `.NS` stocks only scan 9:15–15:30 IST
5. **String literals** — all multi-line strings use `\n` escapes
6. **markup.add()** — telebot uses `.add()`, never `.row()`
7. **safe_send fallback** — preserves `reply_markup` in fallback

## Deploy

1. Download `main_complete.py`
2. Rename to `main.py`
3. Push to GitHub → Render auto-deploys
4. Type `/start` in Telegram → buttons appear

## Rate Limit Math

| Metric | Value |
|--------|-------|
| Existing assets | 7 |
| New stocks | 15 |
| **Total scanned** | **22** |
| Calls per cycle | 22 |
| Delay between calls | 5s |
| Time per cycle | ~110s |
| Cycles per hour | ~32 |
| **Yahoo calls/hour** | **22** |
| Yahoo free limit | ~200–400/hour |
| **Safety margin** | **9×** |
