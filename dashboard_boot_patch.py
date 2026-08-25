"""Deployment-time compatibility patch for the dashboard.

Render runs this file before the bot starts. It is intentionally idempotent.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "dashboard" / "index.html"
BACKTEST = ROOT / "backtest.py"


def patch_html() -> None:
    if not HTML.exists():
        return
    text = HTML.read_text(encoding="utf-8")

    marker = "<!-- mavis-mobile-runtime-fix-v3 -->"
    if marker not in text:
        css = r'''<style id="mavis-mobile-runtime-fix-v3">
@media(max-width:820px){
  /* Keep all Backtest controls on one compact mobile row. */
  .form-grid{grid-template-columns:minmax(0,1.18fr) minmax(0,1fr) minmax(54px,.62fr) auto;gap:5px;align-items:end}
  .form-grid .field label{font-size:8px;margin-bottom:3px}
  .form-grid .field select{min-width:0;padding:8px 6px;font-size:11px;height:38px}
  .form-grid .run{grid-column:auto;min-width:50px;height:38px;padding:7px 9px;font-size:11px}
  .theme-pop{position:fixed !important;right:8px !important;top:64px !important;width:min(285px,calc(100vw - 16px)) !important;z-index:9999 !important}
}
</style>'''
        text = text.replace("</head>", css + "\n</head>", 1)
        text = text.replace("</body>", marker + "\n</body>", 1)

    # Friendly dashboard label -> Yahoo ticker at the browser layer as well.
    text = text.replace(
        '<option>NIFTY 50</option>',
        '<option value="^NSEI">NIFTY 50</option>',
        1,
    )

    touch_marker = "<!-- mavis-theme-touch-fix-v3 -->"
    if touch_marker not in text:
        touch_js = r'''<script>
(()=>{
  const b=document.getElementById('themeBtn'),p=document.getElementById('themePop');
  if(!b||!p)return;
  const toggle=()=>{const open=!p.classList.contains('open');p.classList.toggle('open',open);b.setAttribute('aria-expanded',String(open));};
  b.addEventListener('touchend',e=>{e.preventDefault();e.stopPropagation();toggle();},{passive:false});
})();
</script>'''
        text = text.replace("</body>", touch_marker + "\n" + touch_js + "\n</body>", 1)

    HTML.write_text(text, encoding="utf-8")


def patch_backtest() -> None:
    if not BACKTEST.exists():
        return
    text = BACKTEST.read_text(encoding="utf-8")

    # Previous versions tried to replace one exact line pair. That silently failed
    # when formatting changed. Insert aliases directly after the mapping opening.
    if '"NIFTY 50": "^NSEI"' not in text:
        pattern = r'(mapping\s*=\s*\{\s*\n)'
        replacement = (
            r'\1'
            '            "NIFTY 50": "^NSEI",\n'
            '            "NIFTY50": "^NSEI",\n'
            '            "NIFTY": "^NSEI",\n'
            '            "BANK NIFTY": "^NSEBANK",\n'
            '            "BANKNIFTY": "^NSEBANK",\n'
        )
        text, count = re.subn(pattern, replacement, text, count=1)
        if count != 1:
            # Fallback for unusual formatting: replace the function's mapping
            # declaration without depending on indentation of existing entries.
            needle = '        mapping = {'
            if needle in text:
                text = text.replace(
                    needle,
                    needle + '\n'
                    '            "NIFTY 50": "^NSEI",\n'
                    '            "NIFTY50": "^NSEI",\n'
                    '            "NIFTY": "^NSEI",\n'
                    '            "BANK NIFTY": "^NSEBANK",\n'
                    '            "BANKNIFTY": "^NSEBANK",',
                    1,
                )

    BACKTEST.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_html()
    patch_backtest()
    print("dashboard/backtest compatibility patch applied")
