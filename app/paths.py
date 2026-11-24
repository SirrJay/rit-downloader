"""Locations of bundled resources, tools and user data - works from source and when frozen."""
import glob
import os
import shutil
import sys

APP_NAME = "Rit Downloader"
FROZEN = getattr(sys, "frozen", False)
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
EXE = ".exe" if IS_WIN else ""

if FROZEN:
    RES = sys._MEIPASS                                   # bundled read-only resources
    ROOT = RES
    STATIC = os.path.join(RES, "static")
    BUNDLED_BIN = os.path.join(RES, "bin")
    PYLIB = os.path.join(RES, "pylib")
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT = os.path.dirname(APP_DIR)
    STATIC = os.path.join(APP_DIR, "static")
    BUNDLED_BIN = os.path.join(ROOT, "bin")
    PYLIB = None


def _user_dir():
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, "RitDownloader")
    if IS_MAC:
        return os.path.expanduser("~/Library/Application Support/RitDownloader")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "rit-downloader")


DATA = os.environ.get("RIT_DATA") or _user_dir()   # RIT_DATA: separate profile for testing
USER_BIN = os.path.join(DATA, "bin")          # tools downloaded at runtime (e.g. ffmpeg repair)
UPDATES = os.path.join(DATA, "updates")       # newer yt-dlp downloaded by "Update"
for _d in (DATA, USER_BIN, UPDATES):
    os.makedirs(_d, exist_ok=True)

# One-time migration of settings from the old portable layout (./data)
_old = os.path.join(ROOT, "data")
if not FROZEN and not os.environ.get("RIT_DATA") and os.path.isdir(_old):
    for _f in ("settings.json", "jobs.json"):
        if os.path.isfile(os.path.join(_old, _f)) and not os.path.isfile(os.path.join(DATA, _f)):
            shutil.copy2(os.path.join(_old, _f), os.path.join(DATA, _f))


def tool(name):
    """Full path of ffmpeg / ffprobe / deno / node, or None."""
    for d in (USER_BIN, BUNDLED_BIN):
        p = os.path.join(d, name + EXE)
        if os.path.isfile(p):
            return p
    return shutil.which(name)


def ffmpeg_dir():
    p = tool("ffmpeg")
    return os.path.dirname(p) if p and tool("ffprobe") else None


PYLIB_PATTERNS = (("yt-dlp", "yt-dlp-*.zip"), ("yt-dlp-ejs", "yt_dlp_ejs-*.whl"))


def version_of(path):
    import re
    m = re.search(r"-(\d+(?:\.\d+)+)", os.path.basename(path))
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def setup_pylib(skip_updates=False):
    """Put yt-dlp (newest of bundled vs. user-updated) on sys.path before it is imported.

    In the frozen app yt-dlp is NOT compiled in; it ships as a zip so it can be updated
    without reinstalling the whole application."""
    if not FROZEN:
        return []
    chosen = []
    for _pkg, pat in PYLIB_PATTERNS:
        bundled = glob.glob(os.path.join(PYLIB, pat))
        updates = [] if skip_updates else glob.glob(os.path.join(UPDATES, pat))
        cands = bundled + updates
        if not cands:
            continue
        best = max(cands, key=version_of)
        sys.path.insert(0, best)
        chosen.append(best)
    return chosen


def discard_updates():
    for _pkg, pat in PYLIB_PATTERNS:
        for f in glob.glob(os.path.join(UPDATES, pat)):
            try:
                os.remove(f)
            except OSError:
                pass
