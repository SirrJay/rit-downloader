"""Playback for the built-in player.

Local files: played directly when the browser supports them; otherwise remuxed (copy) or transcoded on the fly
with ffmpeg into fragmented MP4 / MP3, so every format plays (HEVC, MKV, AVI, WMV, FLV, AC3, DTS, WMA...).
Online videos (search results): streamed without downloading - single files are proxied with seeking,
separate video + audio streams are joined live by ffmpeg.
"""
import json
import os
import subprocess
import threading
import time
import uuid

import paths

NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BROWSER_VIDEO = {"h264", "vp8", "vp9", "av1"}
BROWSER_AUDIO = {"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le", "pcm_s24le", "pcm_f32le", "pcm_u8"}
DIRECT_EXT = {"mp4", "m4v", "m4a", "webm", "mp3", "ogg", "oga", "opus", "wav", "flac", "aac", "mov"}
FRAG = ["-movflags", "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4"]

_probe_cache = {}
_lock = threading.Lock()


def _ff(name):
    return paths.tool(name) or name


def probe(path):
    """Streams + duration of a local file (cached by modification time)."""
    key = (path, os.path.getmtime(path))
    with _lock:
        if key in _probe_cache:
            return _probe_cache[key]
    out = subprocess.run([_ff("ffprobe"), "-v", "error", "-show_entries",
                          "stream=index,codec_type,codec_name:stream_disposition=attached_pic:format=duration",
                          "-of", "json", path], capture_output=True, text=True, creationflags=NOWINDOW, timeout=30)
    data = json.loads(out.stdout or "{}")
    with _lock:
        _probe_cache[key] = data
    return data


def plan_local(path):
    """How to play a local file: direct | remux | transcode."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    try:
        data = probe(path)
    except Exception:
        data = {}
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        dur = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        dur = 0
    vc, ac = (v or {}).get("codec_name"), (a or {}).get("codec_name")
    p = {"type": "video" if v else "audio", "duration": dur, "vcodec": vc, "acodec": ac,
         "v": (v or {}).get("index"), "a": (a or {}).get("index")}
    if not v:
        p["mode"] = "direct" if (ext in DIRECT_EXT and ac in BROWSER_AUDIO) else "transcode"
    elif ext in DIRECT_EXT and ext != "mov" and vc in BROWSER_VIDEO and (not a or ac in BROWSER_AUDIO):
        p["mode"] = "direct"
    elif vc == "h264" and (not a or ac in ("aac", "mp3")):
        p["mode"] = "remux"              # fast: only the container changes
    else:
        p["mode"] = "transcode"          # HEVC, MPEG-4, WMV, AC3, DTS ...
    return p


def local_cmd(path, p, start=0.0):
    cmd = [_ff("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.2f}"]
    cmd += ["-i", path]
    if p["type"] == "audio":
        return cmd + ["-vn", "-map", f"0:{p['a']}", "-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3", "pipe:1"], "audio/mpeg"
    cmd += ["-map", f"0:{p['v']}"] + (["-map", f"0:{p['a']}"] if p.get("a") is not None else [])
    if p["mode"] == "remux":
        cmd += ["-c", "copy"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-vf", "scale='min(1920,iw)':-2"]
        cmd += ["-c:a", "copy"] if p.get("acodec") == "aac" else ["-c:a", "aac", "-b:a", "160k", "-ac", "2"]
    return cmd + FRAG + ["pipe:1"], "video/mp4"


def run_pipe(cmd):
    """Yield ffmpeg's output; the process is stopped as soon as the player stops reading."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            bufsize=0, creationflags=NOWINDOW)
    try:
        while True:
            chunk = proc.stdout.read(64 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.stdout.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- online streaming (no download)
sessions = {}


def _headers_arg(h):
    return "".join(f"{k}: {v}\r\n" for k, v in (h or {}).items())


def open_remote(url, ydl_opts, quality=720, audio_only=False):
    """Prepare streaming of an online video. Returns a session dict (id, kind, type, duration, title...)."""
    import yt_dlp
    opts = dict(ydl_opts)
    opts.update({"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    fmts = [f for f in (info.get("formats") or [info]) if f.get("url")]
    http = lambda f: (f.get("protocol") or "https").startswith("http") and "dash" not in (f.get("protocol") or "")
    has_v = lambda f: (f.get("vcodec") or "none") != "none"
    has_a = lambda f: (f.get("acodec") or "none") != "none"
    s = {"id": uuid.uuid4().hex[:12], "url": url, "title": info.get("title") or url, "duration": info.get("duration") or 0,
         "thumb": info.get("thumbnail") or "", "channel": info.get("channel") or info.get("uploader") or "",
         "vid": info.get("id"), "created": time.time()}
    if audio_only:
        aud = sorted([f for f in fmts if has_a(f) and not has_v(f) and http(f)],
                     key=lambda f: (str(f.get("acodec", "")).startswith("mp4a"), f.get("abr") or 0), reverse=True)
        if aud:
            f = aud[0]
            s.update(kind="proxy", type="audio", src=f["url"], headers=f.get("http_headers") or {},
                     mime="audio/mp4" if f.get("ext") in ("m4a", "mp4") else "audio/webm")
            sessions[s["id"]] = s
            return s
    # video: H.264 up to the chosen quality + AAC audio, joined live (copy, no re-encoding)
    vids = sorted([f for f in fmts if has_v(f) and not has_a(f) and http(f) and str(f.get("vcodec", "")).startswith("avc1")
                   and (f.get("height") or 0) <= quality], key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)
    auds = sorted([f for f in fmts if has_a(f) and not has_v(f) and http(f) and str(f.get("acodec", "")).startswith("mp4a")],
                  key=lambda f: f.get("abr") or 0, reverse=True)
    both = sorted([f for f in fmts if has_v(f) and has_a(f)], key=lambda f: (f.get("height") or 0) <= quality and (f.get("height") or 0), reverse=True)
    if audio_only and auds:
        f = auds[0]
        s.update(kind="proxy", type="audio", src=f["url"], headers=f.get("http_headers") or {}, mime="audio/mp4")
    elif vids and auds:
        s.update(kind="pipe", type="video", vsrc=vids[0]["url"], asrc=auds[0]["url"],
                 headers=vids[0].get("http_headers") or {}, height=vids[0].get("height"))
    elif both:
        f = both[0]
        playable = http(f) and f.get("ext") in ("mp4", "webm") and str(f.get("vcodec", "")).split(".")[0] in ("avc1", "vp9", "vp09", "av01", "vp8")
        if playable:
            s.update(kind="proxy", type="video", src=f["url"], headers=f.get("http_headers") or {},
                     mime="video/mp4" if f.get("ext") == "mp4" else "video/webm", height=f.get("height"))
        else:   # HLS or unusual codecs: let ffmpeg turn it into something the browser plays
            s.update(kind="pipe", type="video", vsrc=f["url"], asrc=None, headers=f.get("http_headers") or {},
                     transcode=not str(f.get("vcodec", "")).startswith("avc1"), height=f.get("height"))
    else:
        raise RuntimeError("No playable stream was found for this video.")
    if audio_only:
        s["type"] = "audio"
    sessions[s["id"]] = s
    # forget old sessions (stream links expire after a few hours anyway)
    for k in [k for k, v in sessions.items() if time.time() - v["created"] > 4 * 3600]:
        sessions.pop(k, None)
    return s


def remote_cmd(s, start=0.0):
    hdr = _headers_arg(s.get("headers"))
    cmd = [_ff("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-reconnect", "1", "-reconnect_streamed", "1",
           "-reconnect_delay_max", "5"]
    inp = []
    for src in [s.get("vsrc"), s.get("asrc")]:
        if not src:
            continue
        if start > 0:
            inp += ["-ss", f"{start:.2f}"]
        if hdr:
            inp += ["-headers", hdr]
        inp += ["-i", src]
    cmd += inp
    if s.get("asrc"):
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    if s.get("transcode"):
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k"]
    else:
        cmd += ["-c", "copy"]
    return cmd + FRAG + ["pipe:1"]
