"""Download library: remembers every file ever downloaded (across all folders) and which folder each
channel uses, so already-downloaded videos are skipped and new ones go to the channel's own folder.

Storage: SQLite (library.db in the user data folder). Thread-safe through a single lock.
"""
import json
import os
import re
import sqlite3
import threading
import time

from paths import DATA

DB_FILE = os.path.join(DATA, "library.db")

AUDIO_EXT = {"mp3", "m4a", "opus", "ogg", "oga", "flac", "wav", "aac", "mka", "alac", "aiff"}
VIDEO_EXT = {"mp4", "mkv", "webm", "mov", "avi", "flv", "m4v", "3gp", "ts"}
# "...Title [VIDEOID].ext" - the naming scheme used by Rit Downloader and yt-dlp's default template
ID_IN_NAME = re.compile(r"\[([0-9A-Za-z_-]{6,64})\]\.([0-9A-Za-z]{2,5})$")

_lock = threading.RLock()
_conn = None


def _db():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=30)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript("""
            CREATE TABLE IF NOT EXISTS downloads(
                video_id TEXT NOT NULL, mode TEXT NOT NULL, extractor TEXT, filepath TEXT, title TEXT,
                channel_id TEXT, channel TEXT, upload_date TEXT, size INTEGER, source TEXT, created REAL,
                PRIMARY KEY(video_id, mode));
            CREATE INDEX IF NOT EXISTS ix_dl_channel ON downloads(channel_id);
            CREATE TABLE IF NOT EXISTS channels(
                channel_id TEXT PRIMARY KEY, name TEXT, folder TEXT, url TEXT, thumb TEXT,
                tracked INTEGER DEFAULT 0, auto INTEGER DEFAULT 0, opts TEXT,
                last_sync REAL, new_count INTEGER, created REAL);
            CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        """)
        _conn.commit()
    return _conn


def media_mode(path):
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext in AUDIO_EXT:
        return "audio"
    if ext in VIDEO_EXT:
        return "video"
    return None


def safe_folder_name(name):
    from yt_dlp.utils import sanitize_filename
    n = sanitize_filename(name or "", restricted=False).strip().rstrip(".").strip()
    return n[:80] or "Unknown channel"


# --------------------------------------------------------------------------- meta flags
def get_meta(k, default=None):
    with _lock:
        r = _db().execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def set_meta(k, v):
    with _lock:
        _db().execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)", (k, str(v)))
        _db().commit()


# --------------------------------------------------------------------------- downloads
def record(video_id, mode, *, extractor=None, filepath=None, title=None, channel_id=None, channel=None,
           upload_date=None, source="download", replace=True):
    if not video_id or mode not in ("audio", "video"):
        return
    size = None
    if filepath and os.path.isfile(filepath):
        try:
            size = os.path.getsize(filepath)
        except OSError:
            pass
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    with _lock:
        _db().execute(f"""{verb} INTO downloads(video_id, mode, extractor, filepath, title, channel_id, channel,
                          upload_date, size, source, created) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      (video_id, mode, (extractor or "").lower() or None, filepath, title, channel_id, channel,
                       upload_date, size, source, time.time()))
        _db().commit()


def _file_ok(row):
    fp = row["filepath"]
    return (not fp) or os.path.isfile(fp)   # unknown path (imported archive) counts as present


def status_map(video_ids, redownload_deleted=False):
    """{video_id: {"audio": bool, "video": bool}} for the given ids (only ids found are returned)."""
    ids = [v for v in dict.fromkeys(video_ids) if v]
    out = {}
    with _lock:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = f"SELECT video_id, mode, filepath FROM downloads WHERE video_id IN ({','.join('?' * len(chunk))})"
            for r in _db().execute(q, chunk):
                if redownload_deleted and not _file_ok(r):
                    continue
                out.setdefault(r["video_id"], {"audio": False, "video": False})[r["mode"]] = True
    return out


def is_downloaded(video_id, mode, redownload_deleted=False):
    if not video_id:
        return None
    with _lock:
        r = _db().execute("SELECT filepath FROM downloads WHERE video_id=? AND mode=?", (video_id, mode)).fetchone()
    if not r:
        return None
    if redownload_deleted and not _file_ok(r):
        return None
    return r["filepath"] or True


def forget(video_id, mode=None):
    with _lock:
        if mode:
            _db().execute("DELETE FROM downloads WHERE video_id=? AND mode=?", (video_id, mode))
        else:
            _db().execute("DELETE FROM downloads WHERE video_id=?", (video_id,))
        _db().commit()


def totals():
    with _lock:
        r = _db().execute("SELECT COUNT(*) n, COALESCE(SUM(size),0) s FROM downloads").fetchone()
        c = _db().execute("""SELECT COUNT(*) n FROM channels c WHERE tracked=1 OR EXISTS
                             (SELECT 1 FROM downloads d WHERE d.channel_id=c.channel_id)""").fetchone()
    return {"files": r["n"], "bytes": r["s"], "channels": c["n"]}


# --------------------------------------------------------------------------- channels
def _channel_key(channel_id, name):
    return channel_id or ("name:" + (name or "Unknown channel"))


def get_channel(key):
    with _lock:
        r = _db().execute("SELECT * FROM channels WHERE channel_id=?", (key,)).fetchone()
    return _ch_dict(r) if r else None


def _ch_dict(r):
    d = dict(r)
    try:
        d["opts"] = json.loads(d["opts"]) if d.get("opts") else None
    except Exception:
        d["opts"] = None
    return d


def _merge_pseudo(real_id, name, folder=None):
    """A channel first seen only by folder name (from a disk scan) becomes the real channel."""
    pseudo = "name:" + (name or "")
    with _lock:
        db = _db()
        p = db.execute("SELECT * FROM channels WHERE channel_id=?", (pseudo,)).fetchone()
        if not p and folder:
            p = db.execute("SELECT * FROM channels WHERE channel_id LIKE 'name:%' AND folder=?", (folder,)).fetchone()
        if not p:
            return None
        db.execute("UPDATE downloads SET channel_id=? WHERE channel_id=?", (real_id, p["channel_id"]))
        db.execute("DELETE FROM channels WHERE channel_id=?", (p["channel_id"],))
        db.commit()
        return dict(p)


def upsert_channel(channel_id, name=None, *, url=None, thumb=None, folder=None, tracked=None, auto=None,
                   opts=None, last_sync=None, new_count=None):
    key = _channel_key(channel_id, name)
    with _lock:
        db = _db()
        row = db.execute("SELECT * FROM channels WHERE channel_id=?", (key,)).fetchone()
        if not row and channel_id:
            carried = _merge_pseudo(channel_id, name)
            if carried:
                folder = folder or carried.get("folder")
                tracked = tracked if tracked is not None else carried.get("tracked")
                auto = auto if auto is not None else carried.get("auto")
                opts = opts if opts is not None else (json.loads(carried["opts"]) if carried.get("opts") else None)
        if not row:
            db.execute("INSERT INTO channels(channel_id, name, created, tracked, auto) VALUES(?,?,?,0,0)",
                       (key, name or "", time.time()))
        sets, vals = [], []
        for col, val in (("name", name), ("url", url), ("thumb", thumb), ("folder", folder),
                         ("tracked", None if tracked is None else int(bool(tracked))),
                         ("auto", None if auto is None else int(bool(auto))),
                         ("opts", None if opts is None else json.dumps(opts)),
                         ("last_sync", last_sync), ("new_count", new_count)):
            if val is not None and val != "":
                sets.append(f"{col}=?")
                vals.append(val)
        if sets:
            db.execute(f"UPDATE channels SET {', '.join(sets)} WHERE channel_id=?", (*vals, key))
        db.commit()
    return key


def channel_folder(channel_id, name, base_dir):
    """Absolute folder for a channel. Chosen once and then kept, even if the download folder setting
    changes later, so each channel's videos always stay together."""
    key = _channel_key(channel_id, name)
    ch = get_channel(key)
    if not ch and channel_id:
        upsert_channel(channel_id, name)        # merges a matching folder-name entry from a disk scan
        ch = get_channel(key)
    if ch and ch.get("folder"):
        return ch["folder"]
    folder = os.path.join(base_dir, safe_folder_name(name))
    with _lock:
        other = _db().execute("SELECT channel_id FROM channels WHERE folder=? AND channel_id<>?",
                              (folder, key)).fetchone()
    if other and not other["channel_id"].startswith("name:"):
        # two different channels with the same name: keep them apart
        folder = f"{folder} ({(channel_id or 'x')[-6:]})"
    upsert_channel(channel_id, name, folder=folder)
    return folder


def list_channels():
    with _lock:
        rows = _db().execute("""
            SELECT c.*,
              (SELECT COUNT(*) FROM downloads d WHERE d.channel_id=c.channel_id AND d.mode='audio') n_audio,
              (SELECT COUNT(*) FROM downloads d WHERE d.channel_id=c.channel_id AND d.mode='video') n_video,
              (SELECT COALESCE(SUM(size),0) FROM downloads d WHERE d.channel_id=c.channel_id) bytes,
              (SELECT MAX(created) FROM downloads d WHERE d.channel_id=c.channel_id) last_download
            FROM channels c""").fetchall()
    out = [_ch_dict(r) for r in rows]
    out = [c for c in out if c["tracked"] or c["n_audio"] or c["n_video"]]
    out.sort(key=lambda c: (-(c["tracked"] or 0), -(c["last_download"] or 0), (c["name"] or "").lower()))
    return out


def remove_channel(key):
    """Forget a channel's settings. Download history (and the files) are kept."""
    with _lock:
        _db().execute("UPDATE channels SET tracked=0, auto=0 WHERE channel_id=?", (key,))
        _db().commit()


# --------------------------------------------------------------------------- import / scan
def import_archive(path, mode):
    """yt-dlp archive file ('youtube VIDEOID' per line) from earlier versions."""
    n = 0
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    record(parts[1], mode, extractor=parts[0], source="archive", replace=False)
                    n += 1
    except OSError:
        pass
    return n


def scan_folder(root, progress=None, stop=None):
    """Index media files named '... [ID].ext' under root. Returns counts and any duplicate copies found."""
    found = added = 0
    dupes = []
    by_folder = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if not d.startswith(".")]
        for f in fn:
            if stop and stop():
                return {"found": found, "added": added, "duplicates": dupes}
            m = ID_IN_NAME.search(f)
            if not m:
                continue
            path = os.path.join(dp, f)
            mode = media_mode(f)
            if not mode or f.endswith((".part", ".ytdl")):
                continue
            vid = m.group(1)
            found += 1
            folder_name = os.path.basename(dp) if os.path.normcase(dp) != os.path.normcase(root) else None
            with _lock:
                row = _db().execute("SELECT filepath, channel_id FROM downloads WHERE video_id=? AND mode=?",
                                    (vid, mode)).fetchone()
            if row and row["filepath"] and os.path.normcase(row["filepath"]) != os.path.normcase(path) \
                    and os.path.isfile(row["filepath"]):
                dupes.append({"video_id": vid, "mode": mode, "kept": row["filepath"], "copy": path,
                              "size": os.path.getsize(path)})
                continue
            ch_id = row["channel_id"] if row and row["channel_id"] else (("name:" + folder_name) if folder_name else None)
            title = re.sub(r"^\d{4}-\d{2}-\d{2} - ", "", f[: m.start()]).strip()
            record(vid, mode, filepath=path, title=title, channel_id=ch_id, channel=folder_name, source="scan")
            if not row:
                added += 1
            if folder_name:
                by_folder.setdefault((ch_id, folder_name, dp), 0)
                by_folder[(ch_id, folder_name, dp)] += 1
            if progress and found % 50 == 0:
                progress(found)
    # give folder-only channels a folder (the one holding most of their files)
    best = {}
    for (ch_id, name, dp), n in by_folder.items():
        if ch_id and (ch_id not in best or n > best[ch_id][1]):
            best[ch_id] = (name, n, dp)
    for ch_id, (name, _n, dp) in best.items():
        ch = get_channel(ch_id)
        if not ch:
            if ch_id.startswith("name:"):
                upsert_channel(None, name, folder=dp)
        elif not ch.get("folder"):
            upsert_channel(None if ch_id.startswith("name:") else ch_id, ch.get("name") or name, folder=dp)
    return {"found": found, "added": added, "duplicates": dupes}


def assign_folders_by_majority():
    """Channels found by scanning: use the folder that holds most of their files as their home."""
    with _lock:
        db = _db()
        chans = db.execute("SELECT channel_id FROM channels WHERE channel_id LIKE 'name:%' OR folder IS NULL OR folder=''").fetchall()
        for c in chans:
            counts = {}
            for r in db.execute("SELECT filepath FROM downloads WHERE channel_id=? AND filepath IS NOT NULL", (c["channel_id"],)):
                d = os.path.dirname(r["filepath"])
                counts[d] = counts.get(d, 0) + 1
            if counts:
                db.execute("UPDATE channels SET folder=? WHERE channel_id=?", (max(counts, key=counts.get), c["channel_id"]))
        db.commit()


def find_duplicates(roots):
    """Read-only: every extra copy of an already-indexed video across the given folders."""
    dupes = []
    seen = {}
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if not d.startswith(".")]
            for f in fn:
                m = ID_IN_NAME.search(f)
                mode = media_mode(f) if m else None
                if not mode:
                    continue
                key = (m.group(1), mode)
                path = os.path.join(dp, f)
                if key in seen:
                    dupes.append({"video_id": key[0], "mode": mode, "kept": seen[key], "copy": path,
                                  "size": os.path.getsize(path)})
                else:
                    seen[key] = path
    return dupes
