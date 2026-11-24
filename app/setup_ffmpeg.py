"""Fetches the helper programs Rit Downloader needs: ffmpeg + ffprobe (and Deno for building).

Runtime:  install()                -> downloads ffmpeg for this computer into the user folder
Build:    python setup_ffmpeg.py --dest build/tools --target win-x64|mac-arm64|mac-x64 [--deno]
"""
import argparse
import io
import os
import platform
import shutil
import ssl
import stat
import sys
import urllib.request
import zipfile

FF_WIN = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip"
FF_MAC = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release/{name}.zip"
DENO = "https://github.com/denoland/deno/releases/latest/download/deno-{triple}.zip"
DENO_TRIPLE = {"win-x64": "x86_64-pc-windows-msvc", "mac-arm64": "aarch64-apple-darwin",
               "mac-x64": "x86_64-apple-darwin"}


def current_target():
    if sys.platform == "win32":
        return "win-x64"
    if sys.platform == "darwin":
        return "mac-arm64" if platform.machine() == "arm64" else "mac-x64"
    raise SystemExit("Unsupported platform")


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _fetch(url, progress, label):
    progress(f"Downloading {label}...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    buf = io.BytesIO()
    with urllib.request.urlopen(req, timeout=120, context=_ctx()) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, -1
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            buf.write(chunk)
            done += len(chunk)
            if total and (done * 10 // total) != last:
                last = done * 10 // total
                progress(f"  {label}: {done * 100 // total}%")
    return zipfile.ZipFile(buf)


def _extract(z, dest, want):
    """Copy files whose basename satisfies want(basename) flat into dest."""
    n = 0
    for name in z.namelist():
        base = os.path.basename(name)
        if base and want(base):
            out = os.path.join(dest, base)
            with z.open(name) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.chmod(out, os.stat(out).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            n += 1
    return n


def fetch_ffmpeg(dest, target, progress=print):
    os.makedirs(dest, exist_ok=True)
    if target == "win-x64":
        z = _fetch(FF_WIN, progress, "ffmpeg")
        # shared build: small exes + DLLs (much smaller than two static exes)
        _extract(z, dest, lambda b: b in ("ffmpeg.exe", "ffprobe.exe") or b.lower().endswith(".dll"))
    else:
        arch = "arm64" if target == "mac-arm64" else "amd64"
        for name in ("ffmpeg", "ffprobe"):
            z = _fetch(FF_MAC.format(arch=arch, name=name), progress, name)
            _extract(z, dest, lambda b, n=name: b == n)
    ext = ".exe" if target.startswith("win") else ""
    return all(os.path.isfile(os.path.join(dest, n + ext)) for n in ("ffmpeg", "ffprobe"))


def fetch_deno(dest, target, progress=print):
    os.makedirs(dest, exist_ok=True)
    z = _fetch(DENO.format(triple=DENO_TRIPLE[target]), progress, "deno")
    return _extract(z, dest, lambda b: b in ("deno", "deno.exe")) > 0


def install(progress=print):
    """Runtime repair: put ffmpeg for this computer into the user's tools folder."""
    import paths
    if paths.ffmpeg_dir():
        progress("ffmpeg already installed.")
        return True
    ok = fetch_ffmpeg(paths.USER_BIN, current_target(), progress)
    progress("ffmpeg installed." if ok else "ffmpeg install FAILED.")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
    ap.add_argument("--target", default=None)
    ap.add_argument("--deno", action="store_true", help="also fetch the Deno JavaScript runtime")
    a = ap.parse_args()
    t = a.target or current_target()
    ext = ".exe" if t.startswith("win") else ""
    ok = True
    if not os.path.isfile(os.path.join(a.dest, "ffprobe" + ext)):
        ok = fetch_ffmpeg(a.dest, t)
    if a.deno and not os.path.isfile(os.path.join(a.dest, "deno" + ext)):
        ok = fetch_deno(a.dest, t) and ok
    print("OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)
