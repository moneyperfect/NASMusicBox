"""Playback metadata policies, bounded prefix cache and concurrent work sharing.

No player or network state lives on disk here. Persisted sessions contain only
track metadata; short-lived signed media URLs must always be resolved again.
"""
from __future__ import annotations

from concurrent.futures import Future
import hashlib
import math
import re
import threading
import time
import unicodedata
from urllib.parse import parse_qs, urlparse


class SingleFlight:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {}

    def run(self, key, work):
        with self._lock:
            future = self._pending.get(key)
            owner = future is None
            if owner:
                future = Future()
                self._pending[key] = future
        if not owner:
            return future.result()
        try:
            result = work()
            future.set_result(result)
            return result
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._pending.pop(key, None)


VERSION_TERMS = {
    "live": r"\blive\b|\bconcert\b|现场|演唱会",
    "cover": r"\bcover\b|翻唱|翻奏",
    "remix": r"\bremix\b|\bdj\b|混音|混剪|串烧|加速|慢速|sped.?up|slowed",
    "instrumental": r"\binstrumental\b|\bkaraoke\b|伴奏|纯音乐|无人声",
    "acoustic": r"\bacoustic\b|不插电|木吉他版",
    "demo": r"\bdemo\b|试听版|样带",
}


def normalized_text(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(c for c in text if c.isalnum())


def track_signature(item):
    title = str(item.get("title") or "").strip()
    artist = str(item.get("artist") or item.get("uploader") or item.get("channel") or "").strip()
    if not title or not artist or normalized_text(artist) in {
        "unknown", "unknownartist", "未知", "未知歌手", "variousartists", "群星"
    }:
        return None
    # Only known catalogue suffixes are removed. Arbitrary uploader channels
    # are not treated as performers and arbitrary parenthetical versions stay.
    artist = re.sub(r"\s*[-–—]?\s*(?:topic|vevo|official(?: channel)?)$", "", artist, flags=re.I).strip()
    if not artist:
        return None
    lowered = unicodedata.normalize("NFKC", title).casefold()
    versions = tuple(key for key, pattern in VERSION_TERMS.items() if re.search(pattern, lowered, re.I))
    # YouTube often prefixes the verified artist. Do not split arbitrary '-'.
    prefixed = re.match(r"^(.+?)\s+[-–—]\s+(.+)$", title)
    if prefixed and normalized_text(prefixed.group(1)) == normalized_text(artist):
        title = prefixed.group(2)
    title = re.sub(
        r"[\[(【](?:official\s*(?:music\s*)?(?:video|audio|mv)|lyrics?|lyric video|官方(?:音频|音乐视频|mv)|歌词(?:版|视频)?)[\])】]",
        "", title, flags=re.I,
    )
    duration = finite_number(item.get("duration"), 0)
    return normalized_text(title), normalized_text(artist), versions, duration


def same_recording(first, second):
    a, b = track_signature(first), track_signature(second)
    if not a or not b or a[:3] != b[:3] or a[3] <= 0 or b[3] <= 0:
        return False
    return abs(a[3] - b[3]) <= max(3, min(a[3], b[3]) * 0.02)


def same_named_recording(first, second):
    """For initial lookup only, when a legacy item has no source ID/duration."""
    a, b = track_signature(first), track_signature(second)
    return bool(a and b and a[:3] == b[:3])


def track_identity(item):
    return str(item.get("trackKey") or item.get("key") or
               f"{item.get('source') or ''}:{item.get('sourceId') or item.get('videoId') or item.get('id') or ''}")


def merge_search_items(items):
    groups = []
    seen = set()
    for raw in items:
        item = {key: value for key, value in raw.items() if key not in {"variants", "groupKey"}}
        identity = track_identity(item)
        if identity in seen:
            continue
        seen.add(identity)
        matching = next((group for group in groups if all(same_recording(item, variant) for variant in group["variants"])), None)
        if matching is None:
            group_key = "song:" + hashlib.sha256(identity.encode()).hexdigest()[:20]
            groups.append({**item, "groupKey": group_key, "variants": [item]})
        else:
            matching["variants"].append(item)
    return groups


def finite_number(value, default=0, maximum=86400):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return min(maximum, max(0, result)) if math.isfinite(result) else default


EFFECTS = {"off", "smart", "surround", "bass", "vocal", "spatial", "live", "electronic", "rock", "vintage"}
TRACK_TEXT_FIELDS = {
    "entryId", "id", "key", "trackKey", "groupKey", "title", "artist", "cover", "query",
    "videoId", "source", "sourceId", "provider", "durationText", "offlineUrl", "savedPath",
    "filename", "kind", "type",
}


def sanitize_track(raw):
    if not isinstance(raw, dict):
        return None
    item = {field: str(raw[field])[:4096] for field in TRACK_TEXT_FIELDS if raw.get(field) is not None}
    # Local media references are stable, remote signed URLs are not.
    if item.get("offlineUrl") and not item["offlineUrl"].startswith("/local-media?"):
        item.pop("offlineUrl", None)
    if not item.get("title") and not item.get("sourceId") and not item.get("videoId") and not item.get("savedPath"):
        return None
    if "duration" in raw:
        item["duration"] = finite_number(raw.get("duration"))
    if isinstance(raw.get("variants"), list):
        item["variants"] = [value for variant in raw["variants"][:10]
                            if (value := sanitize_track({k: v for k, v in variant.items() if k != "variants"}) if isinstance(variant, dict) else None)]
    return item


def sanitize_session(raw):
    raw = raw if isinstance(raw, dict) else {}
    if raw.get("version", 1) != 1:
        raise ValueError("Unsupported playback session version")
    queue = [item for entry in (raw.get("queue") if isinstance(raw.get("queue"), list) else [])[:300]
             if (item := sanitize_track(entry))]
    seen = set()
    for index, item in enumerate(queue):
        entry_id = item.get("entryId") or f"restored-{index}-{hashlib.sha256(track_identity(item).encode()).hexdigest()[:12]}"
        if entry_id in seen:
            entry_id = f"{entry_id}-{index}"
        seen.add(entry_id)
        item["entryId"] = entry_id
    current = str(raw.get("currentEntryId") or "")
    def valid_ids(field):
        return [str(value) for value in (raw.get(field) if isinstance(raw.get(field), list) else [])[-600:]
                if str(value) in seen]
    return {
        "version": 1, "queue": queue, "currentEntryId": current if current in seen else None,
        "position": finite_number(raw.get("position")), "shuffle": raw.get("shuffle") is True,
        "repeat": raw.get("repeat") if isinstance(raw.get("repeat"), str) and raw.get("repeat") in {"off", "all", "one"} else "off",
        "history": valid_ids("history"), "shuffleBag": list(dict.fromkeys(valid_ids("shuffleBag"))),
        "effect": raw.get("effect") if isinstance(raw.get("effect"), str) and raw.get("effect") in EFFECTS else "off",
    }


def media_expiry(url, ttl=75):
    expiry = time.time() + ttl
    params = parse_qs(urlparse(url).query)
    for name in ("expire", "expires", "Expires"):
        try:
            upstream_expiry = float(params.get(name, [""])[0])
            if math.isfinite(upstream_expiry) and upstream_expiry > 1_000_000_000:
                expiry = min(expiry, upstream_expiry - 5)
        except (TypeError, ValueError):
            pass
    return expiry


class PrefixCache:
    """One intended next track; replacement drops old bytes immediately."""
    prefix_limit = 2 * 1024 * 1024
    memory_limit = 32 * 1024 * 1024

    def __init__(self):
        self._lock = threading.Lock()
        self._generation = 0
        self._entry = None

    def reserve(self, clear=True):
        with self._lock:
            self._generation += 1
            if clear:
                self._entry = None
            return self._generation

    def store(self, generation, url, data, total, headers, expires_at):
        if not data or len(data) > min(self.prefix_limit, self.memory_limit):
            return False
        with self._lock:
            if generation != self._generation or expires_at <= time.time():
                return False
            self._entry = {"url": url, "data": data, "total": total,
                           "headers": {key.lower(): value for key, value in headers.items()}, "expiresAt": expires_at}
            return True

    def is_current(self, generation):
        with self._lock:
            return generation == self._generation

    def get(self, url):
        with self._lock:
            entry = self._entry
            if entry and entry["expiresAt"] > time.time() and entry["url"] == url:
                return entry
            if entry and entry["expiresAt"] <= time.time():
                self._entry = None
            return None

    def clear(self):
        self.reserve()


def parse_content_range(value):
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", str(value or ""), flags=re.I)
    if not match:
        return None
    start, end, total = map(int, match.groups())
    return (start, end, total) if 0 <= start <= end < total else None
