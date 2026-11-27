"""Direct file downloads (software installers, archives, documents...).

- probe(url): is this a direct file? name, size, type, resumable?
- scan_page(url): find download links (installers, archives...) on a software website page
- download(...): segmented (several connections), resumable, verified, SHA-256, Windows "mark of the web"
"""
import hashlib
import json
import os
import re
import threading
import time
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0 Safari/537.36")
FILE_EXT = ("exe", "msi", "msix", "msixbundle", "appx", "appxbundle", "zip", "7z", "rar", "tar", "gz", "tgz", "bz2", "xz",
            "dmg", "pkg", "iso", "img", "apk", "aab", "xapk", "deb", "rpm", "appimage", "flatpak", "snap", "jar",
            "pdf", "epub", "docx", "xlsx", "pptx", "csv", "txt", "bin", "torrent", "cab", "vsix", "crx", "xpi",
            "mp3", "mp4", "mkv", "wav", "flac", "m4a", "mov", "avi", "webm")
EXECUTABLE = {"exe", "msi", "msix", "msixbundle", "appx", "appxbundle", "dmg", "pkg", "apk", "jar", "deb", "rpm",
              "appimage", "bat", "cmd", "ps1", "vbs", "scr"}
HTML_TYPES = ("text/html", "application/xhtml")


class Stopped(Exception):
    pass


def _session(page=False):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
    if page:
        s.headers.update({"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                          "Upgrade-Insecure-Requests": "1", "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
                          "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1"})
    return s


GH_REPO = re.compile(r"^https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)(?:/|$)", re.I)


def github_assets(url, timeout=20):
    """Files of the latest release of a GitHub project (most open-source software is published there)."""
    m = GH_REPO.match(url)
    if not m or m.group(1).lower() in ("orgs", "settings", "topics", "features", "marketplace", "sponsors"):
        return None
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    tag = re.search(r"/releases/tag/([^/?#]+)", url)
    api = f"https://api.github.com/repos/{owner}/{repo}/releases/" + (f"tags/{tag.group(1)}" if tag else "latest")
    r = _session().get(api, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
    if r.status_code != 200:
        return None
    rel = r.json()
    links = [{"url": a["browser_download_url"], "name": a["name"], "text": rel.get("name") or rel.get("tag_name") or "",
              "ext": ext_of(a["name"]), "executable": ext_of(a["name"]).split(".")[-1] in EXECUTABLE,
              "host": "github.com", "size": a.get("size")} for a in rel.get("assets") or []]
    return {"title": f"{repo} {rel.get('tag_name') or ''}".strip(), "links": links, "final_url": rel.get("html_url") or url}


def ext_of(name):
    n = (name or "").lower()
    for double in ("tar.gz", "tar.xz", "tar.bz2"):
        if n.endswith("." + double):
            return double
    return n.rsplit(".", 1)[-1] if "." in n else ""


def looks_like_file_url(url):
    path = unquote(urlparse(url).path or "")
    return ext_of(path).split(".")[-1] in FILE_EXT


def _name_from_headers(resp, url):
    cd = resp.headers.get("Content-Disposition") or ""
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", cd, re.I)
    if m:
        name = unquote(m.group(1).strip().strip('"'))
    else:
        m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
        name = m.group(1).strip() if m else ""
    if not name:
        name = unquote(os.path.basename(urlparse(resp.url or url).path)) or "download"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "download"
    return name[:180]


def probe(url, timeout=20):
    """Look at a link without downloading it. Returns a dict describing it."""
    s = _session()
    info = {"url": url, "final_url": url, "name": "", "size": None, "mime": "", "ranges": False, "is_file": False,
            "html": False, "host": urlparse(url).hostname or ""}
    r = None
    try:
        r = s.head(url, allow_redirects=True, timeout=timeout)
        if r.status_code >= 400 or not r.headers.get("Content-Type"):
            raise requests.RequestException("HEAD not usable")
    except requests.RequestException:
        r = s.get(url, stream=True, allow_redirects=True, timeout=timeout, headers={"Range": "bytes=0-0"})
    try:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        info["final_url"] = r.url or url
        info["mime"] = ctype
        info["name"] = _name_from_headers(r, url)
        size = r.headers.get("Content-Length")
        cr = r.headers.get("Content-Range")
        if cr and "/" in cr:
            tail = cr.rsplit("/", 1)[-1]
            size = tail if tail.isdigit() else size
            info["ranges"] = True
        if size and str(size).isdigit() and (int(size) > 1 or not cr):
            info["size"] = int(size)
        info["ranges"] = info["ranges"] or "bytes" in (r.headers.get("Accept-Ranges") or "").lower()
        info["html"] = ctype.startswith(HTML_TYPES)
        disp = "attachment" in (r.headers.get("Content-Disposition") or "").lower()
        info["is_file"] = (not info["html"] and ctype not in ("", "text/plain", "application/json")) or disp \
            or (not info["html"] and looks_like_file_url(info["final_url"]))
        if info["is_file"] and info["size"] is None and not info["ranges"]:
            info["size"] = None
    finally:
        r.close()
    info["ext"] = ext_of(info["name"])
    info["executable"] = info["ext"].split(".")[-1] in EXECUTABLE
    return info


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self._a, self._txt = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._a, self._txt = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self._a is not None:
            self._txt.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._a is not None:
            self.links.append((self._a, " ".join("".join(self._txt).split())))
            self._a = None


def scan_page(url, limit=150, timeout=25, deep=True):
    """Find links to downloadable files on a web page (e.g. a software download page).
    Also reads GitHub releases, and follows "download" links one level deep when a page has no files itself."""
    gh = github_assets(url)
    if gh and gh["links"]:
        return gh
    s = _session(page=True)
    r = s.get(url, timeout=timeout)
    r.raise_for_status()
    html = r.text[:3_000_000]
    p = _Links()
    try:
        p.feed(html)
    except Exception:
        pass
    seen, out = set(), []
    base = r.url or url
    for href, text in p.links:
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        absu = urljoin(base, href.strip())
        if absu in seen or not absu.startswith(("http://", "https://")):
            continue
        name = unquote(os.path.basename(urlparse(absu).path))
        e = ext_of(name)
        if e.split(".")[-1] not in FILE_EXT or e.split(".")[-1] in ("mp3", "mp4", "mkv", "wav", "flac", "m4a", "mov", "avi", "webm", "txt", "csv"):
            continue
        seen.add(absu)
        out.append({"url": absu, "name": name, "text": text[:120], "ext": e,
                    "executable": e.split(".")[-1] in EXECUTABLE, "host": urlparse(absu).hostname or ""})
        if len(out) >= limit:
            break
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = " ".join(title.group(1).split())[:150] if title else (urlparse(base).hostname or url)
    if not out and deep:
        # no files on this page: follow its "download" links (same site, or GitHub releases) one level deep
        host = (urlparse(base).hostname or "").lower().removeprefix("www.")
        cands, seen2 = [], set()
        for href, text in p.links:
            if not href or href.startswith(("javascript:", "mailto:", "#")):
                continue
            absu = urljoin(base, href.strip()).split("#")[0]
            h = (urlparse(absu).hostname or "").lower().removeprefix("www.")
            same = h == host or h.endswith("." + host)
            if absu in seen2 or absu.rstrip("/") == base.rstrip("/") or not (same or GH_REPO.match(absu)):
                continue
            hint = (text + " " + absu).lower()
            if "download" in hint or "release" in hint or re.search(r"/v?\d+\.\d+", urlparse(absu).path):
                seen2.add(absu)
                cands.append(absu)
        for c in cands[:8]:
            try:
                sub = scan_page(c, limit=limit, timeout=timeout, deep=False)
            except Exception:
                continue
            for l in sub["links"]:
                if l["url"] not in seen:
                    seen.add(l["url"])
                    out.append(l)
            if len(out) >= 3:
                break
    return {"title": title, "links": out[:limit], "final_url": base}


def unique_path(folder, name):
    base, dot, ext = name.rpartition(".")
    if not dot:
        base, ext = name, ""
    path = os.path.join(folder, name)
    i = 2
    while os.path.exists(path) or os.path.exists(path + ".ripart"):
        path = os.path.join(folder, f"{base} ({i}).{ext}" if ext else f"{base} ({i})")
        i += 1
    return path


def sha256_of(path, stop=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            if stop and stop():
                raise Stopped()
            b = f.read(4 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def mark_of_the_web(path, url, referrer=None):
    """Windows: tag the file as downloaded from the internet, so SmartScreen / Office still check it."""
    if os.name != "nt":
        return
    try:
        with open(path + ":Zone.Identifier", "w", encoding="utf-8") as f:
            f.write("[ZoneTransfer]\r\nZoneId=3\r\n")
            if referrer:
                f.write(f"ReferrerUrl={referrer}\r\n")
            f.write(f"HostUrl={url}\r\n")
    except OSError:
        pass


def download(url, dest, *, connections=4, progress=None, stop=None, rate_limit=None, proxy=None, referrer=None):
    """Download url to dest (final name). Resumable: progress is kept in dest.ripart + dest.ripart.json.
    progress(done, total, speed); stop() -> True to pause/cancel. Returns final path."""
    part, state_file = dest + ".ripart", dest + ".ripart.json"
    s = _session()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    if referrer:
        s.headers["Referer"] = referrer
    state = None
    if os.path.exists(part) and os.path.exists(state_file):
        try:
            state = json.load(open(state_file, encoding="utf-8"))
            if state.get("url") != url:
                state = None
        except Exception:
            state = None
    if state is None:
        info = probe(url)
        size, ranges = info["size"], info["ranges"]
        url = info["final_url"] or url
        n = max(1, min(16, int(connections or 1))) if (ranges and size and size >= 4 << 20) else 1
        if n > 1:
            step = size // n
            segs = [[i * step, (size - 1) if i == n - 1 else (i + 1) * step - 1, 0] for i in range(n)]
        else:
            segs = [[0, (size - 1) if size else -1, 0]]
        state = {"url": url, "size": size, "ranges": bool(ranges), "segments": segs}
        with open(part, "wb") as f:
            if size and n > 1:
                f.truncate(size)
    elif not state.get("ranges"):
        # server cannot resume: start again
        for seg in state["segments"]:
            seg[2] = 0
        open(part, "wb").close()

    lock = threading.Lock()
    size = state["size"]
    errors = []
    t0, last_save = time.time(), 0
    done0 = sum(sg[2] for sg in state["segments"])
    bucket = {"t": time.time(), "bytes": 0}

    def save_state():
        tmp = state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, state_file)

    def worker(seg):
        start, end = seg[0], seg[1]
        tries = 0
        while True:
            if not state["ranges"] and seg[2]:
                # this server cannot continue a broken download: start the file again from zero
                with lock:
                    seg[2] = 0
                open(part, "wb").close()
            pos = start + seg[2]
            if end >= 0 and pos > end:
                return
            headers = {}
            if state["ranges"] and (pos > 0 or end >= 0) and size:
                headers["Range"] = f"bytes={pos}-{end}"
            try:
                with s.get(url, stream=True, timeout=30, headers=headers) as r:
                    if r.status_code == 200 and headers.get("Range") and pos > 0:
                        raise IOError("server ignored resume request")
                    r.raise_for_status()
                    with open(part, "r+b" if os.path.getsize(part) else "wb") as f:
                        f.seek(pos)
                        for chunk in r.iter_content(256 * 1024):
                            if stop and stop():
                                raise Stopped()
                            if not chunk:
                                continue
                            if end >= 0:
                                chunk = chunk[: end - (start + seg[2]) + 1]
                            f.write(chunk)
                            with lock:
                                seg[2] += len(chunk)
                                bucket["bytes"] += len(chunk)
                            if rate_limit:
                                _throttle(bucket, rate_limit / max(1, len(state["segments"])))
                            if end >= 0 and start + seg[2] > end:
                                break
                if end < 0 or start + seg[2] > end:
                    return
            except Stopped:
                raise
            except Exception as ex:
                tries += 1
                if tries > 6:
                    errors.append(ex)
                    return
                time.sleep(min(30, 2 ** tries))

    threads = []
    stop_err = []
    for seg in state["segments"]:
        def run(sg=seg):
            try:
                worker(sg)
            except Stopped:
                stop_err.append(True)
        th = threading.Thread(target=run, daemon=True)
        th.start()
        threads.append(th)
    while any(th.is_alive() for th in threads):
        time.sleep(0.5)
        done = sum(sg[2] for sg in state["segments"])
        el = max(0.5, time.time() - t0)
        if progress:
            progress(done, size, (done - done0) / el)
        if time.time() - last_save > 2:
            last_save = time.time()
            with lock:
                save_state()
    with lock:
        save_state()
    if stop_err:
        raise Stopped()
    if errors:
        raise errors[0]
    done = sum(sg[2] for sg in state["segments"])
    if size and done < size:
        raise IOError(f"download incomplete ({done} of {size} bytes)")
    final = dest
    if os.path.exists(final):
        final = unique_path(os.path.dirname(dest), os.path.basename(dest))
    os.replace(part, final)
    try:
        os.remove(state_file)
    except OSError:
        pass
    mark_of_the_web(final, url, referrer)
    return final


def _throttle(bucket, bps):
    now = time.time()
    el = now - bucket["t"]
    if el >= 1:
        bucket["t"], bucket["bytes"] = now, 0
        return
    if bucket["bytes"] > bps * el:
        time.sleep(min(1.0, bucket["bytes"] / bps - el))
