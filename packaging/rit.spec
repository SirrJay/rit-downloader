# PyInstaller spec for Rit Downloader (Windows + macOS).
# Build:  pyinstaller --noconfirm packaging/rit.spec   (env RIT_TOOLS = folder with ffmpeg/ffprobe/deno)
import importlib.metadata as md
import os
import shutil
import sys
import zipfile

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
APP = os.path.join(ROOT, "app")
IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
TOOLS = os.environ.get("RIT_TOOLS") or os.path.join(ROOT, "build", "tools")
sys.path.insert(0, APP)
from version import VERSION  # noqa: E402

# ---------------------------------------------------------------------------------------
# yt-dlp is shipped as a zip next to the app (not compiled in), so "Update" in the app can
# drop a newer zip into the user folder without reinstalling.
PYLIB = os.path.join(ROOT, "build", "pylib")
shutil.rmtree(PYLIB, ignore_errors=True)
os.makedirs(PYLIB)


def zip_package(dist_name, import_name, out_name):
    import importlib
    mod = importlib.import_module(import_name)
    pkg_dir = os.path.dirname(mod.__file__)
    parent = os.path.dirname(pkg_dir)
    dist = md.distribution(dist_name)
    out = os.path.join(PYLIB, out_name.format(v=dist.version))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for base in [pkg_dir] + [os.path.join(parent, p) for p in os.listdir(parent)
                                 if p.lower().startswith(dist_name.replace("-", "_").lower() + "-")
                                 and p.endswith(".dist-info")]:
            for dp, dn, fn in os.walk(base):
                dn[:] = [d for d in dn if d != "__pycache__"]
                for f in fn:
                    if not f.endswith(".pyc"):
                        full = os.path.join(dp, f)
                        z.write(full, os.path.relpath(full, parent))
    return out


zip_package("yt-dlp", "yt_dlp", "yt-dlp-{v}.zip")
zip_package("yt-dlp-ejs", "yt_dlp_ejs", "yt_dlp_ejs-{v}-py3-none-any.whl")

# Analyse yt-dlp fully so every standard-library module and dependency it uses is bundled...
hidden = collect_submodules("yt_dlp") + collect_submodules("yt_dlp_ejs") + [
    "engine", "engine_dialog", "paths", "auth", "library", "fileget", "send2trash", "setup_ffmpeg", "version",
    "waitress", "flask", "certifi", "websockets", "brotli", "mutagen", "Cryptodome", "requests", "urllib3",
    "sqlite3", "xml.etree.ElementTree", "http.cookiejar", "netrc", "getpass", "hmac", "ctypes",
]
if IS_WIN:
    hidden += ["pystray._win32"]
elif IS_MAC:
    hidden += ["pystray._darwin"]

binaries, tool_datas = [], []
if os.path.isdir(TOOLS):
    for f in os.listdir(TOOLS):
        # Windows: copy as plain files - analysing them as binaries would duplicate the ffmpeg DLLs.
        # macOS: as binaries so they are code-signed with the app.
        (tool_datas if IS_WIN else binaries).append((os.path.join(TOOLS, f), "bin"))
else:
    print("WARNING: no tools folder at", TOOLS, "- ffmpeg/deno will not be bundled")

a = Analysis(
    [os.path.join(APP, "server.py")],
    pathex=[APP],
    binaries=binaries,
    datas=[(os.path.join(APP, "static"), "static"), (PYLIB, "pylib")] + tool_datas,
    hiddenimports=hidden,
    excludes=["matplotlib", "numpy", "pandas", "IPython", "pytest"] + (["tkinter"] if IS_MAC else []),
    noarchive=False,
)
# PyInstaller reclassifies the ffmpeg DLLs as binaries and copies their dependencies a second
# time into the top folder; keep only the copies inside bin/.
_tool_names = {f.lower() for f in os.listdir(TOOLS)} if os.path.isdir(TOOLS) else set()
a.binaries = [b for b in a.binaries
              if not (os.path.basename(b[0]).lower() in _tool_names and not b[0].replace("\\", "/").startswith("bin/"))]
# ...then take yt-dlp itself back out of the compiled archive (it is loaded from pylib/*.zip).
a.pure = [m for m in a.pure if not (m[0] == "yt_dlp" or m[0].startswith(("yt_dlp.", "yt_dlp_ejs")))]
a.datas = [d for d in a.datas if not d[0].replace("\\", "/").startswith(("yt_dlp_ejs/", "yt_dlp/"))]

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="RitDownloader",
    console=False,
    icon=os.path.join(APP, "static", "icon.ico" if IS_WIN else "icon.png"),
    upx=False,
    version=os.path.join(ROOT, "build", "win_version.txt") if IS_WIN and os.path.isfile(
        os.path.join(ROOT, "build", "win_version.txt")) else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="RitDownloader", upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Rit Downloader.app",
        icon=os.path.join(APP, "static", "icon.png"),
        bundle_identifier=os.environ.get("RIT_BUNDLE_ID", "com.ritdownloader.app"),
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSUIElement": True,          # lives in the menu bar, no Dock icon
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSAppleEventsUsageDescription": "Rit Downloader uses this to show the folder picker.",
        },
    )
