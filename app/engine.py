"""Core engine: searching / listing media and a threaded download queue built on yt-dlp."""
import json
import os
import shutil
import string
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import library
import paths
from paths import DATA, IS_MAC, IS_WIN

import yt_dlp
from yt_dlp.utils import DownloadCancelled, sanitize_filename

# bundled tools first on PATH (ffmpeg, ffprobe, deno)
for _d in (paths.USER_BIN, paths.BUNDLED_BIN):
    if os.path.isdir(_d):
        os.environ["PATH"] = _d + os.pathsep + os.environ.get("PATH", "")

SETTINGS_FILE = os.path.join(DATA, "settings.json")
JOBS_FILE = os.path.join(DATA, "jobs.json")
NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# --------------------------------------------------------------------------- utils


def _usage(root, label=None):
    u = shutil.disk_usage(root)
    return {"drive": root, "label": label or root, "free_gb": round(u.free / 2**30, 1),
            "total_gb": round(u.total / 2**30, 1)}


def fixed_drives():
    """Local disks with free space (GB). Windows: fixed drive letters. macOS: mounted volumes."""
    out = []
    if IS_WIN:
        import ctypes
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            try:
                if ctypes.windll.kernel32.GetDriveTypeW(root) != 3:
                    continue
                out.append(_usage(root))
            except Exception:
                pass
    else:
        try:
            out.append(_usage(os.path.expanduser("~") + "/", "Home"))
        except Exception:
            pass
        vols = "/Volumes" if IS_MAC else "/media"
        try:
            for v in sorted(os.listdir(vols)):
                p = os.path.join(vols, v)
                if os.path.ismount(p) and os.path.realpath(p) != "/":
                    try:
                        out.append(_usage(p + "/", v))
                    except Exception:
                        pass
        except Exception:
            pass
    return out


def default_download_dir():
    home_dl = os.path.join(os.path.expanduser("~"), "Downloads", "Rit Downloads")
    if IS_WIN:
        drives = fixed_drives()
        sysdrive = (os.environ.get("SystemDrive", "C:") + "\\").upper()
        sysfree = next((d["free_gb"] for d in drives if d["drive"].upper() == sysdrive), 999)
        others = [d for d in drives if d["drive"].upper() != sysdrive]
        # If the system drive is getting full, prefer the roomiest other drive.
        if sysfree < 30 and others:
            best = max(others, key=lambda d: d["free_gb"])
            if best["free_gb"] > sysfree * 2:
                return os.path.join(best["drive"], "Rit Downloads")
    return home_dl


def free_space_gb(path):
    p = os.path.abspath(path)
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        return round(shutil.disk_usage(p).free / 2**30, 1)
    except Exception:
        return None


def have_ffmpeg():
    return bool(paths.ffmpeg_dir())


def js_runtime_args():
    """yt-dlp needs a JavaScript runtime for YouTube. Prefer the bundled Deno, else Node."""
    for name in ("deno", "node"):
        p = paths.tool(name)
        if p:
            return ["--js-runtimes", f"{name}:{p}"]
    return []


# --------------------------------------------------------------------------- settings

DEFAULTS = {
    "download_dir": None,
    "concurrency": 2,
    "fragments": 4,
    "rate_limit": "",
    "sleep_interval": 1,
    "mode": "video",
    "video_quality": "1080",
    "video_container": "mp4",
    "video_codec": "compatible",
    "audio_format": "mp3",
    "audio_quality": "0",
    "embed_thumbnail": True,
    "embed_metadata": True,
    "embed_chapters": True,
    "subtitles": False,
    "auto_subs": False,
    "sub_langs": "en.*",
    "organize": "channel",
    "date_prefix": True,
    "archive": True,
    "redownload_deleted": False,
    "sync_hours": 12,
    "cookies_browser": "",
    "search_limit": 50,
    "theme": "dark",
    "language": "",
}


class Settings:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = dict(DEFAULTS)
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except Exception:
            pass
        if not self.data.get("download_dir"):
            self.data["download_dir"] = default_download_dir()
            self.save()

    def get(self):
        with self.lock:
            return dict(self.data)

    def update(self, changes):
        with self.lock:
            for k, v in changes.items():
                if k in DEFAULTS:
                    self.data[k] = v
        self.save()
        return self.get()

    def save(self):
        with self.lock:
            tmp = SETTINGS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, SETTINGS_FILE)


settings = Settings()

# --------------------------------------------------------------------------- yt-dlp option building


def base_args(s):
    # --remote-components lets yt-dlp fetch a newer YouTube challenge solver from GitHub
    # if the bundled one is out of date.
    a = js_runtime_args() + ["--remote-components", "ejs:github", "--no-color"]
    ff = paths.ffmpeg_dir()
    if ff:
        a += ["--ffmpeg-location", ff]
    if s.get("cookies_browser"):
        a += ["--cookies-from-browser", s["cookies_browser"]]
    return a


def file_name_template(s):
    name = "%(title).150B [%(id)s].%(ext)s"
    if s.get("date_prefix"):
        name = "%(upload_date>%Y-%m-%d&{} - |)s" + name
    return name


def build_download_args(s, group=None, format_id=None):
    a = base_args(s)
    a += ["--no-playlist", "--retries", "10", "--fragment-retries", "10",
          "--concurrent-fragments", str(int(s.get("fragments") or 1))]
    if s.get("rate_limit"):
        a += ["--limit-rate", str(s["rate_limit"])]

    # ---- output location / naming (the folder is chosen per video in Manager._run)
    a += ["-P", s["download_dir"], "-o", file_name_template(s)]

    meta_ok = True
    if s.get("mode") == "audio":
        fmt = s.get("audio_format") or "mp3"
        sort = {"m4a": "acodec:m4a", "aac": "acodec:m4a", "opus": "acodec:opus",
                "ogg": "acodec:opus"}.get(fmt)
        a += ["-f", format_id or "ba/b"]
        if sort and not format_id:
            a += ["-S", sort]
        a += ["-x", "--audio-format", "best" if fmt == "original" else
              ("vorbis" if fmt == "ogg" else fmt)]
        q = str(s.get("audio_quality") or "0")
        a += ["--audio-quality", q if q == "0" else q + "K"]
        thumb_ok = fmt not in ("wav", "aac")
        if s.get("subtitles"):
            a += ["--write-subs", "--sub-langs", s.get("sub_langs") or "en.*", "--convert-subs", "srt"]
            if s.get("auto_subs"):
                a += ["--write-auto-subs"]
    else:
        q = str(s.get("video_quality") or "best")
        cont = s.get("video_container") or "mp4"
        sort = []
        if q != "best":
            sort.append(f"res:{q}")
        if cont == "webm":
            sort += ["vcodec:vp9", "acodec:opus"]
        elif s.get("video_codec") == "compatible":
            sort += ["vcodec:h264", "acodec:m4a"]
        if format_id:
            a += ["-f", f"{format_id}+ba/{format_id}"]
        else:
            a += ["-f", "bv*+ba/b"]
        if sort:
            a += ["-S", ",".join(sort)]
        if cont in ("mp4", "mkv"):
            a += ["--merge-output-format", cont, "--remux-video", cont]
        elif cont == "webm":
            a += ["--merge-output-format", "webm/mkv"]
        else:  # mov / avi need re-encoding
            a += ["--merge-output-format", "mkv", "--recode-video", cont]
        thumb_ok = cont in ("mp4", "mkv", "mov")
        if s.get("subtitles"):
            a += ["--write-subs", "--sub-langs", s.get("sub_langs") or "en.*"]
            if s.get("auto_subs"):
                a += ["--write-auto-subs"]
            if cont in ("mp4", "mkv", "webm", "mov"):
                a += ["--embed-subs"]
        if s.get("embed_chapters"):
            a += ["--embed-chapters"]
    if s.get("embed_thumbnail") and thumb_ok:
        a += ["--embed-thumbnail"]
    if s.get("embed_metadata") and meta_ok:
        a += ["--embed-metadata"]
    return a


def ydl_opts_from_args(args):
    opts = yt_dlp.parse_options(args).ydl_opts
    opts["ignoreerrors"] = False  # surface real errors instead of returning None
    return opts


# --------------------------------------------------------------------------- browsing / search

SEARCH_PREFIX = {
    "youtube": "ytsearch",
    "youtube_new": "ytsearchdate",
    "soundcloud": "scsearch",
    "bilibili": "bilisearch",
    "niconico": "nicosearch",
}
YT_FILTER = {"channels": "EgIQAg%3D%3D", "playlists": "EgIQAw%3D%3D"}
YT_TABS = {"videos": "/videos", "streams": "/streams", "shorts": "/shorts", "podcasts": "/podcasts"}


def _thumb(e):
    if (e.get("ie_key") == "Youtube" or e.get("extractor_key") == "Youtube") and e.get("id"):
        return f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg"
    if e.get("thumbnail"):
        t = e["thumbnail"]
    else:
        ths = [t for t in (e.get("thumbnails") or []) if t.get("url")]
        if not ths:
            return ""
        mid = [t for t in ths if 200 <= (t.get("width") or 0) <= 720]
        t = (mid or ths)[-1]["url"]
    return "https:" + t if t.startswith("//") else t


def _date(e):
    d = e.get("upload_date") or e.get("release_date")
    if not d and e.get("timestamp"):
        try:
            d = datetime.fromtimestamp(e["timestamp"], timezone.utc).strftime("%Y%m%d")
        except Exception:
            d = None
    return d


def normalize(e, tab=None):
    ie = e.get("ie_key") or e.get("extractor_key") or ""
    url = e.get("webpage_url") or e.get("url") or ""
    eid = e.get("id") or url
    kind = "video"
    if e.get("_type") == "playlist" or ie in ("YoutubeTab",):
        if "/channel/" in url or "/@" in url or (eid or "").startswith("UC"):
            kind = "channel"
        else:
            kind = "playlist"
    if ie == "Youtube" and e.get("id") and not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={e['id']}"
    title = e.get("title") or e.get("fulltitle") or url
    return {
        "id": f"{ie}:{eid}",
        "vid": e.get("id"),
        "url": url,
        "title": title,
        "duration": e.get("duration"),
        "channel": e.get("channel") or e.get("uploader") or "",
        "channel_id": e.get("channel_id") or (e.get("uploader_id") if str(e.get("uploader_id") or "").startswith("UC") else None),
        "channel_url": e.get("channel_url") or e.get("uploader_url") or "",
        "views": e.get("view_count"),
        "date": _date(e),
        "kind": kind,
        "followers": e.get("channel_follower_count"),
        "count": e.get("playlist_count"),
        "live": e.get("live_status"),
        "thumb": _thumb(e),
        "desc": (e.get("description") or "")[:240],
        "tab": tab,
        "site": ie,
    }


def is_yt_channel(url):
    u = url.lower()
    if "youtube.com" not in u:
        return False
    if "/playlist" in u or "watch?" in u or "/shorts/" in u:
        return False
    return any(p in u for p in ("/@", "/channel/", "/c/", "/user/"))


def channel_base(url):
    u = url.split("?")[0].rstrip("/")
    for t in ("/videos", "/streams", "/shorts", "/podcasts", "/featured", "/playlists", "/live", "/releases"):
        if u.lower().endswith(t):
            return u[: -len(t)]
    return u


def _avatar(info):
    ths = [t for t in (info.get("thumbnails") or []) if t.get("url")]
    sq = [t for t in ths if t.get("id") == "avatar_uncropped" or (t.get("width") and t.get("width") == t.get("height"))]
    t = (sq or [None])[-1]
    if not t:
        return ""
    u = t["url"]
    return "https:" + u if u.startswith("//") else u


def annotate(entries):
    """Mark entries the library already has: e['dl'] = {'audio': bool, 'video': bool}."""
    vids = [e.get("vid") for e in entries if e.get("kind") == "video" and e.get("vid")]
    if not vids:
        return entries
    st = library.status_map(vids, settings.get().get("redownload_deleted"))
    for e in entries:
        if e.get("kind") == "video":
            e["dl"] = st.get(e.get("vid"), {"audio": False, "video": False})
    return entries


def channel_info(ch):
    """Browse-header info for a channel being listed, merged with what the library knows."""
    known = library.get_channel(ch["id"]) or library.get_channel("name:" + (ch.get("name") or "")) or {}
    if known and (not known.get("url") or known["channel_id"].startswith("name:")):
        library.upsert_channel(ch["id"], ch["name"], url=ch["url"], thumb=ch.get("thumb") or None)
        known = library.get_channel(ch["id"]) or known
    return {**ch, "tracked": bool(known.get("tracked")), "auto": bool(known.get("auto")),
            "folder": known.get("folder"), "key": ch["id"]}


class Browse:
    def __init__(self, req):
        self.id = uuid.uuid4().hex[:10]
        self.req = req
        self.title = ""
        self.entries = []
        self.seen = set()
        self.done = False
        self.error = None
        self.cancel = False
        self.status = "Starting..."
        self.max = 0
        self.channel = None      # set when listing a channel: {id, name, url, thumb}
        self.lock = threading.Lock()

    def add(self, item):
        with self.lock:
            if item["id"] in self.seen:
                return
            self.seen.add(item["id"])
            self.entries.append(item)

    def snapshot(self, since):
        with self.lock:
            new = self.entries[since:]
            snap = {"id": self.id, "title": self.title, "entries": new,
                    "total": len(self.entries), "done": self.done, "error": self.error,
                    "status": self.status}
        annotate(new)
        if self.channel:
            snap["channel"] = channel_info(self.channel)
        return snap


browses = {}


def start_browse(req):
    b = Browse(req)
    browses[b.id] = b
    # keep memory bounded
    if len(browses) > 20:
        for k in list(browses)[:-20]:
            browses.pop(k, None)
    threading.Thread(target=_run_browse, args=(b,), daemon=True).start()
    return b.id


def _iter_entries(b, ydl, url, tab=None, depth=0):
    info = ydl.extract_info(url, download=False, process=False)
    hops = 0
    while info.get("_type") == "url" and hops < 3:
        info = ydl.extract_info(info["url"], download=False, process=False,
                                ie_key=info.get("ie_key"))
        hops += 1
    if not b.title:
        b.title = info.get("title") or info.get("channel") or ""
    if b.req.get("kind") == "url" and info.get("channel_id") and not b.channel and is_yt_channel(url):
        b.channel = {"id": info.get("channel_id"), "name": info.get("channel") or info.get("uploader") or "",
                     "url": channel_base(info.get("channel_url") or url), "thumb": _avatar(info)}
    if info.get("_type") in ("playlist", "multi_video"):
        for e in info.get("entries") or []:
            if b.cancel:
                return
            if e is None:
                continue
            if b.max and len(b.entries) >= b.max:
                return
            item = normalize(e, tab)
            if info.get("_type") == "playlist" and b.req.get("kind") == "url" and b.channel:
                item["channel"] = item["channel"] or b.channel["name"]
                item["channel_id"] = item["channel_id"] or b.channel["id"]
                item["channel_url"] = item["channel_url"] or b.channel["url"]
            # A channel's home page lists its tabs as nested playlists -> expand once
            if item["kind"] != "video" and depth == 0 and b.req.get("kind") == "url" \
                    and any(item["url"].rstrip("/").endswith(t) for t in YT_TABS.values()):
                _iter_entries(b, ydl, item["url"], item["url"].rstrip("/").rsplit("/", 1)[-1], depth + 1)
                continue
            b.add(item)
            b.status = f"Loaded {len(b.entries)}..."
    else:
        b.add(normalize(info, tab))


def _run_browse(b):
    s = settings.get()
    req = b.req
    kind = req.get("kind", "search")
    q = (req.get("query") or "").strip()
    limit = int(req.get("limit") or s.get("search_limit") or 50)
    platform = req.get("platform", "youtube")
    opts = ydl_opts_from_args(base_args(s) + [
        "--flat-playlist", "--extractor-args", "youtubetab:approximate_date"])
    opts.update({"quiet": True, "no_warnings": True, "skip_download": True,
                 "extract_flat": "in_playlist", "logger": _QuietLogger()})
    try:
        urls = []
        if kind == "search":
            prefix = SEARCH_PREFIX.get(platform, "ytsearch")
            urls = [(f"{prefix}{limit}:{q}", None)]
            b.title = f'Search: "{q}"'
        elif kind in ("channels", "playlists"):
            from urllib.parse import quote_plus
            urls = [(f"https://www.youtube.com/results?search_query={quote_plus(q)}&sp={YT_FILTER[kind]}", None)]
            b.title = f'{kind.title()} matching "{q}"'
            b.max = limit
        else:  # url / channel listing
            b.max = int(req.get("max") or 0)
            if is_yt_channel(q):
                base = channel_base(q)
                tabs = req.get("tabs") or ["videos"]
                if "all" in tabs:
                    tabs = ["videos", "streams"]
                urls = [(base + YT_TABS[t], t) for t in tabs if t in YT_TABS]
            else:
                urls = [(q, None)]
        with yt_dlp.YoutubeDL(opts) as ydl:
            for u, tab in urls:
                if b.cancel:
                    break
                b.status = f"Loading {tab or ''}..."
                try:
                    _iter_entries(b, ydl, u, tab)
                except Exception as ex:
                    # a missing tab (e.g. channel without live streams) shouldn't kill the whole load
                    if len(urls) > 1:
                        continue
                    raise ex
        if kind == "url" and len(urls) and is_yt_channel(q) and b.title:
            b.title = b.title.replace(" - Videos", "").replace(" - Live", "")
        b.status = "Stopped" if b.cancel else f"{len(b.entries)} items"
    except Exception as ex:
        b.error = clean_error(ex)
        b.status = "Error"
    finally:
        b.done = True


class _QuietLogger:
    def debug(self, msg):
        pass

    info = debug
    warning = debug

    def error(self, msg):
        pass


def clean_error(ex):
    msg = str(ex)
    msg = msg.replace("\x1b[0;31mERROR:\x1b[0m ", "").replace("ERROR: ", "")
    if "logged-in" in msg or "login" in msg.lower() or "cookies" in msg:
        msg = msg.split(". Use --cookies")[0] + ".  (Tip: sign in to the site in your browser, then turn on Settings > Sign-in > 'Use cookies from a browser'.)"
    elif "Sign in to confirm" in msg:
        msg += "  (Tip: Settings > 'Use cookies from browser' can help.)"
    return msg.strip()[:600]


# --------------------------------------------------------------------------- formats (quality list)


def get_formats(url):
    s = settings.get()
    opts = ydl_opts_from_args(base_args(s) + ["--no-playlist"])
    opts.update({"quiet": True, "no_warnings": True, "skip_download": True, "logger": _QuietLogger()})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    dur = info.get("duration") or 0
    video, audio = [], []
    best_audio_size = 0
    for f in info.get("formats") or []:
        if f.get("format_note") == "storyboard" or f.get("ext") == "mhtml":
            continue
        size = f.get("filesize") or f.get("filesize_approx")
        if not size and f.get("tbr") and dur:
            size = int(f["tbr"] * 1000 / 8 * dur)
        vc, ac = f.get("vcodec") or "none", f.get("acodec") or "none"
        row = {"id": f.get("format_id"), "ext": f.get("ext"), "height": f.get("height"),
               "width": f.get("width"), "fps": f.get("fps"), "vcodec": vc.split(".")[0],
               "acodec": ac.split(".")[0], "abr": f.get("abr"), "tbr": f.get("tbr"),
               "size": size, "note": f.get("format_note") or "", "lang": f.get("language"),
               "proto": f.get("protocol")}
        if vc != "none":
            row["has_audio"] = ac != "none"
            video.append(row)
        elif ac != "none":
            audio.append(row)
            if size and (f.get("abr") or 0) >= max((a.get("abr") or 0) for a in audio):
                best_audio_size = size
    fam = lambda c: {"avc1": "h264", "vp09": "vp9", "av01": "av1", "hev1": "h265", "hvc1": "h265"}.get(c, c)
    for v in video:
        v["vcodec"] = fam(v["vcodec"])
    direct = {(v["height"], v["vcodec"]) for v in video if not (v["proto"] or "").startswith("m3u8")}
    video = [v for v in video if not ((v["proto"] or "").startswith("m3u8") and (v["height"], v["vcodec"]) in direct)]
    audio = [a for a in audio if not str(a["id"]).endswith("-drc")]
    for v in video:
        if not v["has_audio"] and v["size"]:
            v["size_total"] = v["size"] + best_audio_size
        else:
            v["size_total"] = v["size"]
    video.sort(key=lambda r: ((r["height"] or 0), (r["fps"] or 0), (r["tbr"] or 0)), reverse=True)
    audio.sort(key=lambda r: ((r["abr"] or r["tbr"] or 0)), reverse=True)
    return {"title": info.get("title"), "duration": dur, "channel": info.get("channel") or info.get("uploader"),
            "thumb": info.get("thumbnail"), "url": info.get("webpage_url") or url,
            "video": video, "audio": audio, "date": info.get("upload_date")}


# --------------------------------------------------------------------------- download queue


class Job:
    FIELDS = ("id", "url", "title", "thumb", "group", "format_id", "opts", "status", "percent",
              "speed", "eta", "downloaded", "total", "stage", "filepath", "error", "created",
              "finished", "channel", "duration", "vid", "site", "channel_id", "force")

    def __init__(self, url, title="", thumb="", group=None, format_id=None, opts=None,
                 channel="", duration=None):
        self.id = uuid.uuid4().hex[:12]
        self.url, self.title, self.thumb, self.group = url, title or url, thumb, group
        self.format_id, self.opts = format_id, opts or {}
        self.channel, self.duration = channel, duration
        self.status = "queued"  # queued|running|done|skipped|error|canceled|paused
        self.percent = 0.0
        self.speed = self.eta = self.downloaded = self.total = None
        self.stage = ""
        self.filepath = None
        self.error = None
        self.created = time.time()
        self.finished = None
        self.stop_reason = None  # 'cancel' | 'pause'
        self.vid = self.site = self.channel_id = None
        self.force = False

    def to_dict(self):
        return {k: getattr(self, k) for k in self.FIELDS}

    @classmethod
    def from_dict(cls, d):
        j = cls(d["url"])
        for k in cls.FIELDS:
            if k in d:
                setattr(j, k, d[k])
        return j


class JobLogger:
    def __init__(self, job):
        self.job = job

    def debug(self, msg):
        if "has already been recorded in the archive" in msg:
            self.job.stage = "Already downloaded (skipped)"
            self.job.skipped = True
        elif "[Merger]" in msg:
            self.job.stage = "Merging video + audio..."
        elif "[ExtractAudio]" in msg:
            self.job.stage = "Converting audio..."
        elif "[VideoConvertor]" in msg or "[VideoRemuxer]" in msg:
            self.job.stage = "Converting video..."
        elif "has already been downloaded" in msg:
            self.job.stage = "Already exists"
            self.job.skipped = True

    info = debug

    def warning(self, msg):
        pass

    def error(self, msg):
        self.job.last_error = msg


class Manager:
    def __init__(self):
        self.jobs = []
        self.lock = threading.RLock()
        self.cv = threading.Condition(self.lock)
        self.running = 0
        self._dirty = False
        self._load()
        threading.Thread(target=self._scheduler, daemon=True).start()
        threading.Thread(target=self._saver, daemon=True).start()

    # persistence ------------------------------------------------------------
    def _load(self):
        try:
            with open(JOBS_FILE, encoding="utf-8") as f:
                for d in json.load(f):
                    j = Job.from_dict(d)
                    if j.status in ("running", "queued"):
                        j.status, j.stage = "paused", "Paused (app was closed)"
                    self.jobs.append(j)
        except Exception:
            pass

    def _saver(self):
        while True:
            time.sleep(3)
            if self._dirty:
                self._dirty = False
                try:
                    with self.lock:
                        data = [j.to_dict() for j in self.jobs]
                    tmp = JOBS_FILE + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                    os.replace(tmp, JOBS_FILE)
                except Exception:
                    pass

    def touch(self):
        self._dirty = True
        with self.cv:
            self.cv.notify_all()

    # API --------------------------------------------------------------------
    def add(self, items, opts_override=None, group=None, force=False):
        """Queue downloads. Videos already in the library (for this mode) are skipped unless force=True.
        Returns {"added", "already" (in library), "queued" (already in the list)}."""
        s = settings.get()
        if opts_override:
            s.update(opts_override)
        mode = s.get("mode")
        skip_known = s.get("archive", True) and not force
        redl = s.get("redownload_deleted")
        added = already = queued = 0
        with self.lock:
            active = set()
            for j in self.jobs:
                if j.status in ("queued", "running", "paused"):
                    active.add((j.url, j.format_id, j.opts.get("mode")))
                    if j.vid:
                        active.add((j.vid, j.opts.get("mode")))
            for it in items:
                url = it.get("url")
                if not url:
                    continue
                vid = it.get("vid")
                if (url, it.get("format_id"), mode) in active or (vid and (vid, mode) in active):
                    queued += 1
                    continue
                if skip_known and vid and library.is_downloaded(vid, mode, redl):
                    already += 1
                    continue
                active.add((url, it.get("format_id"), mode))
                if vid:
                    active.add((vid, mode))
                j = Job(url, it.get("title"), it.get("thumb"), it.get("group") or group,
                        it.get("format_id"), dict(s), it.get("channel", ""), it.get("duration"))
                j.vid, j.site, j.channel_id, j.force = vid, it.get("site"), it.get("channel_id"), bool(force)
                self.jobs.append(j)
                added += 1
        self.touch()
        return {"added": added, "already": already, "queued": queued}

    def list(self):
        with self.lock:
            return [j.to_dict() for j in self.jobs]

    def action(self, ids, act):
        with self.lock:
            targets = [j for j in self.jobs if (ids == "all" or j.id in ids)]
            for j in targets:
                if act == "cancel":
                    if j.status == "running":
                        j.stop_reason = "cancel"
                    elif j.status in ("queued", "paused"):
                        j.status, j.stage = "canceled", ""
                elif act == "pause":
                    if j.status == "running":
                        j.stop_reason = "pause"
                    elif j.status == "queued":
                        j.status, j.stage = "paused", "Paused"
                elif act in ("resume", "retry"):
                    if j.status in ("paused", "error", "canceled") or (act == "retry" and j.status == "error"):
                        j.status, j.stage, j.error, j.stop_reason = "queued", "", None, None
                        j.percent = 0
                elif act == "remove":
                    if j.status == "running":
                        j.stop_reason = "cancel"
                        j.remove_after = True
                    else:
                        self.jobs.remove(j)
            if act == "clear":
                self.jobs = [j for j in self.jobs if j.status in ("queued", "running", "paused")]
        self.touch()

    def stats(self):
        with self.lock:
            c = {}
            for j in self.jobs:
                c[j.status] = c.get(j.status, 0) + 1
            return c

    # workers ----------------------------------------------------------------
    def _scheduler(self):
        while True:
            with self.cv:
                limit = max(1, min(8, int(settings.get().get("concurrency") or 1)))
                nxt = None
                if self.running < limit:
                    nxt = next((j for j in self.jobs if j.status == "queued"), None)
                if nxt is None:
                    self.cv.wait(timeout=1.0)
                    continue
                nxt.status, nxt.stage, nxt.percent = "running", "Starting...", 0
                self.running += 1
            threading.Thread(target=self._run, args=(nxt,), daemon=True).start()

    def _run(self, job):
        job.skipped = False
        job.last_error = None
        try:
            s = dict(job.opts)
            # always use the current folder/cookies so restored jobs follow settings changes
            cur = settings.get()
            for k in ("download_dir", "cookies_browser", "rate_limit", "fragments"):
                s[k] = cur.get(k)
            os.makedirs(s["download_dir"], exist_ok=True)
            opts = ydl_opts_from_args(build_download_args(s, job.group, job.format_id))

            def hook(d):
                if job.stop_reason:
                    raise DownloadCancelled()
                if d["status"] == "downloading":
                    tb = d.get("total_bytes") or d.get("total_bytes_estimate")
                    db = d.get("downloaded_bytes") or 0
                    job.downloaded, job.total = db, tb
                    job.percent = round(db * 100 / tb, 1) if tb else job.percent
                    job.speed, job.eta = d.get("speed"), d.get("eta")
                    inf = d.get("info_dict") or {}
                    vc = inf.get("vcodec") or "none"
                    part = "video stream" if vc != "none" and (inf.get("acodec") or "none") == "none" else \
                        ("audio stream" if vc == "none" else "file")
                    job.stage = f"Downloading {part}"
                elif d["status"] == "finished":
                    job.stage = "Processing..."

            def pp_hook(d):
                if d["status"] == "started":
                    name = d.get("postprocessor", "")
                    job.stage = {"Merger": "Merging video + audio...", "ExtractAudio": "Converting audio...",
                                 "EmbedThumbnail": "Embedding cover art...", "FFmpegMetadata": "Writing metadata...",
                                 "VideoConvertor": "Converting video (may take a while)...",
                                 "VideoRemuxer": "Remuxing..."}.get(name, f"{name}...")
                fp = (d.get("info_dict") or {}).get("filepath")
                if fp:
                    job.filepath = fp

            opts.update({"progress_hooks": [hook], "postprocessor_hooks": [pp_hook],
                         "logger": JobLogger(job), "quiet": True, "noprogress": True})
            sleep = float(s.get("sleep_interval") or 0)
            if sleep > 0:
                opts["sleep_interval"] = sleep
            mode = s.get("mode") or "video"
            skip_known = s.get("archive", True) and not job.force
            redl = s.get("redownload_deleted")
            # 1) known id: skip without touching the network
            if skip_known and job.vid:
                have = library.is_downloaded(job.vid, mode, redl)
                if have:
                    job.filepath = have if isinstance(have, str) else job.filepath
                    job.status, job.stage, job.percent = "skipped", "Already downloaded (skipped)", 100
                    return
            with yt_dlp.YoutubeDL(opts) as ydl:
                # 2) identify the video (real id + channel), then decide skip / folder
                job.stage = "Starting..."
                info = ydl.extract_info(job.url, download=False, process=False)
                hops = 0
                while info and info.get("_type") == "url" and hops < 3:
                    info = ydl.extract_info(info["url"], download=False, process=False, ie_key=info.get("ie_key"))
                    hops += 1
                if job.stop_reason:
                    raise DownloadCancelled()
                vid = info.get("id") or job.vid
                job.vid = vid
                job.site = info.get("extractor_key") or job.site
                job.channel_id = info.get("channel_id") or job.channel_id
                ch_name = info.get("channel") or info.get("uploader") or job.channel or ""
                job.channel = ch_name
                job.title = info.get("title") or job.title
                if not job.thumb:
                    job.thumb = info.get("thumbnail") or ""
                if skip_known:
                    have = library.is_downloaded(vid, mode, redl)
                    if have:
                        job.filepath = have if isinstance(have, str) else job.filepath
                        job.status, job.stage, job.percent = "skipped", "Already downloaded (skipped)", 100
                        return
                folder = target_folder(s, job, ch_name)
                os.makedirs(folder, exist_ok=True)
                ydl.params["outtmpl"]["default"] = os.path.join(folder.replace("%", "%%"), file_name_template(s))
                # 3) download
                info = ydl.process_ie_result(info, download=True)
                if info:
                    rd = info.get("requested_downloads") or []
                    if rd and rd[-1].get("filepath"):
                        job.filepath = rd[-1]["filepath"]
            if job.stop_reason:
                raise DownloadCancelled()
            if job.filepath and os.path.isfile(job.filepath):
                library.record(job.vid, mode, extractor=job.site, filepath=job.filepath, title=job.title,
                               channel_id=job.channel_id, channel=job.channel,
                               upload_date=(info or {}).get("upload_date"))
                if job.channel_id or job.channel:
                    library.upsert_channel(job.channel_id, job.channel,
                                           url=(info or {}).get("channel_url") or (info or {}).get("uploader_url"))
            if job.skipped:
                job.status, job.stage = "skipped", "Already exists"
            else:
                job.status, job.stage = "done", "Completed"
            job.percent = 100
        except DownloadCancelled:
            if job.stop_reason == "pause":
                job.status, job.stage = "paused", "Paused"
            else:
                job.status, job.stage = "canceled", "Canceled"
        except Exception as ex:
            if job.stop_reason:
                job.status = "paused" if job.stop_reason == "pause" else "canceled"
                job.stage = job.status.title()
            else:
                job.status, job.stage = "error", "Failed"
                job.error = clean_error(job.last_error or ex)
        finally:
            job.finished = time.time()
            job.speed = job.eta = None
            job.stop_reason = None
            with self.cv:
                self.running -= 1
                if getattr(job, "remove_after", False) and job in self.jobs:
                    self.jobs.remove(job)
            self.touch()


def target_folder(s, job, channel_name):
    """Where this video goes:
    channel -> the channel's own folder (kept forever, even if the download folder changes)
    group   -> one folder per search / playlist
    none    -> the download folder itself"""
    base = s["download_dir"]
    org = s.get("organize") or "channel"
    if org == "channel" and (job.channel_id or channel_name):
        return library.channel_folder(job.channel_id, channel_name, base)
    if org == "group" and job.group:
        return os.path.join(base, library.safe_folder_name(job.group))
    return base


manager = Manager()


# --------------------------------------------------------------------------- channel sync ("download new only")
sync_state = {}          # channel key -> {"state": "checking"|"done"|"error", "new": n, "total": n, ...}
_sync_lock = threading.Lock()


def list_channel_videos(url, tabs=("videos", "streams")):
    """Blocking flat listing of a channel's videos (fast: no per-video requests)."""
    b = Browse({"kind": "url", "query": url, "tabs": list(tabs)})
    _run_browse(b)
    if b.error and not b.entries:
        raise RuntimeError(b.error)
    return b


def resolve_channel(key):
    """A channel known only by folder name (from a disk scan): look up its real id/address
    from one of its downloaded videos."""
    ch = library.get_channel(key)
    if not ch or ch.get("url"):
        return key
    with library._lock:
        rows = library._db().execute("SELECT video_id, extractor FROM downloads WHERE channel_id=? LIMIT 3",
                                     (key,)).fetchall()
    opts = ydl_opts_from_args(base_args(settings.get()) + ["--no-playlist"])
    opts.update({"quiet": True, "no_warnings": True, "skip_download": True, "logger": _QuietLogger()})
    for r in rows:
        vid = r["video_id"]
        if len(vid) != 11 or (r["extractor"] and r["extractor"] != "youtube"):
            continue
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False, process=False)
            if info.get("channel_id"):
                return library.upsert_channel(info["channel_id"], ch.get("name") or info.get("channel"),
                                              url=channel_base(info.get("channel_url") or ""))
        except Exception:
            continue
    return key


def sync_channel(key, download=True, opts=None):
    """Find videos on the channel that are not in the library yet; optionally queue them."""
    if key.startswith("name:"):
        old = key
        key = resolve_channel(key)
        if key != old:
            sync_state.pop(old, None)
            sync_state[old] = {"state": "moved", "to": key}
    ch = library.get_channel(key)
    if not ch or not ch.get("url"):
        sync_state[key] = {"state": "error", "error": "No address saved for this channel. Open it from Browse once."}
        return sync_state[key]
    with _sync_lock:
        cur = sync_state.get(key, {})
        if cur.get("state") == "checking" and not cur.get("pending"):
            return cur                       # another check of this channel is already running
        sync_state[key] = {"state": "checking", "started": time.time()}
    try:
        cur = settings.get()
        o = dict(opts or ch.get("opts") or {})
        mode = o.get("mode") or cur.get("mode")
        b = list_channel_videos(ch["url"])
        vids = [e for e in b.entries if e.get("kind") == "video" and e.get("vid")
                and e.get("live") not in ("is_live", "is_upcoming")]
        st = library.status_map([e["vid"] for e in vids], cur.get("redownload_deleted"))
        new = [e for e in vids if not st.get(e["vid"], {}).get(mode)]
        res = {"state": "done", "new": len(new), "total": len(vids), "queued": 0, "finished": time.time()}
        if download and new:
            if b.channel and b.channel.get("id") and key.startswith("name:"):
                key = library.upsert_channel(b.channel["id"], b.channel["name"], url=b.channel["url"])
            for e in new:
                e["channel_id"] = e.get("channel_id") or (None if key.startswith("name:") else key)
            r = manager.add([{**e, "group": ch.get("name")} for e in reversed(new)],   # oldest first
                            {**o, "mode": mode} if o else {"mode": mode}, group=ch.get("name"))
            res["queued"] = r["added"]
        library.upsert_channel(None if key.startswith("name:") else key, ch.get("name"),
                               last_sync=time.time(), new_count=0 if download else len(new),
                               thumb=(b.channel or {}).get("thumb") or None)
        sync_state[key] = res
    except Exception as ex:
        sync_state[key] = {"state": "error", "error": clean_error(ex), "finished": time.time()}
    return sync_state[key]


def start_sync(keys, download=True):
    def run():
        for k in keys:
            sync_channel(k, download)
    for k in keys:
        if sync_state.get(k, {}).get("state") != "checking":
            sync_state[k] = {"state": "checking", "started": time.time(), "pending": True}
    threading.Thread(target=run, daemon=True).start()


def _auto_sync_loop():
    """Channels marked "Keep up to date" are checked every few hours; new videos are queued."""
    time.sleep(90)
    while True:
        try:
            hours = float(settings.get().get("sync_hours") or 12)
            due = [c["channel_id"] for c in library.list_channels()
                   if c.get("tracked") and c.get("auto") and time.time() - (c.get("last_sync") or 0) > hours * 3600]
            for k in due:
                sync_channel(k, download=True)
        except Exception as ex:
            print("auto sync:", ex, file=sys.stderr)
        time.sleep(15 * 60)


# --------------------------------------------------------------------------- library migration / scanning
scan_state = {"state": "idle"}


def scan_library(extra_roots=(), report_duplicates=True):
    """Index files on disk (plus old skip lists and download history) into the library."""
    if scan_state.get("state") == "scanning":
        return
    scan_state.clear()
    scan_state.update({"state": "scanning", "found": 0, "started": time.time()})
    try:
        roots = [r for r in _clean_roots(known_roots() + list(extra_roots)) if os.path.isdir(r)]
        imported = 0
        for r in roots:
            for mode in ("audio", "video"):
                imported += library.import_archive(os.path.join(r, f".rit-archive-{mode}.txt"), mode)
        # finished jobs from the download history
        for j in manager.list():
            if j.get("status") in ("done", "skipped") and j.get("filepath") and os.path.isfile(j["filepath"]):
                m = library.ID_IN_NAME.search(os.path.basename(j["filepath"]))
                if m:
                    library.record(m.group(1), library.media_mode(j["filepath"]) or (j.get("opts") or {}).get("mode"),
                                   filepath=j["filepath"], title=j.get("title"), channel=j.get("channel"),
                                   source="history", replace=False)
        found = added = 0
        dupes = []
        for r in roots:
            res = library.scan_folder(r, progress=lambda n: scan_state.update(found=found + n))
            found += res["found"]
            added += res["added"]
            dupes += res["duplicates"]
        library.assign_folders_by_majority()
        library.set_meta("roots", json.dumps(roots))
        scan_state.update({"state": "done", "found": found, "added": added, "imported": imported,
                           "duplicates": dupes, "roots": roots, "finished": time.time()})
    except Exception as ex:
        scan_state.update({"state": "error", "error": str(ex)})


def known_roots():
    """Folders that hold (or held) downloads: current + previous download folders + channel folders."""
    roots = [settings.get()["download_dir"]]
    try:
        roots += json.loads(library.get_meta("roots", "[]"))
    except Exception:
        pass
    for j in manager.list():
        fp = j.get("filepath")
        if fp:
            d = os.path.dirname(fp)
            roots += [d, os.path.dirname(d)]          # the channel folder and the folder above it
    for c in library.list_channels():
        if c.get("folder"):
            roots += [c["folder"], os.path.dirname(c["folder"])]
    return _clean_roots(roots)


def _clean_roots(roots):
    """Drop drive roots / home folder (never scan a whole disk) and folders inside other folders."""
    home = os.path.normcase(os.path.expanduser("~"))
    ok = []
    for r in roots:
        if not r:
            continue
        r = os.path.normpath(r)
        if os.path.dirname(r) == r or os.path.normcase(r) == home or len(r) <= 3:
            continue
        ok.append(r)
    ok = sorted(dict.fromkeys(ok), key=len)
    out = []
    for r in ok:
        if not any(os.path.normcase(r).startswith(os.path.normcase(o) + os.sep) for o in out):
            out.append(r)
    return out


def _first_run_migration():
    if library.get_meta("migrated_v2"):
        return
    s = settings.get()
    if s.get("organize") == "group":
        settings.update({"organize": "channel"})   # one folder per channel is now the default
    scan_library()
    library.set_meta("migrated_v2", time.time())


threading.Thread(target=_first_run_migration, daemon=True).start()
threading.Thread(target=_auto_sync_loop, daemon=True).start()

# --------------------------------------------------------------------------- misc helpers


def pick_folder(initial):
    """Native folder chooser. Runs in a separate process (GUI dialogs need their own main thread)."""
    initial = initial if initial and os.path.isdir(initial) else os.path.expanduser("~")
    if IS_MAC:
        script = f'POSIX path of (choose folder with prompt "Choose download folder" default location (POSIX file "{initial}"))'
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        p = out.stdout.strip()
        return p.rstrip("/") or None if p else None
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    cmd = [sys.executable] if paths.FROZEN else [sys.executable.replace("pythonw.exe", "python.exe"),
                                                 os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")]
    try:
        subprocess.run(cmd + ["--pick-folder", initial, tmp], creationflags=NOWINDOW, timeout=600)
        with open(tmp, encoding="utf-8") as f:
            p = f.read().strip()
    except Exception:
        p = ""
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return os.path.normpath(p) if p else None


def open_path(path, select=False):
    if not path:
        return False
    path = os.path.normpath(path)
    if select and os.path.exists(path):
        if IS_WIN:
            subprocess.Popen(["explorer", "/select,", path])
        elif IS_MAC:
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
        return True
    target = path if os.path.exists(path) else os.path.dirname(path)
    if not os.path.exists(target):
        os.makedirs(target, exist_ok=True)
    if IS_WIN:
        os.startfile(target)
    else:
        subprocess.Popen(["open" if IS_MAC else "xdg-open", target])
    return True


def _urlopen(url, timeout=60):
    import ssl
    import urllib.request
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "RitDownloader-updater"})
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def _download_to(url, dest):
    tmp = dest + ".part"
    with _urlopen(url, 120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    os.replace(tmp, dest)


def update_ytdlp():
    """Source install: pip. Installed app: download the newest yt-dlp (+ solver) into the user folder."""
    if not paths.FROZEN:
        py = sys.executable.replace("pythonw.exe", "python.exe")
        out = subprocess.run([py, "-m", "pip", "install", "-U", "yt-dlp[default]", "yt-dlp-ejs"],
                             capture_output=True, text=True, creationflags=NOWINDOW)
        tail = (out.stdout + out.stderr).strip().splitlines()[-4:]
        return out.returncode == 0, chr(10).join(tail)
    import zipfile
    try:
        with _urlopen("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest") as r:
            rel = json.load(r)
        tag = rel["tag_name"].lstrip("v")
        current = yt_dlp.version.__version__
        msgs = []
        if paths.version_of("x-" + tag) > paths.version_of("x-" + current):
            asset = next(a["browser_download_url"] for a in rel["assets"] if a["name"] == "yt-dlp")
            dest = os.path.join(paths.UPDATES, f"yt-dlp-{tag}.zip")
            _download_to(asset, dest)
            with zipfile.ZipFile(dest) as z:
                if "yt_dlp/version.py" not in z.namelist():
                    os.remove(dest)
                    return False, "Downloaded file was not valid."
            msgs.append(f"yt-dlp {current} -> {tag}")
        with _urlopen("https://pypi.org/pypi/yt-dlp-ejs/json") as r:
            pj = json.load(r)
        ever = pj["info"]["version"]
        whl = next((u for u in pj["urls"] if u["packagetype"] == "bdist_wheel"), None)
        dest = os.path.join(paths.UPDATES, f"yt_dlp_ejs-{ever}-py3-none-any.whl")
        if whl and not os.path.isfile(dest):
            have = [paths.version_of(p) for p in sys.path if "yt_dlp_ejs-" in p]
            if not have or paths.version_of(dest) > max(have):
                _download_to(whl["url"], dest)
                msgs.append(f"solver -> {ever}")
        # remove superseded update files
        for _pkg, pat in paths.PYLIB_PATTERNS:
            import glob
            files = sorted(glob.glob(os.path.join(paths.UPDATES, pat)), key=paths.version_of)
            for old in files[:-1]:
                try:
                    os.remove(old)
                except OSError:
                    pass
        return True, ("Updated: " + ", ".join(msgs)) if msgs else "Already up to date."
    except Exception as ex:
        return False, str(ex)


def install_ffmpeg():
    import setup_ffmpeg
    return setup_ffmpeg.install(lambda m: None)


def system_info():
    s = settings.get()
    return {"ytdlp": yt_dlp.version.__version__, "ffmpeg": have_ffmpeg(),
            "free_gb": free_space_gb(s["download_dir"]), "drives": fixed_drives(),
            "js": bool(js_runtime_args()), "stats": manager.stats(),
            "platform": "mac" if IS_MAC else ("win" if IS_WIN else "linux")}
