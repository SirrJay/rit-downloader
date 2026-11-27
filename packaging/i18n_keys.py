"""Collects every translatable English string from the UI and reports missing translations.

    python packaging/i18n_keys.py          -> writes app/static/i18n/_keys.json, prints coverage per language
"""
import json
import os
import re
from html.parser import HTMLParser

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC = os.path.join(ROOT, "app", "static")
I18N_DIR = os.path.join(STATIC, "i18n")

SKIP_IDS = {"results", "jobs", "fmtBody", "dlStats", "selInfo", "sysinfo", "drives", "rTitle", "rStatus",
            "toasts", "dlDir", "appv", "ytv", "ffv", "updateBanner"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.keys, self.stack = [], []   # stack of (tag, skip, html_capture)
        self.html_buf = None
        self.html_depth = 0

    def skipping(self):
        return any(s for _, s in self.stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.html_buf is not None:
            self.html_buf.append(self.get_starttag_text())
            if tag not in VOID:
                self.html_depth += 1
            return
        skip = tag in ("script", "style", "code") or a.get("id") in SKIP_IDS or "data-no-i18n" in a
        if not (skip or self.skipping()):
            for attr in ("placeholder", "title"):
                if a.get(attr) and re.search(r"[A-Za-z]", a[attr]):
                    self.keys.append(a[attr])
            if "data-i18n-html" in a:
                self.html_buf, self.html_depth = [], 1
                return
        if tag not in VOID:
            self.stack.append((tag, skip))

    def handle_endtag(self, tag):
        if self.html_buf is not None:
            self.html_depth -= 1
            if self.html_depth == 0:
                self.keys.append(re.sub(r"\s+", " ", "".join(self.html_buf)).strip())
                self.html_buf = None
            else:
                self.html_buf.append(f"</{tag}>")
            return
        while self.stack:
            t, _ = self.stack.pop()
            if t == tag:
                break

    def handle_data(self, data):
        if self.html_buf is not None:
            self.html_buf.append(data.replace("&", "&amp;").replace("<", "&lt;"))
            return
        if self.skipping():
            return
        txt = re.sub(r"\s+", " ", data).strip()
        if txt and re.search(r"[A-Za-z]", txt):
            self.keys.append(txt)


def js_keys():
    src = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    keys = []
    for m in re.finditer(r'\bt\(\s*"((?:[^"\\]|\\.)*)"', src):
        keys.append(m.group(1).encode().decode("unicode_escape") if "\\" in m.group(1) else m.group(1))
    for m in re.finditer(r"\bt\(\s*'((?:[^'\\]|\\.)*)'", src):
        keys.append(m.group(1))
    for m in re.finditer(r'\bt\(audio \? "([^"]+)" : "([^"]+)"', src):
        keys += [m.group(1), m.group(2)]
    # tables of labels that are passed through t() at runtime
    for block in ("PLACEHOLDER", "STATUS_LABEL", "AUTH_ERR", "COOKIE_ERR"):
        m = re.search(block + r"\s*=\s*\{(.*?)\};", src, re.S)
        keys += re.findall(r':\s*"([^"]+)"', m.group(1))
    m = re.search(r"const labels = \[(.*?)\];", src, re.S)
    keys += re.findall(r'\["\w+", "([^"]+)"\]', m.group(1))
    keys += re.findall(r'b\("\w+", "([^"]+)"', src)
    # the built-in player has its own script
    psrc = open(os.path.join(STATIC, "player.js"), encoding="utf-8").read()
    keys += re.findall(r'\bt\(\s*"((?:[^"\\]|\\.)*)"', psrc)
    return keys


# Progress messages produced by the download engine (app/engine.py)
ENGINE = ["Starting...", "Downloading video stream", "Downloading audio stream", "Downloading file", "Processing...",
          "Merging video + audio...", "Converting audio...", "Embedding cover art...", "Writing metadata...",
          "Converting video (may take a while)...", "Converting video...", "Remuxing...", "Completed",
          "Already downloaded before (skipped)", "Already downloaded (skipped)", "Already exists", "Paused",
          "Paused (app was closed)", "Canceled", "Failed"]


# Brand / technical strings that stay the same in every language (fall back to English).
SAME_IN_ALL = {"Rit Downloader", "Rit", "Downloader", "YouTube", "SoundCloud", "Bilibili", "Niconico", "MP4", "MKV",
               "WebM", "MP3", "Opus", "AAC", "OGG Vorbis", "M4A (AAC)", "Microsoft Edge", "Google Chrome", "Firefox",
               "Brave", "Opera", "1440p", "480p", "240p", "144p", "4K (2160p)", "Full HD (1080p)", "HD (720p)",
               "320 kbps", "256 kbps", "192 kbps", "96 kbps", "500 KB/s", "1 MB/s", "2 MB/s", "5 MB/s", "en.*,fr",
               "Shorts", "{h} h {m} min", "{m} min", "Codec", "App", "Video", "Audio", "Playlist", "Playlists",
               "Date", "Source", "Bitrate", "Grid", "1 item", "LIVE", "Error", "Pause", "Downloads", "Videos",
               "Channel", "audio", "stream", "Downloading", "5 minutes", "15 minutes", "30 minutes",
               "Vivaldi", "1 GB", "2 GB", "5 GB", "10 GB", "20 GB", "http://host:port"}


def engine_keys():
    """Plain-language error and status messages produced by app/engine.py (shown through t())."""
    src = open(os.path.join(ROOT, "app", "engine.py"), encoding="utf-8").read()
    m = re.search(r"ERROR_RULES = \[(.*?)\n\]", src, re.S)
    keys = re.findall(r'"([A-Z][^"]+\.)"\),', m.group(1)) if m else []
    for line in src.splitlines():                 # status lines shown in the Downloads list
        if ".stage" in line and "=" in line and "Merger" not in line:
            keys += [k for k in re.findall(r'"([^"]+)"', line) if k[:1].isupper()]
    return [k for k in keys if "{" not in k]


def collect():
    c = Collector()
    c.feed(open(os.path.join(STATIC, "index.html"), encoding="utf-8").read())
    seen, out = set(), []
    for k in c.keys + js_keys() + ENGINE + engine_keys():
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


if __name__ == "__main__":
    keys = collect()
    os.makedirs(I18N_DIR, exist_ok=True)
    with open(os.path.join(I18N_DIR, "_keys.json"), "w", encoding="utf-8") as f:
        json.dump(keys, f, ensure_ascii=False, indent=1)
    print(len(keys), "strings")
    for fn in sorted(os.listdir(I18N_DIR)):
        if fn.startswith("_") or not fn.endswith(".json"):
            continue
        d = json.load(open(os.path.join(I18N_DIR, fn), encoding="utf-8"))
        missing = [k for k in keys if not d.get(k) and k not in SAME_IN_ALL]
        bad_vars = [k for k in keys if d.get(k) and set(re.findall(r"\{\w+\}", k)) != set(re.findall(r"\{\w+\}", d[k]))]
        print(f"{fn}: {len(keys) - len(missing)}/{len(keys)}"
              + (f"  missing: {missing[:5]}" if missing else "") + (f"  BAD PLACEHOLDERS: {bad_vars[:5]}" if bad_vars else ""))
