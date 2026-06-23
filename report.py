import base64
import json
import os
import shutil
import subprocess
import sys
import time
from io import BytesIO

from PIL import Image

from version import __version__


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_date(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _thumb_b64(path: str) -> str | None:
    try:
        with Image.open(path) as img:
            img.thumbnail((120, 120))
            buf = BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _is_image(path: str) -> bool:
    return path.lower().endswith((".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"))


_nswindow = None   # module-level refs prevent GC closing the window
_wkwebview = None


def open_loading_page(port: int) -> None:
    global _nswindow, _wkwebview
    import server as _srv

    loading_html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Sweep — Scanning</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; overflow: hidden;
    -webkit-user-select: none; user-select: none; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif;
    background: #18181B; color: #fff;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
  }
  .logo { width: 64px; height: 64px; background: #FF6551; border-radius: 18px;
    display: flex; align-items: center; justify-content: center;
    margin-bottom: 24px; box-shadow: 0 8px 32px rgba(255,101,81,.3); }
  .logo svg { width: 32px; height: 32px; stroke: #fff; stroke-width: 2;
    stroke-linecap: round; stroke-linejoin: round; fill: none; }
  h2 { font-size: 22px; font-weight: 700; margin-bottom: 6px; letter-spacing: -.3px; }
  .step { font-size: 13px; color: rgba(255,255,255,.3); margin-bottom: 36px; min-height: 18px; }
  .ring-wrap { position: relative; width: 100px; height: 100px; }
  .ring-wrap svg { transform: rotate(-90deg); display: block; }
  .pct { position: absolute; inset: 0; display: flex; align-items: center;
    justify-content: center; font-size: 22px; font-weight: 800; color: #FF6551; }
  circle { fill: none; }
  .ring-bg { stroke: rgba(255,255,255,.07); }
  .ring-fg { stroke: #FF6551; stroke-linecap: round; transition: stroke-dashoffset .5s ease; }
</style>
</head>
<body>
<div class="logo"><svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M17.7 7.7a2.5 2.5 0 1 1 1.8 4.3H2"/><path d="M9.6 4.6A2 2 0 1 1 11 8H2"/><path d="M12.6 19.4A2 2 0 1 0 14 16H2"/></svg></div>
<h2>Scanning your Mac…</h2>
<div class="step" id="step">Starting up…</div>
<div class="ring-wrap">
  <svg viewBox="0 0 100 100" width="100" height="100">
    <circle class="ring-bg" cx="50" cy="50" r="45" stroke-width="5"/>
    <circle class="ring-fg" id="ring" cx="50" cy="50" r="45" stroke-width="5"/>
  </svg>
  <div class="pct" id="pct">0%</div>
</div>
<script>
const C = 2 * Math.PI * 45;
const ring = document.getElementById('ring');
ring.style.strokeDasharray = C;
ring.style.strokeDashoffset = C;
async function poll() {
  try {
    const r = await fetch('/status');
    const d = await r.json();
    const pct = d.pct || 0;
    document.getElementById('pct').textContent = pct + '%';
    ring.style.strokeDashoffset = C * (1 - pct / 100);
    document.getElementById('step').textContent = d.step || 'Scanning…';
    if (d.ready) {
      document.getElementById('pct').textContent = '100%';
      ring.style.strokeDashoffset = 0;
      setTimeout(() => window.location.href = '/report', 400);
      return;
    }
  } catch(e) {}
  setTimeout(poll, 600);
}
poll();
</script>
</body>
</html>"""

    _srv.set_loading(loading_html)

    # Build native NSWindow + WKWebView on the main thread (rumps callbacks run there)
    import AppKit
    from WebKit import WKWebView, WKWebViewConfiguration
    from Foundation import NSURL, NSURLRequest

    url_str = f'http://127.0.0.1:{port}/loading'

    # Close previous window if still open
    if _nswindow is not None:
        try:
            _nswindow.close()
        except Exception:
            pass

    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        AppKit.NSMakeRect(0, 0, 1280, 820),
        15,   # titled | closable | miniaturizable | resizable
        AppKit.NSBackingStoreBuffered,
        False,
    )
    window.setTitle_("Sweep")
    window.setReleasedWhenClosed_(False)

    config = WKWebViewConfiguration.alloc().init()
    prefs = config.preferences()
    prefs.setJavaScriptEnabled_(True)
    webview = WKWebView.alloc().initWithFrame_configuration_(
        AppKit.NSMakeRect(0, 0, 0, 0), config
    )
    webview.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(url_str)))

    window.setContentView_(webview)
    window.center()
    AppKit.NSApp.activateIgnoringOtherApps_(True)
    window.makeKeyAndOrderFront_(None)

    _nswindow = window
    _wkwebview = webview


def build_report_html(scan_result: dict, port: int = 0) -> str:
    return _build_html(scan_result, port)



def _build_html(scan_result: dict, port: int = 0) -> str:
    screenshots    = scan_result.get("screenshots", [])
    bad_photos     = scan_result.get("bad_photos", [])
    duplicates     = scan_result.get("duplicates", [])
    downloads      = scan_result.get("downloads", [])
    trash          = scan_result.get("trash", {"size": 0, "path": ""})
    language_files = scan_result.get("language_files", [])
    mail_attachments = scan_result.get("mail_attachments", [])
    cache_sizes    = scan_result.get("cache_sizes", {})
    browser_caches = scan_result.get("browser_caches", {})
    node_modules   = scan_result.get("node_modules", [])
    ios_backups    = scan_result.get("ios_backups", [])
    xcode_archives = scan_result.get("xcode_archives", [])
    large_files    = scan_result.get("large_files", [])
    recordings     = scan_result.get("recordings", [])
    docker         = scan_result.get("docker", {})
    login_items    = scan_result.get("login_items", [])

    def sz(n): return _format_bytes(n)

    total_cache        = sum(cache_sizes.values())
    total_browser      = sum(browser_caches.values())
    total_node_modules = sum(i["size"] for i in node_modules)
    total_recordings   = sum(i["size"] for i in recordings)
    total_large        = sum(i["size"] for i in large_files)
    total_ios          = sum(i["size"] for i in ios_backups)
    total_xcode        = sum(i["size"] for i in xcode_archives)

    total_downloads  = sum(f["size"] for f in downloads)
    total_lang       = sum(f["size"] for f in language_files)
    total_mail       = sum(f["size"] for f in mail_attachments)

    recoverable = total_cache + total_browser + total_node_modules + total_recordings + trash["size"] + total_mail
    total_files = len(screenshots) + len(bad_photos) + len(duplicates) + len(downloads)

    total_junk = (total_cache + total_browser + total_node_modules + total_recordings
                  + trash["size"] + total_mail + total_xcode + total_ios
                  + total_large + total_downloads + total_lang)
    try:
        disk_total = shutil.disk_usage("/").total
        junk_pct = min(99, max(1, int(total_junk / disk_total * 100))) if disk_total else 5
    except OSError:
        junk_pct = 5

    clean_state = total_junk < 50 * 1024 * 1024  # < 50 MB = effectively clean

    # build thumbnails for image files
    def thumb_tag(p):
        if _is_image(p):
            b64 = _thumb_b64(p)
            if b64:
                return f'<img src="data:image/jpeg;base64,{b64}" class="thumb" data-fullpath="{p}" onclick="openLb(this.dataset.fullpath)" title="Preview">'
        ext = os.path.splitext(p)[1].lower()
        icon = {".pdf": "📄", ".zip": "🗜️", ".dmg": "💿", ".mp4": "🎬",
                ".mov": "🎬", ".pkg": "📦", ".app": "🖥️"}.get(ext, "📄")
        return f'<div class="thumb-ph">{icon}</div>'

    def _he(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def file_rows(paths, checkable=True, thumb_limit=50, default_checked=True, reveal=False):
        if not paths:
            return "<div class='empty-state'><span>✓</span><p>Nothing found</p></div>"
        rows = ""
        for i, p in enumerate(paths):
            name = os.path.basename(p)
            folder = os.path.dirname(p).replace(os.path.expanduser("~"), "~")
            try: size = sz(os.path.getsize(p))
            except OSError: size = "—"
            safe_p = _he(p)
            cb = f'<input type="checkbox" class="cb" value="{safe_p}" {"checked" if default_checked else ""}>' if checkable else ""
            thumb = thumb_tag(p) if i < thumb_limit else f'<div class="thumb-ph">📄</div>'
            reveal_btn = f'<button class="reveal-btn" onclick="revealInFinder(this.dataset.path)" data-path="{safe_p}">Show in Finder</button>' if reveal else ""
            rows += f"""<div class="file-row" data-path="{safe_p}">
              {cb}{thumb}
              <div class="file-info"><div class="file-name">{_he(name)}</div><div class="file-folder">{_he(folder)}</div></div>
              <div class="file-size">{size}</div>{reveal_btn}
            </div>"""
        return rows

    def dict_rows(items, checkable=True, show_date=False):
        if not items:
            return "<div class='empty-state'><span>✓</span><p>Nothing found</p></div>"
        rows = ""
        for item in items:
            p = item["path"]
            name = os.path.basename(p)
            folder = os.path.dirname(p).replace(os.path.expanduser("~"), "~")
            size = sz(item["size"])
            safe_p = _he(p)
            date = f'<div class="file-size" style="width:100px">{_fmt_date(item["mtime"])}</div>' if show_date else ""
            cb = f'<input type="checkbox" class="cb" value="{safe_p}" checked>' if checkable else ""
            rows += f"""<div class="file-row" data-path="{safe_p}">
              {cb}<div class="thumb-ph">📁</div>
              <div class="file-info"><div class="file-name">{_he(name)}</div><div class="file-folder">{_he(folder)}</div></div>
              {date}<div class="file-size">{size}</div>
            </div>"""
        return rows

    def cache_rows(sizes):
        if not sizes:
            return "<div class='empty-state'><span>✓</span><p>Nothing found</p></div>"
        rows = ""
        for d, s in sizes.items():
            short = d.replace(os.path.expanduser("~"), "~")
            rows += f"""<div class="file-row" data-path="{d}">
              <input type="checkbox" class="cb" value="{d}" checked>
              <div class="thumb-ph">🗑️</div>
              <div class="file-info"><div class="file-name" style="font-size:13px">{short}</div></div>
              <div class="file-size">{sz(s)}</div>
            </div>"""
        return rows

    def browser_rows(caches):
        if not caches:
            return "<div class='empty-state'><span>✓</span><p>No browser caches found</p></div>"
        icons = {"Chrome": "🌐", "Safari": "🧭", "Arc": "🌈", "Firefox": "🦊", "Brave": "🦁", "Edge": "🔷"}
        rows = ""
        for browser, size in caches.items():
            rows += f"""<div class="file-row">
              <div class="thumb-ph">{icons.get(browser, '🌐')}</div>
              <div class="file-info"><div class="file-name">{browser}</div></div>
              <div class="file-size">{sz(size)}</div>
            </div>"""
        return rows

    def download_rows(items):
        if not items:
            return "<div class='empty-state'><span>✓</span><p>Downloads folder is empty</p></div>"
        rows = ""
        for i, item in enumerate(items):
            p = item["path"]
            name = os.path.basename(p)
            folder = os.path.dirname(p).replace(os.path.expanduser("~"), "~")
            size = sz(item["size"])
            age = item["age_days"]
            if age <= 7:
                badge = f'<span class="age-badge age-new">{age}d ago</span>'
            elif age <= 30:
                badge = f'<span class="age-badge age-recent">{age}d ago</span>'
            else:
                badge = f'<span class="age-badge age-old">{age}d ago</span>'
            thumb = thumb_tag(p) if i < 50 else f'<div class="thumb-ph">📄</div>'
            checked = "" if age <= 7 else "checked"
            rows += f"""<div class="file-row" data-path="{p}">
              <input type="checkbox" class="cb" value="{p}" {checked}>{thumb}
              <div class="file-info"><div class="file-name">{name}</div><div class="file-folder">{folder}</div></div>
              {badge}<div class="file-size">{size}</div>
            </div>"""
        return rows

    def lang_rows(items):
        if not items:
            return "<div class='empty-state'><span>✓</span><p>No unused language files found</p></div>"
        rows = ""
        for item in items:
            p = item["path"]
            rows += f"""<div class="file-row" data-path="{p}">
              <input type="checkbox" class="cb" value="{p}" checked>
              <div class="thumb-ph">🌍</div>
              <div class="file-info"><div class="file-name">{item["lang"]}</div><div class="file-folder">{item["app"]}</div></div>
              <div class="file-size">{sz(item["size"])}</div>
            </div>"""
        return rows

    def mail_rows(items):
        if not items:
            return "<div class='empty-state'><span>✓</span><p>No mail attachments found</p></div>"
        rows = ""
        for item in items:
            p = item["path"]
            name = os.path.basename(p)
            folder = os.path.dirname(p).replace(os.path.expanduser("~"), "~")
            rows += f"""<div class="file-row" data-path="{p}">
              <input type="checkbox" class="cb" value="{p}" checked>
              <div class="thumb-ph">📎</div>
              <div class="file-info"><div class="file-name">{name}</div><div class="file-folder">{folder}</div></div>
              <div class="file-size">{sz(item["size"])}</div>
            </div>"""
        return rows

    def login_item_rows(items):
        if not items:
            return "<div class='empty-state'><span>✓</span><p>No login items found</p></div>"
        rows = ""
        for item in items:
            name = _he(item["name"])
            path = _he(item.get("path", ""))
            rows += f"""<div class="file-row" data-path="{name}">
              <input type="checkbox" class="cb" value="{name}">
              <div class="thumb-ph">🚀</div>
              <div class="file-info"><div class="file-name">{name}</div><div class="file-folder">{path}</div></div>
            </div>"""
        return rows

    sections_data = json.dumps({
        "screenshots":    screenshots,
        "bad_photos":     bad_photos,
        "duplicates":     duplicates,
        "downloads":      [f["path"] for f in downloads],
        "cache_dirs":     list(cache_sizes.keys()),
        "browser_dirs":   list(browser_caches.keys()),
        "node_modules":   [i["path"] for i in node_modules],
        "ios_backups":    [i["path"] for i in ios_backups],
        "xcode_archives": [i["path"] for i in xcode_archives],
        "recordings":     [r["path"] for r in recordings],
        "large_files":    [f["path"] for f in large_files],
        "language_files": [f["path"] for f in language_files],
        "mail_attachments": [f["path"] for f in mail_attachments],
        "login_items":    [i["name"] for i in login_items],
    }).replace("</", "<\\/")

    api = f"http://127.0.0.1:{port}" if port else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Sweep</title>
<script src="/assets/lucide.min.js"></script>
<style>
:root {{
  --sidebar-bg: #18181B;
  --sidebar-w: 224px;
  --accent: #FF6551;
  --accent-soft: rgba(255,101,81,.08);
  --text: #18181B;
  --text-2: #52525B;
  --surface: #FFFFFF;
  --bg: #F4F4F5;
  --border: rgba(0,0,0,.07);
  --radius: 14px;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif;
        background: var(--bg); color: var(--text); display: flex;
        min-height: 100vh; overflow: hidden; }}

/* ── Sidebar ── */
.sidebar {{ width: var(--sidebar-w); background: var(--sidebar-bg); flex-shrink: 0;
            display: flex; flex-direction: column; height: 100vh;
            position: fixed; top: 0; left: 0; overflow-y: auto; }}
.sidebar-logo {{ padding: 22px 16px 14px; display: flex; align-items: center; gap: 10px; }}
.logo-mark {{ width: 30px; height: 30px; background: var(--accent); border-radius: 8px;
               display: flex; align-items: center; justify-content: center; flex-shrink: 0; }}
.logo-name {{ font-size: 16px; font-weight: 800; color: #fff; letter-spacing: -.3px; }}
.sidebar-section {{ padding: 14px 16px 4px; font-size: 10px; font-weight: 700;
                     color: rgba(255,255,255,.2); letter-spacing: .8px; text-transform: uppercase; }}
.nav-item {{ display: flex; align-items: center; gap: 9px; padding: 8px 10px;
              border-radius: 9px; margin: 1px 8px; cursor: pointer;
              color: rgba(255,255,255,.45); font-size: 13px; font-weight: 500;
              transition: background .12s, color .12s; user-select: none; }}
.nav-item:hover {{ background: rgba(255,255,255,.06); color: rgba(255,255,255,.8); }}
.nav-item.active {{ background: var(--accent-soft); color: var(--accent); }}
.nav-icon {{ width: 18px; height: 18px; display: flex; align-items: center;
              justify-content: center; flex-shrink: 0; }}
.nav-item .label {{ flex: 1; }}
.nav-item .badge {{ background: rgba(255,255,255,.1); color: rgba(255,255,255,.4);
                     font-size: 10px; font-weight: 600; padding: 1px 6px;
                     border-radius: 99px; flex-shrink: 0; }}
.nav-item .badge.has-items {{ background: var(--accent); color: #fff; }}
.sidebar-bottom {{ margin-top: auto; padding: 14px; }}
.version-tag {{ font-size: 10px; color: rgba(255,255,255,.15); text-align: center; }}

/* ── Main ── */
.main {{ margin-left: var(--sidebar-w); width: calc(100vw - var(--sidebar-w)); height: 100vh; overflow-y: auto; overflow-x: hidden; }}

/* ── Views ── */
.view {{ display: none; }}
.view.active {{ display: block; }}

/* ── Dashboard hero ── */
.dash-hero {{ background: var(--surface); padding: 40px 40px 32px;
               border-bottom: 1px solid var(--border); }}
.dash-eyebrow {{ font-size: 11px; font-weight: 700; color: var(--accent);
                  letter-spacing: .8px; text-transform: uppercase; margin-bottom: 12px; }}
.dash-hero h1 {{ font-size: 36px; font-weight: 800; color: var(--text);
                  line-height: 1.1; margin-bottom: 6px; }}
.dash-hero h1 em {{ font-style: normal; color: var(--accent); }}
.dash-hero .sub {{ color: var(--text-2); font-size: 14px; margin-bottom: 24px; }}
.hero-pills {{ display: flex; gap: 10px; flex-wrap: wrap; }}
.hero-pill {{ display: flex; flex-direction: column; gap: 1px;
               background: var(--bg); border: 1.5px solid var(--border);
               border-radius: 12px; padding: 10px 14px; }}
.hero-pill .val {{ font-size: 19px; font-weight: 800; color: var(--text); }}
.hero-pill .lbl {{ font-size: 11px; color: var(--text-2); font-weight: 500;
                    text-transform: uppercase; letter-spacing: .3px; }}

/* ── Dashboard grid ── */
.dash-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
               gap: 12px; padding: 24px 40px; }}
.dash-card {{ background: var(--surface); border-radius: var(--radius); padding: 18px;
               cursor: pointer; border: 1.5px solid var(--border);
               transition: border-color .15s, box-shadow .15s; }}
.dash-card:hover {{ border-color: var(--accent); box-shadow: 0 4px 20px var(--accent-soft); }}
.card-icon-wrap {{ width: 36px; height: 36px; border-radius: 10px;
                    background: var(--accent-soft); display: flex;
                    align-items: center; justify-content: center;
                    color: var(--accent); margin-bottom: 14px; }}
.dash-card .card-count {{ font-size: 26px; font-weight: 800; color: var(--text); line-height: 1; }}
.dash-card .card-label {{ font-size: 12px; color: var(--text-2); margin-top: 3px; font-weight: 500; }}
.dash-card .card-size {{ font-size: 12px; font-weight: 700; color: var(--accent); margin-top: 8px; }}
.dash-card.zero {{ opacity: .3; cursor: default; pointer-events: none; }}

.clean-all-wrap {{ padding: 0 40px 40px; }}
.btn-clean-all {{ width: 100%; padding: 14px; border-radius: 12px; border: none;
                   background: var(--accent); color: #fff; font-size: 15px; font-weight: 700;
                   cursor: pointer; transition: opacity .15s;
                   box-shadow: 0 4px 16px rgba(255,101,81,.3); }}
.btn-clean-all:hover {{ opacity: .88; }}

/* ── Section header ── */
.sec-header {{ padding: 26px 40px 20px; border-bottom: 1px solid var(--border);
                background: var(--surface); display: flex; align-items: center; gap: 14px; }}
.sec-icon-wrap {{ width: 44px; height: 44px; border-radius: 12px; background: var(--accent-soft);
                   display: flex; align-items: center; justify-content: center;
                   color: var(--accent); flex-shrink: 0; font-size: 20px; }}
.sec-title h2 {{ font-size: 20px; font-weight: 800; color: var(--text); margin-bottom: 2px; }}
.sec-title p {{ font-size: 13px; color: var(--text-2); }}

/* ── Action bar ── */
.action-bar {{ display: flex; align-items: center; gap: 10px; padding: 10px 40px;
               background: var(--surface); border-bottom: 1px solid var(--border); }}
.select-all-btn {{ background: var(--bg); border: none; border-radius: 8px;
                    padding: 7px 14px; font-size: 13px; font-weight: 600;
                    cursor: pointer; color: var(--text); transition: background .12s; }}
.select-all-btn:hover {{ background: #E4E4E7; }}
.delete-btn {{ background: #FF3B30; border: none; border-radius: 8px;
                padding: 7px 18px; font-size: 13px; font-weight: 700; cursor: pointer;
                color: #fff; transition: opacity .15s; margin-left: auto; }}
.delete-btn:hover {{ opacity: .88; }}
.delete-btn:disabled {{ opacity: .35; cursor: default; }}
.sel-count {{ font-size: 13px; color: var(--text-2); }}

/* ── File list ── */
.file-list {{ padding: 16px 40px 40px; display: flex; flex-direction: column; gap: 1px; }}
.file-row {{ display: flex; align-items: center; gap: 12px; padding: 10px 14px;
              background: var(--surface); font-size: 14px; transition: background .1s; }}
.file-row:first-child {{ border-radius: var(--radius) var(--radius) 0 0; }}
.file-row:last-child {{ border-radius: 0 0 var(--radius) var(--radius); }}
.file-row:only-child {{ border-radius: var(--radius); }}
.file-row:hover {{ background: #FAFAFA; }}
.file-row.cleaned {{ opacity: .3; }}
.file-row.cleaned .file-name {{ text-decoration: line-through; }}
.thumb {{ width: 46px; height: 46px; object-fit: cover; border-radius: 8px; flex-shrink: 0;
           cursor: zoom-in; transition: transform .15s; border: 1px solid var(--border); }}
.thumb:hover {{ transform: scale(1.06); }}
.thumb-ph {{ width: 46px; height: 46px; border-radius: 8px; flex-shrink: 0;
              display: flex; align-items: center; justify-content: center;
              background: var(--bg); font-size: 20px; border: 1px solid var(--border); }}
.file-info {{ flex: 1; min-width: 0; }}
.file-name {{ font-weight: 500; white-space: nowrap; overflow: hidden;
               text-overflow: ellipsis; color: var(--text); }}
.file-folder {{ font-size: 12px; color: var(--text-2); margin-top: 1px;
                 white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.file-size {{ width: 78px; text-align: right; color: var(--text-2); font-size: 13px;
               flex-shrink: 0; font-weight: 500; }}
.cb {{ width: 16px; height: 16px; flex-shrink: 0; cursor: pointer; accent-color: var(--accent); }}
.empty-state {{ text-align: center; padding: 52px 20px; color: var(--text-2);
                 background: var(--surface); border-radius: var(--radius); }}
.empty-state p {{ font-size: 14px; font-weight: 500; }}
.warning-bar {{ background: #FFF8E1; border-left: 3px solid #FF9500; border-radius: 10px;
                 padding: 12px 16px; margin: 0 40px 4px; font-size: 13px; color: #7A5000; }}

/* ── Reveal btn ── */
.reveal-btn {{ background: none; border: 1.5px solid var(--border); color: var(--text-2);
               border-radius: 8px; padding: 5px 12px; font-size: 12px; font-weight: 600;
               cursor: pointer; flex-shrink: 0; white-space: nowrap; transition: all .12s; }}
.reveal-btn:hover {{ border-color: var(--accent); color: var(--accent); }}

/* ── Lightbox ── */
#lb {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,.88);
        backdrop-filter: blur(20px); z-index: 9999; align-items: center;
        justify-content: center; flex-direction: column; gap: 16px; cursor: zoom-out; }}
#lb.open {{ display: flex; }}
#lb img {{ max-width: 92vw; max-height: 84vh; border-radius: 14px;
            object-fit: contain; box-shadow: 0 32px 80px rgba(0,0,0,.7); cursor: default; }}
#lb-name {{ color: rgba(255,255,255,.5); font-size: 13px; }}
#lb-x {{ position: fixed; top: 18px; right: 22px; color: #fff; font-size: 22px;
           cursor: pointer; opacity: .55; background: none; border: none; }}
#lb-x:hover {{ opacity: 1; }}

/* ── Toast ── */
.toast {{ position: fixed; bottom: 28px; right: 28px; background: #18181B; color: #fff;
           padding: 12px 20px; border-radius: 12px; font-size: 14px; font-weight: 500;
           opacity: 0; transition: opacity .3s, transform .3s; transform: translateY(8px);
           box-shadow: 0 8px 30px rgba(0,0,0,.2); z-index: 9998; pointer-events: none; }}
.toast.show {{ opacity: 1; transform: translateY(0); }}

/* ── Confirm modal ── */
.modal-backdrop {{ display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,.6); backdrop-filter: blur(12px);
  z-index: 99999; align-items: center; justify-content: center; }}
.modal-backdrop.open {{ display: flex; }}
.modal-box {{ background: #1C1C1E; border: 1px solid rgba(255,255,255,.1);
  border-radius: 18px; padding: 28px 28px 22px; max-width: 360px; width: 90%;
  box-shadow: 0 24px 64px rgba(0,0,0,.6); }}
.modal-title {{ font-size: 17px; font-weight: 700; color: #F4F4F5; margin-bottom: 8px; }}
.modal-body {{ font-size: 14px; color: #A1A1AA; line-height: 1.55; margin-bottom: 22px; }}
.modal-actions {{ display: flex; gap: 10px; justify-content: flex-end; }}
.modal-cancel {{ padding: 9px 18px; border-radius: 10px;
  border: 1.5px solid rgba(255,255,255,.12); background: none;
  color: #A1A1AA; font-size: 14px; font-weight: 600; cursor: pointer; }}
.modal-cancel:hover {{ background: rgba(255,255,255,.06); }}
.modal-ok {{ padding: 9px 20px; border-radius: 10px; border: none;
  background: var(--accent); color: #fff; font-size: 14px;
  font-weight: 700; cursor: pointer; }}
.modal-ok:hover {{ opacity: .88; }}

/* ── Age badges ── */
.age-badge {{ font-size: 11px; font-weight: 700; padding: 2px 8px;
               border-radius: 99px; flex-shrink: 0; white-space: nowrap; }}
.age-new    {{ background: #D4F5E0; color: #1e7e34; }}
.age-recent {{ background: #FFF3CD; color: #856404; }}
.age-old    {{ background: #FDE8E8; color: #B91C1C; }}

/* ── Clean state ── */
.clean-screen {{ display: flex; flex-direction: column; align-items: center;
                  justify-content: center; padding: 80px 40px; text-align: center; }}
.clean-icon-wrap {{ width: 68px; height: 68px; border-radius: 18px;
                     background: var(--accent-soft); display: flex; align-items: center;
                     justify-content: center; color: var(--accent);
                     margin: 0 auto 20px; font-size: 32px; }}
.clean-screen h2 {{ font-size: 26px; font-weight: 800; color: var(--text); margin-bottom: 8px; }}
.clean-screen p {{ font-size: 15px; color: var(--text-2); margin-bottom: 24px; }}
.clean-screen .rescan-btn {{ background: var(--accent); color: #fff; border: none;
  border-radius: 12px; padding: 12px 28px; font-size: 15px; font-weight: 700;
  cursor: pointer; transition: opacity .15s; }}
.clean-screen .rescan-btn:hover {{ opacity: .88; }}

/* ── Dark mode ── */
@media (prefers-color-scheme: dark) {{
  :root {{ --text: #F4F4F5; --text-2: #A1A1AA; --surface: #1C1C1E; --bg: #000; --border: rgba(255,255,255,.08); }}
  .file-row:hover {{ background: #27272A; }}
  .thumb-ph {{ background: #27272A; }}
  .select-all-btn {{ background: #27272A; color: #F4F4F5; }}
  .select-all-btn:hover {{ background: #3F3F46; }}
  .dash-hero {{ background: #1C1C1E; }}
  .sec-header {{ background: #1C1C1E; }}
  .action-bar {{ background: #1C1C1E; }}
  .empty-state {{ background: #1C1C1E; }}
  .warning-bar {{ background: #2D1F00; color: #FFD60A; border-left-color: #FF9500; }}
  .toast {{ background: #F4F4F5; color: #18181B; }}
  .reveal-btn {{ border-color: rgba(255,255,255,.12); }}
  .hero-pill {{ background: rgba(255,255,255,.06); border-color: rgba(255,255,255,.1); }}
  .hero-pill .val {{ color: #F4F4F5; }}
}}
</style>
</head>
<body>

<div id="lb" onclick="if(event.target===this)closeLb()">
  <button id="lb-x" onclick="closeLb()">✕</button>
  <img id="lb-img" src="">
  <div id="lb-name"></div>
</div>
<div class="toast" id="toast"></div>

<!-- ── Confirm modal ────────────────────────────────────── -->
<div class="modal-backdrop" id="modal">
  <div class="modal-box">
    <div class="modal-title" id="modal-title"></div>
    <div class="modal-body" id="modal-body"></div>
    <div class="modal-actions">
      <button class="modal-cancel" id="modal-cancel">Cancel</button>
      <button class="modal-ok" id="modal-ok">Continue</button>
    </div>
  </div>
</div>

<!-- ── Sidebar ─────────────────────────────────────────── -->
<aside class="sidebar">
  <div class="sidebar-logo">
    <div class="logo-mark"><i data-lucide="wind"></i></div>
    <span class="logo-name">Sweep</span>
  </div>

  <div class="sidebar-section">Overview</div>
  <div class="nav-item active" onclick="nav('dashboard')">
    <span class="nav-icon"><i data-lucide="layout-dashboard"></i></span><span class="label">Dashboard</span>
  </div>

  <div class="sidebar-section">Files</div>
  <div class="nav-item" onclick="nav('screenshots')">
    <span class="nav-icon"><i data-lucide="image"></i></span><span class="label">Screenshots</span>
    <span class="badge {'has-items' if screenshots else ''}">{len(screenshots)}</span>
  </div>
  <div class="nav-item" onclick="nav('bad')">
    <span class="nav-icon"><i data-lucide="eye-off"></i></span><span class="label">Blurry &amp; Dark</span>
    <span class="badge {'has-items' if bad_photos else ''}">{len(bad_photos)}</span>
  </div>
  <div class="nav-item" onclick="nav('dupes')">
    <span class="nav-icon"><i data-lucide="copy"></i></span><span class="label">Duplicates</span>
    <span class="badge {'has-items' if duplicates else ''}">{len(duplicates)}</span>
  </div>
  <div class="nav-item" onclick="nav('downloads')">
    <span class="nav-icon"><i data-lucide="download"></i></span><span class="label">Downloads</span>
    <span class="badge {'has-items' if downloads else ''}">{len(downloads)}</span>
  </div>
  <div class="nav-item" onclick="nav('mail')">
    <span class="nav-icon"><i data-lucide="paperclip"></i></span><span class="label">Mail Attachments</span>
    <span class="badge {'has-items' if mail_attachments else ''}">{len(mail_attachments)}</span>
  </div>

  <div class="sidebar-section">Caches</div>
  <div class="nav-item" onclick="nav('browser')">
    <span class="nav-icon"><i data-lucide="globe"></i></span><span class="label">Browser</span>
    <span class="badge {'has-items' if browser_caches else ''}">{sz(total_browser) if total_browser else '0 B'}</span>
  </div>
  <div class="nav-item" onclick="nav('nm')">
    <span class="nav-icon"><i data-lucide="package"></i></span><span class="label">node_modules</span>
    <span class="badge {'has-items' if node_modules else ''}">{sz(total_node_modules) if node_modules else '0 B'}</span>
  </div>
  <div class="nav-item" onclick="nav('cache')">
    <span class="nav-icon"><i data-lucide="database"></i></span><span class="label">Dev Cache</span>
    <span class="badge {'has-items' if cache_sizes else ''}">{sz(total_cache) if total_cache else '0 B'}</span>
  </div>

  <div class="sidebar-section">System</div>
  <div class="nav-item" onclick="nav('login')">
    <span class="nav-icon"><i data-lucide="rocket"></i></span><span class="label">Login Items</span>
    <span class="badge {'has-items' if login_items else ''}">{len(login_items)}</span>
  </div>
  <div class="nav-item" onclick="nav('docker')">
    <span class="nav-icon"><i data-lucide="box"></i></span><span class="label">Docker</span>
    <span class="badge {'has-items' if docker.get('available') else ''}">{'on' if docker.get('available') else 'off'}</span>
  </div>
  <div class="nav-item" onclick="nav('ios')">
    <span class="nav-icon"><i data-lucide="smartphone"></i></span><span class="label">iOS Backups</span>
    <span class="badge {'has-items' if ios_backups else ''}">{len(ios_backups)}</span>
  </div>
  <div class="nav-item" onclick="nav('xcode')">
    <span class="nav-icon"><i data-lucide="cpu"></i></span><span class="label">Xcode</span>
    <span class="badge {'has-items' if xcode_archives else ''}">{len(xcode_archives)}</span>
  </div>
  <div class="nav-item" onclick="nav('rec')">
    <span class="nav-icon"><i data-lucide="video"></i></span><span class="label">Recordings</span>
    <span class="badge {'has-items' if recordings else ''}">{len(recordings)}</span>
  </div>
  <div class="nav-item" onclick="nav('large')">
    <span class="nav-icon"><i data-lucide="hard-drive"></i></span><span class="label">Large Files</span>
    <span class="badge {'has-items' if large_files else ''}">{len(large_files)}</span>
  </div>
  <div class="nav-item" onclick="nav('lang')">
    <span class="nav-icon"><i data-lucide="languages"></i></span><span class="label">Language Files</span>
    <span class="badge {'has-items' if language_files else ''}">{'300+' if len(language_files) >= 300 else len(language_files)}</span>
  </div>
  <div class="nav-item" onclick="nav('trash')">
    <span class="nav-icon"><i data-lucide="trash-2"></i></span><span class="label">Trash</span>
    <span class="badge {'has-items' if trash['size'] else ''}">{sz(trash['size']) if trash['size'] else '0 B'}</span>
  </div>
  <div class="sidebar-bottom">
    <button onclick="rescan()" id="rescan-btn" style="width:100%;padding:9px;border-radius:9px;border:none;
      background:rgba(255,255,255,.06);color:rgba(255,255,255,.5);font-size:12px;font-weight:600;
      cursor:pointer;margin-bottom:10px;display:flex;align-items:center;justify-content:center;gap:6px;">
      <i data-lucide="refresh-cw" style="width:13px;height:13px;"></i> Scan Again
    </button>
    <div class="version-tag">Sweep v{__version__}</div>
  </div>
</aside>

<!-- ── Main ──────────────────────────────────────────────── -->
<main class="main">

  <!-- Dashboard -->
  <div class="view active" id="view-dashboard">
    <div class="dash-hero">
      <div class="dash-eyebrow">Scan Complete</div>
      <h1><em>{sz(recoverable)}</em> ready to clear</h1>
      <p class="sub">{total_files} junk files found across your Mac</p>
      <div class="hero-pills">
        <div class="hero-pill">
          <div class="val">{sz(total_cache + total_browser)}</div>
          <div class="lbl">Caches</div>
        </div>
        <div class="hero-pill">
          <div class="val">{total_files}</div>
          <div class="lbl">Files</div>
        </div>
        <div class="hero-pill">
          <div class="val">{sz(trash["size"])}</div>
          <div class="lbl">Trash</div>
        </div>
      </div>
    </div>

    {'<div class="clean-screen"><div class="clean-icon-wrap">✨</div><h2>Your Mac is spotless!</h2><p>Nothing significant found. Come back in a few days.</p><button class="rescan-btn" onclick="rescan()">Scan Again</button></div>' if clean_state else ''}
    <div class="dash-grid" {'style="display:none"' if clean_state else ''}>
      <div class="dash-card {'zero' if not screenshots else ''}" onclick="nav('screenshots')">
        <div class="card-icon-wrap"><i data-lucide="image"></i></div>
        <div class="card-count">{len(screenshots)}</div>
        <div class="card-label">Screenshots</div>
        <div class="card-size">{sz(sum(os.path.getsize(p) for p in screenshots if os.path.exists(p)))}</div>
      </div>
      <div class="dash-card {'zero' if not bad_photos else ''}" onclick="nav('bad')">
        <div class="card-icon-wrap"><i data-lucide="eye-off"></i></div>
        <div class="card-count">{len(bad_photos)}</div>
        <div class="card-label">Blurry &amp; Dark</div>
        <div class="card-size">{sz(sum(os.path.getsize(p) for p in bad_photos if os.path.exists(p)))}</div>
      </div>
      <div class="dash-card {'zero' if not duplicates else ''}" onclick="nav('dupes')">
        <div class="card-icon-wrap"><i data-lucide="copy"></i></div>
        <div class="card-count">{len(duplicates)}</div>
        <div class="card-label">Duplicates</div>
        <div class="card-size">{sz(sum(os.path.getsize(p) for p in duplicates if os.path.exists(p)))}</div>
      </div>
      <div class="dash-card {'zero' if not downloads else ''}" onclick="nav('downloads')">
        <div class="card-icon-wrap"><i data-lucide="download"></i></div>
        <div class="card-count">{len(downloads)}</div>
        <div class="card-label">Downloads</div>
        <div class="card-size">{sz(total_downloads)}</div>
      </div>
      <div class="dash-card {'zero' if not total_cache else ''}" onclick="nav('cache')">
        <div class="card-icon-wrap"><i data-lucide="database"></i></div>
        <div class="card-count">{sz(total_cache)}</div>
        <div class="card-label">Dev Cache</div>
        <div class="card-size">{len(cache_sizes)} dirs</div>
      </div>
      <div class="dash-card {'zero' if not total_browser else ''}" onclick="nav('browser')">
        <div class="card-icon-wrap"><i data-lucide="globe"></i></div>
        <div class="card-count">{sz(total_browser)}</div>
        <div class="card-label">Browser Cache</div>
        <div class="card-size">{len(browser_caches)} browsers</div>
      </div>
      <div class="dash-card {'zero' if not node_modules else ''}" onclick="nav('nm')">
        <div class="card-icon-wrap"><i data-lucide="package"></i></div>
        <div class="card-count">{sz(total_node_modules)}</div>
        <div class="card-label">node_modules</div>
        <div class="card-size">{len(node_modules)} folders</div>
      </div>
      <div class="dash-card {'zero' if not large_files else ''}" onclick="nav('large')">
        <div class="card-icon-wrap"><i data-lucide="hard-drive"></i></div>
        <div class="card-count">{len(large_files)}</div>
        <div class="card-label">Large Files</div>
        <div class="card-size">{sz(total_large)}</div>
      </div>
      <div class="dash-card {'zero' if not login_items else ''}" onclick="nav('login')">
        <div class="card-icon-wrap"><i data-lucide="rocket"></i></div>
        <div class="card-count">{len(login_items)}</div>
        <div class="card-label">Login Items</div>
        <div class="card-size">startup apps</div>
      </div>
    </div>

    <div class="clean-all-wrap" {'style="display:none"' if clean_state else ''}>
      <button class="btn-clean-all" onclick="confirmCleanAll()">Clean Everything</button>
    </div>
  </div>

  <!-- Screenshots -->
  <div class="view" id="view-screenshots">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="image"></i></div>
      <div class="sec-title"><h2>Screenshots</h2><p>{len(screenshots)} files on Desktop &amp; Downloads</p></div>
    </div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('screenshots')">Select All</button>
      <span class="sel-count" id="cnt-screenshots"></span>
      <button class="delete-btn" onclick="cleanFiles('screenshots', '/clean/files')">Move to Bin</button>
    </div>
    <div class="file-list">{file_rows(screenshots)}</div>
  </div>

  <!-- Bad photos -->
  <div class="view" id="view-bad">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="eye-off"></i></div>
      <div class="sec-title"><h2>Blurry &amp; Dark Photos</h2><p>{len(bad_photos)} photos that may not be worth keeping</p></div>
    </div>
    <div class="warning-bar">⚠️ AI detection only — it can make mistakes. Review each photo carefully. All unchecked by default.</div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('bad')">Select All</button>
      <span class="sel-count" id="cnt-bad"></span>
      <button class="delete-btn" onclick="cleanFiles('bad', '/clean/files')">Move to Bin</button>
    </div>
    <div class="file-list">{file_rows(bad_photos, default_checked=False)}</div>
  </div>

  <!-- Duplicates -->
  <div class="view" id="view-dupes">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="copy"></i></div>
      <div class="sec-title"><h2>Duplicate Photos</h2><p>{len(duplicates)} duplicates — originals are kept</p></div>
    </div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('dupes')">Select All</button>
      <span class="sel-count" id="cnt-dupes"></span>
      <button class="delete-btn" onclick="cleanFiles('dupes', '/clean/files')">Move to Bin</button>
    </div>
    <div class="file-list">{file_rows(duplicates)}</div>
  </div>

  <!-- Downloads -->
  <div class="view" id="view-downloads">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="download"></i></div>
      <div class="sec-title"><h2>Downloads</h2><p>{len(downloads)} files · {sz(total_downloads)} · green = new, red = 30d+ old</p></div>
    </div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('downloads')">Select All</button>
      <span class="sel-count" id="cnt-downloads"></span>
      <button class="delete-btn" onclick="cleanFiles('downloads', '/clean/files')">Move to Bin</button>
    </div>
    <div class="file-list">{download_rows(downloads)}</div>
  </div>

  <!-- Browser caches -->
  <div class="view" id="view-browser">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="globe"></i></div>
      <div class="sec-title"><h2>Browser Caches</h2><p>{sz(total_browser)} across {len(browser_caches)} browser(s)</p></div>
    </div>
    <div class="action-bar">
      <button class="delete-btn" onclick="cleanBrowserCaches()" style="margin-left:0">Clear All Browser Caches</button>
    </div>
    <div class="file-list">{browser_rows(browser_caches)}</div>
  </div>

  <!-- node_modules -->
  <div class="view" id="view-nm">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="package"></i></div>
      <div class="sec-title"><h2>node_modules</h2><p>{len(node_modules)} folders unused 30+ days · {sz(total_node_modules)}</p></div>
    </div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('nm')">Select All</button>
      <span class="sel-count" id="cnt-nm"></span>
      <button class="delete-btn" onclick="cleanNodeModules()">Delete Selected</button>
    </div>
    <div class="file-list">{dict_rows(node_modules, show_date=True)}</div>
  </div>

  <!-- Dev caches -->
  <div class="view" id="view-cache">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="database"></i></div>
      <div class="sec-title"><h2>Dev Caches</h2><p>{sz(total_cache)} across {len(cache_sizes)} cache directories</p></div>
    </div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('cache')">Select All</button>
      <span class="sel-count" id="cnt-cache"></span>
      <button class="delete-btn" onclick="cleanCaches()">Clear Selected</button>
    </div>
    <div class="file-list">{cache_rows(cache_sizes)}</div>
  </div>

  <!-- Docker -->
  <div class="view" id="view-docker">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="box"></i></div>
      <div class="sec-title"><h2>Docker</h2><p>{'Running — prune to free space' if docker.get('available') else 'Not running or not installed'}</p></div>
    </div>
    <div class="action-bar">
      {'<button class="delete-btn" onclick="pruneDocker()" style="margin-left:0">docker system prune</button>' if docker.get('available') else '<span class="sel-count">Docker is not running</span>'}
    </div>
    <div class="file-list">
      {''.join(f'<div class="file-row"><div class="thumb-ph">📦</div><div class="file-info"><div class="file-name">{r["type"]}</div><div class="file-folder">Total: {r["size"]}</div></div><div class="file-size">{r["reclaimable"]} free</div></div>' for r in docker.get("rows", [])) or "<div class='empty-state'><p>Docker not running</p></div>"}
    </div>
  </div>

  <!-- iOS Backups -->
  <div class="view" id="view-ios">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="smartphone"></i></div>
      <div class="sec-title"><h2>iOS Backups</h2><p>{len(ios_backups)} backup(s) · {sz(total_ios)}</p></div>
    </div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('ios')">Select All</button>
      <span class="sel-count" id="cnt-ios"></span>
      <button class="delete-btn" onclick="cleanFiles('ios', '/clean/files')">Move to Bin</button>
    </div>
    {'<div class="warning-bar">⚠️ Only delete old backups you no longer need.</div>' if ios_backups else ''}
    <div class="file-list">{dict_rows(ios_backups, show_date=True)}</div>
  </div>

  <!-- Xcode Archives -->
  <div class="view" id="view-xcode">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="cpu"></i></div>
      <div class="sec-title"><h2>Xcode Archives</h2><p>{len(xcode_archives)} archive(s) · {sz(total_xcode)}</p></div>
    </div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('xcode')">Select All</button>
      <span class="sel-count" id="cnt-xcode"></span>
      <button class="delete-btn" onclick="cleanFiles('xcode', '/clean/files')">Move to Bin</button>
    </div>
    <div class="file-list">{dict_rows(xcode_archives, show_date=True)}</div>
  </div>

  <!-- Recordings -->
  <div class="view" id="view-rec">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="video"></i></div>
      <div class="sec-title"><h2>Recordings</h2><p>{len(recordings)} video file(s) · {sz(total_recordings)}</p></div>
    </div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('rec')">Select All</button>
      <span class="sel-count" id="cnt-rec"></span>
      <button class="delete-btn" onclick="cleanFiles('rec', '/clean/files')">Move to Bin</button>
    </div>
    <div class="file-list">{file_rows([r["path"] for r in recordings])}</div>
  </div>

  <!-- Large files -->
  <div class="view" id="view-large">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="hard-drive"></i></div>
      <div class="sec-title"><h2>Large Files</h2><p>{len(large_files)} files over 500 MB · {sz(total_large)} total</p></div>
    </div>
    {'<div class="warning-bar">These are your biggest files — review in Finder and decide what to keep.</div>' if large_files else ''}
    <div class="file-list">{file_rows([f["path"] for f in large_files], checkable=False, reveal=True)}</div>
  </div>

  <!-- Mail Attachments -->
  <div class="view" id="view-mail">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="paperclip"></i></div>
      <div class="sec-title"><h2>Mail Attachments</h2><p>{len(mail_attachments)} attachment(s) · {sz(total_mail)}</p></div>
    </div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('mail')">Select All</button>
      <span class="sel-count" id="cnt-mail"></span>
      <button class="delete-btn" onclick="cleanFiles('mail', '/clean/files')">Move to Bin</button>
    </div>
    <div class="file-list">{mail_rows(mail_attachments)}</div>
  </div>

  <!-- Language Files -->
  <div class="view" id="view-lang">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="languages"></i></div>
      <div class="sec-title"><h2>Language Files</h2><p>{'300+' if len(language_files) >= 300 else len(language_files)} unused packs inside app bundles · {sz(total_lang)}</p></div>
    </div>
    <div class="warning-bar">⚠️ These files live inside app bundles. Restore them anytime by reinstalling the app.</div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('lang')">Select All</button>
      <span class="sel-count" id="cnt-lang"></span>
      <button class="delete-btn" onclick="cleanLangFiles()">Delete Selected</button>
    </div>
    <div class="file-list">{lang_rows(language_files)}</div>
  </div>

  <!-- Login Items -->
  <div class="view" id="view-login">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="rocket"></i></div>
      <div class="sec-title"><h2>Login Items</h2><p>{len(login_items)} app(s) launch automatically at startup</p></div>
    </div>
    <div class="warning-bar">ℹ️ Removing an item only stops it auto-launching — the app itself is not deleted.</div>
    <div class="action-bar">
      <button class="select-all-btn" onclick="toggleAll('login')">Select All</button>
      <span class="sel-count" id="cnt-login"></span>
      <button class="delete-btn" onclick="cleanLoginItems()">Remove Selected</button>
    </div>
    <div class="file-list">{login_item_rows(login_items)}</div>
  </div>

  <!-- Trash -->
  <div class="view" id="view-trash">
    <div class="sec-header">
      <div class="sec-icon-wrap"><i data-lucide="trash-2"></i></div>
      <div class="sec-title"><h2>Trash</h2><p>{sz(trash['size'])} waiting to be freed</p></div>
    </div>
    <div class="action-bar">
      <button class="delete-btn" onclick="emptyTrash()" style="margin-left:0">Empty Trash</button>
    </div>
    <div class="file-list">
      {'<div class="file-row"><div class="thumb-ph">🗑️</div><div class="file-info"><div class="file-name">Trash</div><div class="file-folder">~/.Trash</div></div><div class="file-size">' + sz(trash["size"]) + '</div></div>' if trash["size"] else "<div class='empty-state'><p>Trash is empty</p></div>"}
    </div>
  </div>


</main>

<script>
const API = "{api}";
const DATA = {sections_data};

// ── Navigation ────────────────────────────────────────────
const _NAV_LABELS = {{
  dashboard:'Dashboard', screenshots:'Screenshots', bad:'Blurry & Dark',
  dupes:'Duplicates', downloads:'Downloads', mail:'Mail Attachments',
  browser:'Browser Cache', nm:'node_modules', cache:'Dev Cache',
  login:'Login Items', docker:'Docker', ios:'iOS Backups', xcode:'Xcode Archives',
  rec:'Recordings', large:'Large Files', lang:'Language Files', trash:'Trash'
}};
function nav(id) {{
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('view-' + id).classList.add('active');
  document.querySelector(`[onclick="nav('${{id}}')"]`)?.classList.add('active');
  document.querySelector('.main').scrollTop = 0;
  document.title = 'Sweep — ' + (_NAV_LABELS[id] || id);
}}

// ── Lightbox ──────────────────────────────────────────────
function openLb(path) {{
  document.getElementById('lb-img').src = 'file://' + path;
  document.getElementById('lb-name').textContent = path.split('/').pop();
  document.getElementById('lb').classList.add('open');
}}
function closeLb() {{ document.getElementById('lb').classList.remove('open'); }}
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeLb(); }});

// ── Toast ─────────────────────────────────────────────────
function toast(msg, ok=true) {{
  const el = document.getElementById('toast');
  el.textContent = (ok ? '✅ ' : '❌ ') + msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3500);
}}

// ── Helpers ───────────────────────────────────────────────
function getChecked(secId) {{
  return [...document.querySelectorAll(`#view-${{secId}} .cb:checked`)].map(c => c.value);
}}
function toggleAll(secId) {{
  const cbs = document.querySelectorAll(`#view-${{secId}} .cb`);
  const all = [...cbs].every(c => c.checked);
  cbs.forEach(c => c.checked = !all);
  updateCount(secId);
}}
function updateCount(secId) {{
  const checked = document.querySelectorAll(`#view-${{secId}} .cb:checked`).length;
  const total = document.querySelectorAll(`#view-${{secId}} .cb`).length;
  const el = document.getElementById('cnt-' + secId);
  if (el) el.textContent = total > 0 ? `${{checked}} of ${{total}} selected` : '';
}}
function markCleaned(secId) {{
  document.querySelectorAll(`#view-${{secId}} .cb:checked`).forEach(cb => {{
    cb.closest('.file-row').classList.add('cleaned');
    cb.checked = false;
  }});
  updateCount(secId);
}}
async function post(endpoint, body) {{
  try {{
    const r = await fetch(API + endpoint, {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(body)
    }});
    return r.json();
  }} catch(e) {{
    toast('Connection error — is Sweep running?', false);
    return {{ok: 0, fail: 0}};
  }}
}}
document.addEventListener('change', e => {{
  if (e.target.classList.contains('cb')) {{
    const view = e.target.closest('.view');
    if (view) updateCount(view.id.replace('view-', ''));
  }}
}});

// ── Clean actions ─────────────────────────────────────────
function hintRescan() {{
  setTimeout(rescan, 1200);
}}
async function cleanFiles(secId, endpoint) {{
  const paths = getChecked(secId);
  if (!paths.length) {{ toast('Nothing selected', false); return; }}
  const r = await post(endpoint, {{paths}});
  markCleaned(secId);
  toast(`Moved ${{r.ok}} item(s) to Bin${{r.fail ? ' · ' + r.fail + ' failed' : ''}} — rescanning…`);
  hintRescan();
}}
async function cleanCaches() {{
  const dirs = getChecked('cache');
  if (!dirs.length) {{ toast('Nothing selected', false); return; }}
  const r = await post('/clean/caches', {{dirs}});
  markCleaned('cache');
  toast(`Cleared ${{r.ok}} cache dir(s)${{r.fail ? ' · ' + r.fail + ' failed' : ''}} — rescanning…`);
  hintRescan();
}}
async function cleanNodeModules() {{
  const paths = getChecked('nm');
  if (!paths.length) {{ toast('Nothing selected', false); return; }}
  const r = await post('/clean/node_modules', {{paths}});
  markCleaned('nm');
  toast(`Moved ${{r.ok}} node_modules folder(s) to Bin — rescanning…`);
  hintRescan();
}}
async function cleanBrowserCaches() {{
  const r = await post('/clean/caches', {{dirs: DATA.browser_dirs}});
  toast(`Moved ${{r.ok}} browser cache(s) to Bin — rescanning…`);
  hintRescan();
}}
async function pruneDocker() {{
  toast('Running docker system prune…');
  const r = await post('/clean/docker', {{}});
  toast(r.success ? 'Docker pruned ✓ — rescanning…' : 'Docker prune failed', r.success);
  if (r.success) hintRescan();
}}
async function cleanLangFiles() {{
  const paths = getChecked('lang');
  if (!paths.length) {{ toast('Nothing selected', false); return; }}
  const r = await post('/clean/lang', {{paths}});
  markCleaned('lang');
  toast(`Deleted ${{r.ok}} language pack(s)${{r.fail ? ' · ' + r.fail + ' failed' : ''}} — rescanning…`);
  hintRescan();
}}
async function cleanLoginItems() {{
  const names = getChecked('login');
  if (!names.length) {{ toast('Nothing selected', false); return; }}
  const r = await post('/clean/login_items', {{names}});
  markCleaned('login');
  toast(`Removed ${{r.ok}} login item(s) from startup${{r.fail ? ' · ' + r.fail + ' failed' : ''}}`);
}}
async function emptyTrash() {{
  toast('Emptying Trash…');
  const r = await post('/clean/trash', {{}});
  toast(r.success ? 'Trash emptied ✓ — rescanning…' : 'Could not empty Trash', r.success);
  if (r.success) hintRescan();
}}
function showConfirm(title, body, onOk) {{
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').textContent = body;
  const modal = document.getElementById('modal');
  modal.classList.add('open');
  document.getElementById('modal-ok').onclick = () => {{ modal.classList.remove('open'); onOk(); }};
  document.getElementById('modal-cancel').onclick = () => modal.classList.remove('open');
}}
function confirmCleanAll() {{
  showConfirm(
    'Clean Everything?',
    'Moves all found files to the Bin and clears all caches. You can recover them from Trash.',
    cleanAll
  );
}}
async function cleanAll() {{
  const cleanBtn = document.querySelector('.btn-clean-all');
  if (cleanBtn) {{ cleanBtn.disabled = true; cleanBtn.textContent = '⏳ Cleaning…'; }}

  // Respect checkboxes in every section — only delete what's checked
  const files = [
    ...getChecked('screenshots'), ...getChecked('bad'),
    ...getChecked('dupes'), ...getChecked('downloads'),
    ...getChecked('ios'), ...getChecked('xcode'),
    ...getChecked('rec'), ...getChecked('mail'),
  ];
  let total = 0;
  if (files.length) {{ const r = await post('/clean/files', {{paths: files}}); total += r.ok; }}
  const cacheDirs = getChecked('cache');
  if (cacheDirs.length) {{ const r = await post('/clean/caches', {{dirs: cacheDirs}}); total += r.ok; }}
  const nmPaths = getChecked('nm');
  if (nmPaths.length) {{ const r = await post('/clean/node_modules', {{paths: nmPaths}}); total += r.ok; }}
  const langPaths = getChecked('lang');
  if (langPaths.length) {{ const r = await post('/clean/lang', {{paths: langPaths}}); total += r.ok; }}

  // Immediately zero out the dashboard so it looks clean right away
  document.querySelectorAll('.card-count').forEach(el => el.textContent = '0');
  document.querySelectorAll('.card-size').forEach(el => el.textContent = '—');
  document.querySelectorAll('.dash-card').forEach(el => el.classList.add('zero'));
  const heroTitle = document.querySelector('.dash-hero h1');
  if (heroTitle) heroTitle.innerHTML = '<em>0 B</em> ready to clear';
  const heroSub = document.querySelector('.dash-hero .sub');
  if (heroSub) heroSub.textContent = 'Rescanning…';

  document.querySelectorAll('.file-row').forEach(r => r.classList.add('cleaned'));
  if (cleanBtn) cleanBtn.textContent = 'Rescanning…';
  toast(`Cleaned ${{total}} item(s) — rescanning your Mac… 🎉`);
  // Bypass rescan-btn disabled check — always trigger a fresh scan after Clean Everything
  await post('/rescan', {{}});
  window.location.href = '/loading';
}}

async function revealInFinder(path) {{
  await post('/reveal', {{path}});
}}

// ── Scan Again ────────────────────────────────────────────
async function rescan() {{
  const btn = document.getElementById('rescan-btn');
  if (btn && btn.disabled) return;
  if (btn) btn.disabled = true;
  await post('/rescan', {{}});
  window.location.href = '/loading';
}}

// ── Init Lucide icons ─────────────────────────────────────
window.addEventListener('load', () => {{ lucide.createIcons(); }});
</script>
</body>
</html>"""
