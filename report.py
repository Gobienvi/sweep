import base64
import json
import os
import subprocess
import tempfile
import time
from io import BytesIO

from PIL import Image


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
            img.thumbnail((80, 80))
            buf = BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=75)
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _is_image(path: str) -> bool:
    return path.lower().endswith((".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"))


def _file_rows(paths: list[str], checkable: bool = True, show_thumb: bool = False) -> str:
    if not paths:
        return "<p class='empty'>None found ✓</p>"
    rows = ""
    for p in paths:
        name = os.path.basename(p)
        folder = os.path.dirname(p)
        try:
            size = _format_bytes(os.path.getsize(p))
        except OSError:
            size = "—"

        thumb_html = ""
        if show_thumb and _is_image(p):
            b64 = _thumb_b64(p)
            if b64:
                thumb_html = f'<img src="data:image/jpeg;base64,{b64}" class="thumb" data-fullpath="{p}" onclick="openFile(this.dataset.fullpath)" title="Click to preview">'
            else:
                thumb_html = '<div class="thumb-placeholder">🖼️</div>'
        elif show_thumb:
            ext = os.path.splitext(name)[1].lower()
            icon = {"pdf": "📄", ".zip": "🗜️", ".mp4": "🎬", ".mov": "🎬"}.get(ext, "📄")
            thumb_html = f'<div class="thumb-placeholder">{icon}</div>'

        cb = f'<input type="checkbox" class="file-cb" value="{p}" checked>' if checkable else ""
        rows += f"""<div class="row" data-path="{p}">
            {cb}
            {thumb_html}
            <div class="name" title="{p}">{name}</div>
            <div class="folder">{folder}</div>
            <div class="size">{size}</div>
        </div>"""
    return rows


def _dict_rows(items: list[dict], checkable: bool = True, show_date: bool = False) -> str:
    if not items:
        return "<p class='empty'>None found ✓</p>"
    rows = ""
    for item in items:
        p = item["path"]
        name = os.path.basename(p)
        folder = os.path.dirname(p)
        size = _format_bytes(item["size"])
        date_cell = f'<div class="size">{_fmt_date(item["mtime"])}</div>' if show_date else ""
        cb = f'<input type="checkbox" class="file-cb" value="{p}" checked>' if checkable else ""
        rows += f"""<div class="row" data-path="{p}">
            {cb}
            <div class="name" title="{p}">{name}</div>
            <div class="folder">{folder}</div>
            {date_cell}
            <div class="size">{size}</div>
        </div>"""
    return rows


def _browser_rows(caches: dict[str, int]) -> str:
    if not caches:
        return "<p class='empty'>None found ✓</p>"
    rows = ""
    for browser, size in caches.items():
        rows += f"""<div class="row">
            <div class="name">{browser}</div>
            <div class="folder"></div>
            <div class="size">{_format_bytes(size)}</div>
        </div>"""
    return rows


def _cache_rows(cache_sizes: dict[str, int]) -> str:
    if not cache_sizes:
        return "<p class='empty'>None found ✓</p>"
    rows = ""
    for d, s in cache_sizes.items():
        rows += f"""<div class="row">
            <input type="checkbox" class="file-cb" value="{d}" checked>
            <div class="name" style="flex:3" title="{d}">{d}</div>
            <div class="size">{_format_bytes(s)}</div>
        </div>"""
    return rows


def _docker_rows(docker: dict) -> str:
    if not docker.get("available"):
        return "<p class='empty'>Docker not running</p>"
    rows = docker.get("rows", [])
    if not rows:
        return "<p class='empty'>Docker clean ✓</p>"
    html = ""
    for r in rows:
        html += f"""<div class="row">
            <div class="name">{r['type']}</div>
            <div class="folder">{r['size']}</div>
            <div class="size">{r['reclaimable']}</div>
        </div>"""
    return html


def open_loading_page(port: int) -> None:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Sweep — Scanning…</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif;
         background: #f5f5f7; color: #1d1d1f;
         display: flex; align-items: center; justify-content: center;
         min-height: 100vh; flex-direction: column; gap: 24px; }}
  .spinner {{ width: 52px; height: 52px; border: 4px solid #e0e0e5;
               border-top-color: #007aff; border-radius: 50%;
               animation: spin .8s linear infinite; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  h2 {{ font-size: 22px; font-weight: 600; }}
  .step {{ font-size: 15px; color: #6e6e73; min-height: 22px; }}
  .dots span {{ animation: blink 1.2s infinite; display: inline-block; }}
  .dots span:nth-child(2) {{ animation-delay: .2s; }}
  .dots span:nth-child(3) {{ animation-delay: .4s; }}
  @keyframes blink {{ 0%,80%,100% {{ opacity:0 }} 40% {{ opacity:1 }} }}
</style>
</head>
<body>
<div class="spinner"></div>
<h2>🧹 Scanning your Mac<span class="dots"><span>.</span><span>.</span><span>.</span></span></h2>
<div class="step" id="step">Starting scan…</div>
<script>
async function poll() {{
  try {{
    const r = await fetch('http://127.0.0.1:{port}/status');
    const d = await r.json();
    document.getElementById('step').textContent = d.step || 'Scanning…';
    if (d.ready) {{
      window.location.href = 'http://127.0.0.1:{port}/report';
      return;
    }}
  }} catch(e) {{}}
  setTimeout(poll, 800);
}}
poll();
</script>
</body>
</html>"""
    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", prefix="sweep_loading_", delete=False, mode="w"
    )
    tmp.write(html)
    tmp.close()
    subprocess.run(["open", tmp.name])


def build_report_html(scan_result: dict, port: int = 0) -> str:
    """Build and return the report HTML string (does not open browser)."""
    return _build_html(scan_result, port)


def _build_html(scan_result: dict, port: int = 0) -> str:
    screenshots    = scan_result.get("screenshots", [])
    bad_photos     = scan_result.get("bad_photos", [])
    duplicates     = scan_result.get("duplicates", [])
    old_downloads  = scan_result.get("old_downloads", [])
    cache_sizes    = scan_result.get("cache_sizes", {})
    browser_caches = scan_result.get("browser_caches", {})
    node_modules   = scan_result.get("node_modules", [])
    ios_backups    = scan_result.get("ios_backups", [])
    xcode_archives = scan_result.get("xcode_archives", [])
    large_files    = scan_result.get("large_files", [])
    recordings     = scan_result.get("recordings", [])
    docker         = scan_result.get("docker", {})

    total_cache        = sum(cache_sizes.values())
    total_browser      = sum(browser_caches.values())
    total_node_modules = sum(i["size"] for i in node_modules)
    total_ios          = sum(i["size"] for i in ios_backups)
    total_xcode        = sum(i["size"] for i in xcode_archives)
    total_recordings   = sum(i["size"] for i in recordings)
    total_large        = sum(i["size"] for i in large_files)
    total_files        = len(screenshots) + len(bad_photos) + len(duplicates) + len(old_downloads)
    total_space        = total_cache + total_browser + total_node_modules + total_recordings

    api = f"http://127.0.0.1:{port}" if port else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Sweep — Scan Results</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif;
         background: #f5f5f7; color: #1d1d1f; padding: 40px 32px; }}
  h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 4px; }}
  .subtitle {{ color: #6e6e73; font-size: 15px; margin-bottom: 32px; }}
  .summary {{ display: flex; gap: 16px; margin-bottom: 40px; flex-wrap: wrap; }}
  .card {{ background: #fff; border-radius: 14px; padding: 20px 24px; min-width: 130px;
            flex: 1; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .card .num {{ font-size: 28px; font-weight: 700; }}
  .card .label {{ font-size: 12px; color: #6e6e73; margin-top: 3px; }}
  .red .num {{ color: #ff3b30; }} .orange .num {{ color: #ff9500; }}
  .blue .num {{ color: #007aff; }} .green .num {{ color: #34c759; }}
  .purple .num {{ color: #af52de; }}
  section {{ margin-bottom: 36px; }}
  .section-header {{ display: flex; align-items: center; justify-content: space-between;
                      margin-bottom: 12px; gap: 12px; }}
  .section-header h2 {{ font-size: 17px; font-weight: 600; }}
  .tag {{ display: inline-block; background: #f0f0f5; border-radius: 6px;
           padding: 2px 8px; font-size: 12px; color: #6e6e73; margin-left: 6px; }}
  .section-actions {{ display: flex; gap: 8px; align-items: center; flex-shrink: 0; }}
  .btn {{ padding: 7px 16px; border-radius: 8px; font-size: 13px; font-weight: 600;
           border: none; cursor: pointer; transition: opacity .15s; }}
  .btn:disabled {{ opacity: .4; cursor: default; }}
  .btn-clean {{ background: #ff3b30; color: #fff; }}
  .btn-clean:hover:not(:disabled) {{ opacity: .85; }}
  .btn-select {{ background: #f0f0f5; color: #1d1d1f; }}
  .btn-docker {{ background: #0d96f2; color: #fff; }}
  .table {{ background: #fff; border-radius: 14px;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden; }}
  .header {{ background: #f5f5f7; font-size: 12px; font-weight: 600;
              color: #6e6e73; text-transform: uppercase; letter-spacing: .5px; }}
  .row {{ display: flex; align-items: center; padding: 8px 16px;
          border-bottom: 1px solid #f0f0f0; gap: 12px; font-size: 14px; }}
  .row:last-child {{ border-bottom: none; }}
  .row.cleaned {{ opacity: .35; text-decoration: line-through; }}
  .name {{ flex: 1; font-weight: 500; word-break: break-all; min-width: 0; }}
  .folder {{ flex: 2; color: #6e6e73; font-size: 12px; word-break: break-all; min-width: 0; }}
  .size {{ width: 80px; text-align: right; color: #6e6e73; font-size: 13px; flex-shrink: 0; }}
  .empty {{ padding: 16px 20px; color: #34c759; font-size: 14px; }}
  .warning {{ background: #fff3cd; border-radius: 10px; padding: 12px 20px;
               font-size: 13px; color: #856404; margin-bottom: 12px; }}
  .toast {{ position: fixed; bottom: 32px; right: 32px; background: #1d1d1f;
             color: #fff; padding: 12px 20px; border-radius: 12px; font-size: 14px;
             font-weight: 500; opacity: 0; transition: opacity .3s;
             box-shadow: 0 4px 20px rgba(0,0,0,.3); z-index: 999; }}
  .toast.show {{ opacity: 1; }}
  input[type=checkbox] {{ width: 16px; height: 16px; flex-shrink: 0; cursor: pointer; accent-color: #007aff; }}
  .thumb {{ width: 60px; height: 60px; object-fit: cover; border-radius: 8px;
             flex-shrink: 0; cursor: pointer; border: 1px solid #e0e0e5;
             transition: transform .15s; }}
  .thumb:hover {{ transform: scale(1.06); }}
  .thumb-placeholder {{ width: 60px; height: 60px; border-radius: 8px; flex-shrink: 0;
                          display: flex; align-items: center; justify-content: center;
                          background: #f0f0f5; font-size: 22px; border: 1px solid #e0e0e5; }}
  /* lightbox */
  #lb {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.85);
          backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px);
          z-index:1000; align-items:center; justify-content:center; flex-direction:column;
          gap:16px; cursor:zoom-out; }}
  #lb.open {{ display:flex; }}
  #lb img {{ max-width:92vw; max-height:85vh; border-radius:12px; object-fit:contain;
              box-shadow:0 24px 80px rgba(0,0,0,.7); cursor:default; }}
  #lb-filename {{ color:rgba(255,255,255,.8); font-size:13px; letter-spacing:.2px; }}
  #lb-close {{ position:fixed; top:20px; right:24px; color:#fff; font-size:28px;
                cursor:pointer; opacity:.7; background:none; border:none;
                line-height:1; padding:4px 8px; }}
  #lb-close:hover {{ opacity:1; }}
</style>
</head>
<body>

<div id="lb" onclick="closeLb(event)">
  <button id="lb-close" onclick="document.getElementById('lb').classList.remove('open')">✕</button>
  <img id="lb-img" src="" onclick="event.stopPropagation()">
  <div id="lb-filename"></div>
</div>
<div class="toast" id="toast"></div>

<h1>🧹 Sweep Scan Results</h1>
<p class="subtitle">{total_files} junk files · {_format_bytes(total_space)} recoverable space · Click thumbnails to preview · Uncheck to skip</p>

<div class="summary">
  <div class="card red"><div class="num">{len(screenshots)}</div><div class="label">Screenshots</div></div>
  <div class="card orange"><div class="num">{len(old_downloads)}</div><div class="label">Old Downloads</div></div>
  <div class="card blue"><div class="num">{_format_bytes(total_cache)}</div><div class="label">Dev Cache</div></div>
  <div class="card blue"><div class="num">{_format_bytes(total_browser)}</div><div class="label">Browser Cache</div></div>
  <div class="card purple"><div class="num">{_format_bytes(total_node_modules)}</div><div class="label">node_modules</div></div>
  <div class="card orange"><div class="num">{_format_bytes(total_ios)}</div><div class="label">iOS Backups</div></div>
  <div class="card green"><div class="num">{_format_bytes(total_large)}</div><div class="label">Large Files</div></div>
</div>

<!-- Screenshots -->
<section id="sec-screenshots">
  <div class="section-header">
    <h2>📸 Screenshots <span class="tag">{len(screenshots)}</span></h2>
    <div class="section-actions">
      <button class="btn btn-select" onclick="toggleAll('sec-screenshots')">Select All</button>
      <button class="btn btn-clean" onclick="cleanFiles('sec-screenshots','/clean/files')">Move to Bin</button>
    </div>
  </div>
  <div class="table">
    <div class="row header"><div style="width:16px"></div><div style="width:60px"></div><div class="name">File</div><div class="folder">Location</div><div class="size">Size</div></div>
    {_file_rows(screenshots, checkable=True, show_thumb=True)}
  </div>
</section>

<!-- Bad photos -->
<section id="sec-bad">
  <div class="section-header">
    <h2>🌑 Bad / Dark Photos <span class="tag">{len(bad_photos)}</span></h2>
    <div class="section-actions">
      <button class="btn btn-select" onclick="toggleAll('sec-bad')">Select All</button>
      <button class="btn btn-clean" onclick="cleanFiles('sec-bad','/clean/files')">Move to Bin</button>
    </div>
  </div>
  <div class="table">
    <div class="row header"><div style="width:16px"></div><div style="width:60px"></div><div class="name">File</div><div class="folder">Location</div><div class="size">Size</div></div>
    {_file_rows(bad_photos, checkable=True, show_thumb=True)}
  </div>
</section>

<!-- Duplicates -->
<section id="sec-dupes">
  <div class="section-header">
    <h2>👯 Duplicate Photos <span class="tag">{len(duplicates)}</span></h2>
    <div class="section-actions">
      <button class="btn btn-select" onclick="toggleAll('sec-dupes')">Select All</button>
      <button class="btn btn-clean" onclick="cleanFiles('sec-dupes','/clean/files')">Move to Bin</button>
    </div>
  </div>
  <div class="table">
    <div class="row header"><div style="width:16px"></div><div style="width:60px"></div><div class="name">File</div><div class="folder">Location</div><div class="size">Size</div></div>
    {_file_rows(duplicates, checkable=True, show_thumb=True)}
  </div>
</section>

<!-- Old Downloads -->
<section id="sec-downloads">
  <div class="section-header">
    <h2>📦 Old Downloads <span class="tag">{len(old_downloads)}</span></h2>
    <div class="section-actions">
      <button class="btn btn-select" onclick="toggleAll('sec-downloads')">Select All</button>
      <button class="btn btn-clean" onclick="cleanFiles('sec-downloads','/clean/files')">Move to Bin</button>
    </div>
  </div>
  <div class="table">
    <div class="row header"><div style="width:16px"></div><div style="width:60px"></div><div class="name">File</div><div class="folder">Location</div><div class="size">Size</div></div>
    {_file_rows(old_downloads, checkable=True, show_thumb=True)}
  </div>
</section>

<!-- Browser caches -->
<section id="sec-browser">
  <div class="section-header">
    <h2>🌐 Browser Caches <span class="tag">{_format_bytes(total_browser)}</span></h2>
    <div class="section-actions">
      <button class="btn btn-clean" onclick="cleanBrowserCaches()">Clear All Browser Caches</button>
    </div>
  </div>
  <div class="table">
    <div class="row header"><div class="name">Browser</div><div class="folder"></div><div class="size">Size</div></div>
    {_browser_rows(browser_caches)}
  </div>
</section>

<!-- node_modules -->
<section id="sec-nm">
  <div class="section-header">
    <h2>📦 node_modules (30+ days old) <span class="tag">{len(node_modules)} · {_format_bytes(total_node_modules)}</span></h2>
    <div class="section-actions">
      <button class="btn btn-select" onclick="toggleAll('sec-nm')">Select All</button>
      <button class="btn btn-clean" onclick="cleanNodeModules('sec-nm')">Delete Selected</button>
    </div>
  </div>
  <div class="table">
    <div class="row header"><div style="width:16px"></div><div class="name">Project</div><div class="folder">Path</div><div class="size">Last used</div><div class="size">Size</div></div>
    {_dict_rows(node_modules, checkable=True, show_date=True)}
  </div>
</section>

<!-- Dev caches -->
<section id="sec-devcache">
  <div class="section-header">
    <h2>🗑️ Dev Caches <span class="tag">{_format_bytes(total_cache)}</span></h2>
    <div class="section-actions">
      <button class="btn btn-select" onclick="toggleAll('sec-devcache')">Select All</button>
      <button class="btn btn-clean" onclick="cleanCaches('sec-devcache')">Clear Selected</button>
    </div>
  </div>
  <div class="table">
    <div class="row header"><div style="width:16px"></div><div class="name" style="flex:3">Directory</div><div class="size">Size</div></div>
    {_cache_rows(cache_sizes)}
  </div>
</section>

<!-- Docker -->
<section id="sec-docker">
  <div class="section-header">
    <h2>🐳 Docker <span class="tag">{'running' if docker.get('available') else 'not running'}</span></h2>
    {'<div class="section-actions"><button class="btn btn-docker" onclick="pruneDocker()">docker system prune</button></div>' if docker.get('available') else ''}
  </div>
  <div class="table">
    <div class="row header"><div class="name">Type</div><div class="folder">Total Size</div><div class="size">Reclaimable</div></div>
    {_docker_rows(docker)}
  </div>
</section>

<!-- iOS Backups -->
<section id="sec-ios">
  <div class="section-header">
    <h2>📱 iOS Backups <span class="tag">{len(ios_backups)} · {_format_bytes(total_ios)}</span></h2>
    <div class="section-actions">
      <button class="btn btn-select" onclick="toggleAll('sec-ios')">Select All</button>
      <button class="btn btn-clean" onclick="cleanFiles('sec-ios','/clean/files')">Move to Bin</button>
    </div>
  </div>
  {"<p class='warning'>⚠️ Only delete old backups you no longer need.</p>" if ios_backups else ""}
  <div class="table">
    <div class="row header"><div style="width:16px"></div><div class="name">Backup</div><div class="folder">Path</div><div class="size">Date</div><div class="size">Size</div></div>
    {_dict_rows(ios_backups, checkable=True, show_date=True)}
  </div>
</section>

<!-- Xcode Archives -->
<section id="sec-xcode">
  <div class="section-header">
    <h2>🗂️ Xcode Archives <span class="tag">{len(xcode_archives)} · {_format_bytes(total_xcode)}</span></h2>
    <div class="section-actions">
      <button class="btn btn-select" onclick="toggleAll('sec-xcode')">Select All</button>
      <button class="btn btn-clean" onclick="cleanFiles('sec-xcode','/clean/files')">Move to Bin</button>
    </div>
  </div>
  <div class="table">
    <div class="row header"><div style="width:16px"></div><div class="name">Archive</div><div class="folder">Path</div><div class="size">Date</div><div class="size">Size</div></div>
    {_dict_rows(xcode_archives, checkable=True, show_date=True)}
  </div>
</section>

<!-- Recordings -->
<section id="sec-rec">
  <div class="section-header">
    <h2>🎬 Recordings <span class="tag">{len(recordings)} · {_format_bytes(total_recordings)}</span></h2>
    <div class="section-actions">
      <button class="btn btn-select" onclick="toggleAll('sec-rec')">Select All</button>
      <button class="btn btn-clean" onclick="cleanFiles('sec-rec','/clean/files')">Move to Bin</button>
    </div>
  </div>
  <div class="table">
    <div class="row header"><div style="width:16px"></div><div class="name">File</div><div class="folder">Location</div><div class="size">Size</div></div>
    {_file_rows([r["path"] for r in recordings], checkable=True)}
  </div>
</section>

<!-- Large files -->
<section id="sec-large">
  <div class="section-header">
    <h2>🐘 Large Files (500MB+) <span class="tag">{len(large_files)}</span></h2>
    <div class="section-actions">
      <button class="btn btn-select" onclick="toggleAll('sec-large')">Select All</button>
      <button class="btn btn-clean" onclick="cleanFiles('sec-large','/clean/files')">Move to Bin</button>
    </div>
  </div>
  {"<p class='warning'>⚠️ Review carefully — uncheck anything you want to keep.</p>" if large_files else ""}
  <div class="table">
    <div class="row header"><div style="width:16px"></div><div class="name">File</div><div class="folder">Location</div><div class="size">Size</div></div>
    {_file_rows([f["path"] for f in large_files], checkable=True)}
  </div>
</section>

<script>
const API = "{api}";

function toast(msg, ok=true) {{
  const el = document.getElementById('toast');
  el.textContent = (ok ? '✅ ' : '❌ ') + msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3500);
}}

function closeLb(e) {{
  if (e.target === document.getElementById('lb')) {{
    document.getElementById('lb').classList.remove('open');
  }}
}}
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') document.getElementById('lb').classList.remove('open');
}});

function openFile(path) {{
  const img = document.getElementById('lb-img');
  const fn = document.getElementById('lb-filename');
  // load full-res from disk via file:// URL
  img.src = 'file://' + path;
  fn.textContent = path.split('/').pop();
  document.getElementById('lb').classList.add('open');
}}

function toggleAll(secId) {{
  const sec = document.getElementById(secId);
  const cbs = sec.querySelectorAll('input.file-cb');
  const allChecked = [...cbs].every(c => c.checked);
  cbs.forEach(c => c.checked = !allChecked);
}}

function getChecked(secId) {{
  const sec = document.getElementById(secId);
  return [...sec.querySelectorAll('input.file-cb:checked')].map(c => c.value);
}}

async function post(endpoint, body) {{
  const resp = await fetch(API + endpoint, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body)
  }});
  return resp.json();
}}

async function cleanFiles(secId, endpoint) {{
  const paths = getChecked(secId);
  if (!paths.length) {{ toast('Nothing selected', false); return; }}
  const sec = document.getElementById(secId);
  sec.querySelectorAll('input.file-cb:checked').forEach(cb => {{
    cb.closest('.row').classList.add('cleaned');
    cb.checked = false;
  }});
  const r = await post(endpoint, {{paths}});
  toast(`Moved ${{r.ok}} item(s) to Bin${{r.fail ? ' · ' + r.fail + ' failed' : ''}}`);
}}

async function cleanCaches(secId) {{
  const dirs = getChecked(secId);
  if (!dirs.length) {{ toast('Nothing selected', false); return; }}
  const sec = document.getElementById(secId);
  sec.querySelectorAll('input.file-cb:checked').forEach(cb => {{
    cb.closest('.row').classList.add('cleaned');
    cb.checked = false;
  }});
  const r = await post('/clean/caches', {{dirs}});
  toast(`Cleared ${{r.ok}} cache dir(s)${{r.fail ? ' · ' + r.fail + ' failed' : ''}}`);
}}

async function cleanNodeModules(secId) {{
  const paths = getChecked(secId);
  if (!paths.length) {{ toast('Nothing selected', false); return; }}
  const sec = document.getElementById(secId);
  sec.querySelectorAll('input.file-cb:checked').forEach(cb => {{
    cb.closest('.row').classList.add('cleaned');
    cb.checked = false;
  }});
  const r = await post('/clean/node_modules', {{paths}});
  toast(`Deleted ${{r.ok}} node_modules folder(s)${{r.fail ? ' · ' + r.fail + ' failed' : ''}}`);
}}

async function cleanBrowserCaches() {{
  const dirs = {json.dumps(list(browser_caches.keys()) if browser_caches else [])};
  if (!dirs.length) {{ toast('No browser caches found', false); return; }}
  const r = await post('/clean/caches', {{dirs}});
  toast(`Cleared ${{r.ok}} browser cache(s)`);
}}

async function pruneDocker() {{
  toast('Running docker system prune…', true);
  const r = await post('/clean/docker', {{}});
  toast(r.success ? 'Docker pruned ✓' : 'Docker prune failed', r.success);
}}
</script>
</body>
</html>"""

    return html


def open_report(scan_result: dict, port: int = 0) -> None:
    html = _build_html(scan_result, port)
    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", prefix="sweep_report_", delete=False, mode="w"
    )
    tmp.write(html)
    tmp.close()
    subprocess.run(["open", tmp.name])
