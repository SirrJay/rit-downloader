"""Local app lock: one account per computer, salted scrypt password hash, cookie sessions.

This keeps other people who use the same computer out of the app. It is not encryption:
someone with access to the Windows/macOS user account can delete auth.json to reset it.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from paths import DATA

AUTH_FILE = os.path.join(DATA, "auth.json")
COOKIE = "rit_session"
REMEMBER_DAYS = 30

_lock = threading.Lock()
_sessions = {}          # token -> {"user", "last", "remember"}
_fails = {"count": 0, "until": 0.0}


def _hash(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32).hex()


def _load():
    try:
        with open(AUTH_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save(d):
    tmp = AUTH_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, AUTH_FILE)


def status(token):
    d = _load()
    if d is None:
        return {"setup": True, "authed": False}
    if not d.get("enabled", True):
        return {"setup": False, "authed": True, "user": d.get("user"), "enabled": False,
                "auto_lock": d.get("auto_lock", 0)}
    return {"setup": False, "authed": check(token), "user": d.get("user") if check(token) else None,
            "hint": d.get("hint", ""), "enabled": True, "auto_lock": d.get("auto_lock", 0)}


def _validate(user, password):
    user = (user or "").strip()
    if not 1 <= len(user) <= 40:
        return "bad_user"
    if len(password or "") < 4:
        return "short_password"
    return None


def setup(user, password, hint=""):
    with _lock:
        if _load() is not None:
            return None, "exists"
        err = _validate(user, password)
        if err:
            return None, err
        salt = secrets.token_hex(16)
        _save({"user": user.strip(), "salt": salt, "hash": _hash(password, salt), "hint": (hint or "")[:80],
               "enabled": True, "auto_lock": 0, "remember": []})
    return _new_session(user.strip(), False), None


def login(user, password, remember=False):
    now = time.time()
    if now < _fails["until"]:
        return None, "wait", int(_fails["until"] - now) + 1
    d = _load()
    if not d:
        return None, "no_account", 0
    ok = hmac.compare_digest(d.get("user", "").lower(), (user or "").strip().lower()) & \
        hmac.compare_digest(d["hash"], _hash(password or "", d["salt"]))
    if not ok:
        _fails["count"] += 1
        if _fails["count"] >= 5:
            _fails["until"] = now + 30
            _fails["count"] = 0
        return None, "invalid", 0
    _fails["count"] = 0
    token = _new_session(d["user"], remember)
    if remember:
        with _lock:
            d = _load()
            keep = [r for r in d.get("remember", []) if r["exp"] > now][-9:]
            keep.append({"h": hashlib.sha256(token.encode()).hexdigest(), "exp": now + REMEMBER_DAYS * 86400})
            d["remember"] = keep
            _save(d)
    return token, None, 0


def _new_session(user, remember):
    token = secrets.token_urlsafe(32)
    _sessions[token] = {"user": user, "last": time.time(), "remember": remember}
    return token


def check(token, touch=False):
    d = _load()
    if d is None:
        return False
    if not d.get("enabled", True):
        return True
    if not token:
        return False
    s = _sessions.get(token)
    now = time.time()
    if s is None:
        # a "keep me signed in" token survives app restarts
        h = hashlib.sha256(token.encode()).hexdigest()
        if any(hmac.compare_digest(r["h"], h) and r["exp"] > now for r in d.get("remember", [])):
            s = _sessions[token] = {"user": d["user"], "last": now, "remember": True}
        else:
            return False
    auto = int(d.get("auto_lock") or 0)
    if auto and not s["remember"] and now - s["last"] > auto * 60:
        _sessions.pop(token, None)
        return False
    if touch:
        s["last"] = now
    return True


def any_session():
    """True when the app is unlocked in at least one window (used for the browser extension)."""
    d = _load()
    if d is None or not d.get("enabled", True):
        return d is not None
    auto = int(d.get("auto_lock") or 0)
    now = time.time()
    return any(s["remember"] or not auto or now - s["last"] <= auto * 60 for s in _sessions.values())


def logout(token):
    _sessions.pop(token, None)
    if token:
        h = hashlib.sha256(token.encode()).hexdigest()
        with _lock:
            d = _load()
            if d and d.get("remember"):
                d["remember"] = [r for r in d["remember"] if r["h"] != h]
                _save(d)


def update(token, current, changes):
    """Change username / password / hint / auto-lock / enabled. Requires the current password."""
    with _lock:
        d = _load()
        if not d:
            return "no_account"
        if not hmac.compare_digest(d["hash"], _hash(current or "", d["salt"])):
            return "invalid"
        if "user" in changes:
            err = _validate(changes["user"], "xxxx")
            if err:
                return err
            d["user"] = changes["user"].strip()
        if changes.get("password"):
            if len(changes["password"]) < 4:
                return "short_password"
            d["salt"] = secrets.token_hex(16)
            d["hash"] = _hash(changes["password"], d["salt"])
            d["remember"] = []                      # sign out other "remembered" windows
            for t in [t for t in _sessions if t != token]:
                _sessions.pop(t, None)
        if "hint" in changes:
            d["hint"] = (changes["hint"] or "")[:80]
        if "enabled" in changes:
            d["enabled"] = bool(changes["enabled"])
        _save(d)
    return None


def set_auto_lock(minutes):
    with _lock:
        d = _load()
        if d:
            d["auto_lock"] = int(minutes)
            _save(d)
