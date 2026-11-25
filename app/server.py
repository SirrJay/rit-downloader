"""Rit Downloader - local app server + tray icon.

Source:    python app/server.py [--no-browser]
Installed: RitDownloader.exe / Rit Downloader.app
"""
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

HOST, PORT = "127.0.0.1", int(os.environ.get("RIT_PORT") or 8765)
APP_URL = f"http://{HOST}:{PORT}/"

# ---- helper mode: native folder dialog in its own process ------------------------------
if __name__ == "__main__" and len(sys.argv) >= 4 and sys.argv[1] == "--pick-folder":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import engine_dialog  # noqa: E402  (tiny module, avoids importing yt-dlp)
    engine_dialog.run(sys.argv[2], sys.argv[3])
    sys.exit(0)

import paths  # noqa: E402
from version import UPDATE_REPO, VERSION  # noqa: E402

# Windowed builds have no console: keep stray output from crashing, log errors to a file.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None or paths.FROZEN:
    sys.stderr = open(os.path.join(paths.DATA, "error.log"), "a", encoding="utf-8", buffering=1)


def already_running():
    try:
        with urllib.request.urlopen(APP_URL + "api/ping", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def open_window(extra=""):
    """Open the UI in a chromeless app window (Edge/Chrome), else the default browser."""
    url = APP_URL + extra
    if paths.IS_WIN:
        cands = [os.path.expandvars(p) for p in (
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe")]
    elif paths.IS_MAC:
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                 "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                 os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    else:
        cands = []
    for exe in cands:
        if os.path.isfile(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=1440,920"])
                return
            except Exception:
                pass
    webbrowser.open(url)


if __name__ == "__main__" and "--no-browser" not in sys.argv and "--wait-port" not in sys.argv \
        and already_running():
    open_window()
    sys.exit(0)

# ---- import the engine (with a safety net for a broken yt-dlp update) -------------------
paths.setup_pylib()
try:
    import engine as E  # noqa: E402
except Exception:
    paths.discard_updates()
    for k in [m for m in sys.modules if m == "yt_dlp" or m.startswith(("yt_dlp.", "yt_dlp_ejs"))]:
        del sys.modules[k]
    sys.path[:] = [p for p in sys.path if paths.UPDATES not in p]
    import engine as E  # noqa: E402

from flask import Flask, abort, jsonify, make_response, request, send_from_directory  # noqa: E402

import auth  # noqa: E402

app = Flask(__name__, static_folder=paths.STATIC, static_url_path="/static")


@app.before_request
def guard():
    # Block DNS-rebinding and drive-by requests from other websites.
    host = (request.host or "").split(":")[0]
    if host not in ("127.0.0.1", "localhost"):
        abort(403)
    if request.method == "POST":
        origin = request.headers.get("Origin", "")
        if origin and not (origin.startswith(f"http://{HOST}") or origin.startswith("http://localhost")
                           or origin.startswith("chrome-extension://") or origin.startswith("extension://")):
            abort(403)
        if not request.is_json:
            abort(415)
    # ---- app lock
    p = request.path
    if not p.startswith("/api/") or p == "/api/ping" or p.startswith("/api/auth/"):
        return None
    token = request.cookies.get(auth.COOKIE)
    if auth.check(token, touch=request.method == "POST"):
        return None
    origin = request.headers.get("Origin", "")
    if p == "/api/download" and origin.startswith(("chrome-extension://", "extension://")) and auth.any_session():
        return None  # browser extension may queue downloads while the app is unlocked
    return jsonify(error="locked", locked=True), 401


@app.after_request
def nocache(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/ping")
def ping():
    return jsonify(ok=True, app="rit-downloader", version=VERSION)


# ---- login / app lock ----------------------------------------------------------------
def _with_cookie(payload, token, remember=False):
    resp = make_response(jsonify(payload))
    resp.set_cookie(auth.COOKIE, token, httponly=True, samesite="Strict", path="/",
                    max_age=auth.REMEMBER_DAYS * 86400 if remember else None)
    return resp


@app.get("/api/auth/status")
def auth_status():
    st = auth.status(request.cookies.get(auth.COOKIE))
    st["language"] = E.settings.get().get("language") or ""
    st["data_dir"] = paths.DATA
    return jsonify(st)


@app.post("/api/auth/touch")
def auth_touch():
    return jsonify(ok=auth.check(request.cookies.get(auth.COOKIE), touch=True))


@app.post("/api/auth/setup")
def auth_setup():
    d = request.get_json() or {}
    token, err = auth.setup(d.get("user"), d.get("password"), d.get("hint", ""))
    if err:
        return jsonify(error=err), 400
    return _with_cookie({"ok": True}, token)


@app.post("/api/auth/login")
def auth_login():
    d = request.get_json() or {}
    token, err, wait = auth.login(d.get("user"), d.get("password"), bool(d.get("remember")))
    if err:
        return jsonify(error=err, wait=wait), 401
    return _with_cookie({"ok": True}, token, bool(d.get("remember")))


@app.post("/api/auth/logout")
def auth_logout():
    auth.logout(request.cookies.get(auth.COOKIE))
    resp = make_response(jsonify(ok=True))
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.post("/api/auth/update")
def auth_update():
    token = request.cookies.get(auth.COOKIE)
    if not auth.check(token, touch=True):
        return jsonify(error="locked", locked=True), 401
    d = request.get_json() or {}
    changes = {k: d[k] for k in ("user", "password", "hint", "enabled") if k in d}
    err = auth.update(token, d.get("current"), changes)
    if err:
        return jsonify(error=err), 400
    return jsonify(ok=True, status=auth.status(token))


@app.post("/api/auth/autolock")
def auth_autolock():
    token = request.cookies.get(auth.COOKIE)
    if not auth.check(token, touch=True):
        return jsonify(error="locked", locked=True), 401
    auth.set_auto_lock(int((request.get_json() or {}).get("minutes") or 0))
    return jsonify(ok=True)


@app.get("/api/settings")
def get_settings():
    return jsonify(E.settings.get())


@app.post("/api/settings")
def set_settings():
    return jsonify(E.settings.update(request.get_json() or {}))


@app.get("/api/system")
def system():
    info = E.system_info()
    info["version"] = VERSION
    info["frozen"] = paths.FROZEN
    return jsonify(info)


_app_update = {"checked": 0, "data": None}


@app.get("/api/app-update")
def app_update():
    """Checks the project's GitHub releases for a newer version of the app itself."""
    if not UPDATE_REPO:
        return jsonify(available=False)
    if time.time() - _app_update["checked"] > 6 * 3600:
        _app_update["checked"] = time.time()
        try:
            import json
            with E._urlopen(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest", 10) as r:
                rel = json.load(r)
            latest = rel["tag_name"].lstrip("v")
            newer = paths.version_of("x-" + latest) > paths.version_of("x-" + VERSION)
            _app_update["data"] = {"available": newer, "latest": latest, "url": rel["html_url"]}
        except Exception:
            _app_update["data"] = None
    return jsonify(_app_update["data"] or {"available": False})


@app.post("/api/browse")
def browse():
    return jsonify(id=E.start_browse(request.get_json() or {}))


@app.get("/api/browse/<bid>")
def browse_poll(bid):
    b = E.browses.get(bid)
    if not b:
        abort(404)
    return jsonify(b.snapshot(int(request.args.get("since", 0))))


@app.post("/api/browse/<bid>/stop")
def browse_stop(bid):
    b = E.browses.get(bid)
    if b:
        b.cancel = True
    return jsonify(ok=True)


@app.post("/api/formats")
def formats():
    url = (request.get_json() or {}).get("url")
    try:
        return jsonify(E.get_formats(url))
    except Exception as ex:
        return jsonify(error=E.clean_error(ex)), 400


@app.post("/api/download")
def download():
    d = request.get_json() or {}
    items = d.get("items") or ([{"url": d["url"], "title": d.get("title", "")}] if d.get("url") else [])
    r = E.manager.add(items, d.get("options"), d.get("group"), force=bool(d.get("force")))
    return jsonify(**r, skipped=r["already"] + r["queued"])


# ---- library: what is already downloaded, channel folders, "download new only" ----------
@app.post("/api/library/status")
def library_status():
    vids = (request.get_json() or {}).get("vids") or []
    return jsonify(E.library.status_map(vids[:5000], E.settings.get().get("redownload_deleted")))


@app.get("/api/library")
def library_overview():
    chans = E.library.list_channels()
    for c in chans:
        c["sync"] = E.sync_state.get(c["channel_id"])
    scan = {k: v for k, v in E.scan_state.items() if k != "duplicates"}
    scan["duplicates"] = (E.scan_state.get("duplicates") or [])[:300]
    return jsonify(totals=E.library.totals(), channels=chans, scan=scan,
                   moved={k: v["to"] for k, v in E.sync_state.items() if v.get("state") == "moved"})


@app.post("/api/library/sync")
def library_sync():
    d = request.get_json() or {}
    keys = d.get("keys")
    if keys == "all":
        keys = [c["channel_id"] for c in E.library.list_channels() if c.get("tracked") or c.get("url")
                or c["channel_id"].startswith("name:")]
    E.start_sync(keys or [], download=bool(d.get("download", True)))
    return jsonify(ok=True, keys=keys)


@app.post("/api/library/channel")
def library_channel():
    """Track / update a channel: {key | id+name+url, tracked, auto, opts}."""
    d = request.get_json() or {}
    key = d.get("key") or d.get("id")
    cid = None if (key or "").startswith("name:") else key
    name = d.get("name") or (E.library.get_channel(key) or {}).get("name")
    k = E.library.upsert_channel(cid, name, url=d.get("url"), thumb=d.get("thumb"),
                                 tracked=d.get("tracked"), auto=d.get("auto"), opts=d.get("opts"))
    if d.get("tracked") and not (E.library.get_channel(k) or {}).get("folder"):
        E.library.channel_folder(cid, name, E.settings.get()["download_dir"])
    return jsonify(ok=True, channel=E.library.get_channel(k))


@app.post("/api/library/channel/folder")
def library_channel_folder():
    key = (request.get_json() or {}).get("key")
    ch = E.library.get_channel(key)
    if not ch:
        abort(404)
    p = E.pick_folder(ch.get("folder") or E.settings.get()["download_dir"])
    if p:
        E.library.upsert_channel(None if key.startswith("name:") else key, ch.get("name"), folder=p)
    return jsonify(path=p)


@app.post("/api/library/remove")
def library_remove():
    E.library.remove_channel((request.get_json() or {}).get("key"))
    return jsonify(ok=True)


@app.post("/api/library/scan")
def library_scan():
    d = request.get_json() or {}
    extra = []
    if d.get("pick"):
        p = E.pick_folder(E.settings.get()["download_dir"])
        if not p:
            return jsonify(ok=False)
        extra.append(p)
    threading.Thread(target=E.scan_library, args=(extra,), daemon=True).start()
    return jsonify(ok=True)


@app.get("/api/jobs")
def jobs():
    return jsonify(jobs=E.manager.list(), stats=E.manager.stats())


@app.post("/api/jobs/action")
def jobs_action():
    d = request.get_json() or {}
    E.manager.action(d.get("ids", []), d.get("action"))
    return jsonify(ok=True)


@app.post("/api/pick-folder")
def pick_folder():
    p = E.pick_folder(E.settings.get()["download_dir"])
    if p:
        E.settings.update({"download_dir": p})
    return jsonify(path=p, settings=E.settings.get())


@app.post("/api/open")
def open_path():
    d = request.get_json() or {}
    path = d.get("path") or E.settings.get()["download_dir"]
    return jsonify(ok=E.open_path(path, bool(d.get("select"))))


@app.post("/api/update-ytdlp")
def update_ytdlp():
    ok, out = E.update_ytdlp()
    return jsonify(ok=ok, output=out, restart=ok and "up to date" not in out)


@app.post("/api/install-ffmpeg")
def install_ffmpeg():
    try:
        ok = E.install_ffmpeg()
    except Exception as ex:
        return jsonify(ok=False, output=str(ex))
    return jsonify(ok=ok)


def _restart():
    time.sleep(0.6)
    cmd = [sys.executable] if paths.FROZEN else [sys.executable, os.path.abspath(__file__)]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd + ["--no-browser", "--wait-port"], creationflags=flags, close_fds=True)
    os._exit(0)


@app.post("/api/restart")
def restart():
    threading.Thread(target=_restart, daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/quit")
def quit_app():
    threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0)), daemon=True).start()
    return jsonify(ok=True)


# ---- tray / menu-bar icon --------------------------------------------------------------
def run_tray():
    """Blocks on the main thread. Returns False if no tray is possible."""
    try:
        import pystray
        from PIL import Image
    except Exception:
        return False
    try:
        img = Image.open(os.path.join(paths.STATIC, "icon.png"))
        menu = pystray.Menu(
            pystray.MenuItem("Open Rit Downloader", lambda: open_window(), default=True),
            pystray.MenuItem("Open downloads folder", lambda: E.open_path(E.settings.get()["download_dir"])),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit (stops downloads)", lambda icon: (icon.stop(), os._exit(0))),
        )
        pystray.Icon("RitDownloader", img, f"Rit Downloader {VERSION}", menu).run()
        return True
    except Exception as ex:
        print("tray failed:", ex, file=sys.stderr)
        return False


def main():
    from waitress import serve
    if "--wait-port" in sys.argv:
        for _ in range(40):
            if not already_running():
                break
            time.sleep(0.25)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, open_window).start()
    if "--no-tray" in sys.argv:
        serve(app, host=HOST, port=PORT, threads=12, ident="rit")
        return
    t = threading.Thread(target=lambda: serve(app, host=HOST, port=PORT, threads=12, ident="rit"), daemon=True)
    t.start()
    if not run_tray():
        t.join()
    os._exit(0)


if __name__ == "__main__":
    main()
