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

    marker = "<!-- mavis-mobile-runtime-fix-v4 -->"
    if marker not in text:
        css = r'''<style id="mavis-mobile-runtime-fix-v4">
@media(max-width:820px){
  /* Keep all Backtest controls on one compact mobile row. */
  .form-grid{grid-template-columns:minmax(0,1.18fr) minmax(0,1fr) minmax(54px,.62fr) auto;gap:5px;align-items:end}
  .form-grid .field label{font-size:8px;margin-bottom:3px}
  .form-grid .field select{min-width:0;padding:8px 6px;font-size:11px;height:38px}
  .form-grid .run{grid-column:auto;min-width:50px;height:38px;padding:7px 9px;font-size:11px}
  /* Theme popover must sit above the mobile UI and remain touchable. */
  .theme-box{position:relative;z-index:10001}
  #themeBtn{position:relative;z-index:10003;touch-action:manipulation;-webkit-tap-highlight-color:transparent}
  .theme-pop{position:fixed !important;right:8px !important;top:64px !important;width:min(285px,calc(100vw - 16px)) !important;max-height:calc(100vh - 80px) !important;overflow:auto !important;z-index:10002 !important;pointer-events:auto !important;touch-action:manipulation}
  .theme-choice,.swatch{touch-action:manipulation;-webkit-tap-highlight-color:transparent}
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

    touch_marker = "<!-- mavis-theme-pointer-fix-v4 -->"
    if touch_marker not in text:
        touch_js = r'''<script>
(()=>{
  const b=document.getElementById('themeBtn'),p=document.getElementById('themePop');
  if(!b||!p)return;
  let suppressClick=false;
  const setOpen=(open)=>{
    p.classList.toggle('open',open);
    b.setAttribute('aria-expanded',String(open));
  };
  const toggle=()=>setOpen(!p.classList.contains('open'));

  /* Android Chrome reliably delivers Pointer Events even when click handling is
     affected by an overlay or touch compatibility event. Handle touch/pen here,
     then suppress the synthetic click so the menu does not toggle twice. */
  b.addEventListener('pointerup',e=>{
    if(e.pointerType!=='mouse'){
      e.preventDefault();
      e.stopPropagation();
      suppressClick=true;
      toggle();
      setTimeout(()=>{suppressClick=false;},700);
    }
  },{capture:true,passive:false});

  document.addEventListener('click',e=>{
    if(suppressClick && (e.target===b || b.contains(e.target))){
      e.preventDefault();
      e.stopImmediatePropagation();
      suppressClick=false;
    }
  },true);

  /* Also make the theme choices themselves deterministic on touch devices. */
  p.querySelectorAll('.theme-choice').forEach(choice=>{
    choice.addEventListener('pointerup',e=>{
      if(e.pointerType!=='mouse'){
        e.preventDefault();
        e.stopPropagation();
        choice.click();
      }
    },{capture:true,passive:false});
  });
  p.querySelectorAll('.swatch').forEach(choice=>{
    choice.addEventListener('pointerup',e=>{
      if(e.pointerType!=='mouse'){
        e.preventDefault();
        e.stopPropagation();
        choice.click();
      }
    },{capture:true,passive:false});
  });
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
