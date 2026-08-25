"""Small deployment-time compatibility patch for the dashboard.

The dashboard is intentionally kept as a single static HTML file. This boot patch
makes the two mobile regressions defensive at runtime without changing the bot's
trading logic:
  1. keep Backtest's NIFTY 50 label mapped to Yahoo's ^NSEI symbol;
  2. make the mobile theme control reliable on touch browsers;
  3. keep the Backtest controls on one compact row on phones.

The patch is idempotent and safe to run on every Render restart.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "dashboard" / "index.html"
BACKTEST = ROOT / "backtest.py"


def patch_html() -> None:
    text = HTML.read_text(encoding="utf-8")

    marker = "<!-- mavis-mobile-runtime-fix-v2 -->"
    if marker not in text:
        css = r'''<style id="mavis-mobile-runtime-fix-v2">
/* Mobile Backtest: Symbol / Strategy / Period / Run stay on one compact row. */
@media (max-width:820px){
  .form-grid{grid-template-columns:minmax(0,1.18fr) minmax(0,1fr) minmax(54px,.62fr) auto;gap:5px;align-items:end}
  .form-grid .field label{font-size:8px;margin-bottom:3px}
  .form-grid .field select{min-width:0;padding:8px 6px;font-size:11px;height:38px}
  .form-grid .run{grid-column:auto;min-width:50px;height:38px;padding:7px 9px;font-size:11px}
  .theme-pop{position:fixed !important;right:8px !important;top:64px !important;width:min(285px,calc(100vw - 16px)) !important;z-index:9999 !important}
}
</style>'''
        text = text.replace("</head>", css + "\n</head>", 1)

    # Use the canonical Yahoo symbol while retaining the user-facing label.
    text = text.replace(
        '<option>NIFTY 50</option><option>^NSEI</option>',
        '<option value="^NSEI">NIFTY 50</option><option value="^NSEI">^NSEI</option>',
        1,
    )

    # Replace the existing theme listener block with a touch-safe implementation.
    old = "themeBtn.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();const open=!themePop.classList.contains('open');themePop.classList.toggle('open',open);themeBtn.setAttribute('aria-expanded',String(open))})"
    new = "themeBtn.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();const open=!themePop.classList.contains('open');themePop.classList.toggle('open',open);themeBtn.setAttribute('aria-expanded',String(open))});themeBtn.addEventListener('pointerup',e=>{e.preventDefault();e.stopPropagation()})"
    if old in text:
        text = text.replace(old, new, 1)

    if marker not in text:
        text = text.replace("</body>", marker + "\n</body>", 1)

    HTML.write_text(text, encoding="utf-8")


def patch_backtest() -> None:
    text = BACKTEST.read_text(encoding="utf-8")
    old = '"XAUUSD": "GC=F",\n            "EURUSD": "EURUSD=X",'
    new = '"XAUUSD": "GC=F",\n            "NIFTY 50": "^NSEI",\n            "NIFTY": "^NSEI",\n            "BANK NIFTY": "^NSEBANK",\n            "BANKNIFTY": "^NSEBANK",\n            "EURUSD": "EURUSD=X",'
    if "\"NIFTY 50\": \"^NSEI\"" not in text and old in text:
        text = text.replace(old, new, 1)
    BACKTEST.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_html()
    patch_backtest()
    print("dashboard/backtest mobile compatibility patch applied")
