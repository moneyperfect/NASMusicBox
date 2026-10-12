import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
from pathlib import Path

import pytest
import requests
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import main
from playback_upgrade import PrefixCache, SingleFlight, merge_search_items, same_recording, sanitize_session


@pytest.fixture(autouse=True)
def clean_playback_caches():
    main.VISUALIZE_CACHE.clear()
    main.PLAYBACK_INFO_CACHE.clear()
    main.PREFIX_CACHE.clear()
    main.COLOR_CACHE.clear()


def song(source="qqmusic", source_id="q1", **changes):
    return {"source": source, "sourceId": source_id, "trackKey": f"{source}:{source_id}",
            "title": "Yellow", "artist": "Coldplay", "duration": 267,
            "videoId": source_id if source == "youtube" else "", "cover": "", "query": "Yellow Coldplay", **changes}


def entry(source="qqmusic", source_id="q1", **changes):
    item = song(source, source_id, **changes)
    return {**item, "id": item["videoId"], "uploader": item["artist"], "thumbnail": item["cover"]}


def fake_qq(source_id, candidate=None):
    return {"title": "Yellow", "uploader": "Coldplay", "thumbnail": "https://example.com/cover.jpg",
            "audioUrl": "https://example.com/audio.m4a", "audioExt": "m4a"}


def fake_youtube(video_id):
    return {"title": "Yellow", "uploader": "Coldplay", "formats": [
        {"url": "https://example.com/youtube.m4a", "acodec": "aac", "vcodec": "none", "ext": "m4a"}]}


def test_public_qq_candidate_hydrates_media_identity_before_vkey(monkeypatch):
    public = song()
    detail = {**public, "uploader": public["artist"], "qqMediaMid": "different-media-mid", "qqFile": {"size_128mp3": 1000}}
    hydrated = []
    monkeypatch.setattr(main, "fetch_qqmusic_track_detail", lambda source_id: hydrated.append(source_id) or detail)
    def vkey(source_id, media_mid, *_):
        assert source_id == "q1" and media_mid == "different-media-mid"
        return {"url": "https://example.com/audio.mp3", "purl": "audio.mp3"}
    monkeypatch.setattr(main, "fetch_qqmusic_vkey_info", vkey)
    monkeypatch.setattr(main, "probe_playable_media_url_info", lambda _: {"ok": True})
    assert main.resolve_qqmusic_entry("q1", public)["audioUrl"] == "https://example.com/audio.mp3"
    assert hydrated == ["q1"]


def test_ytdlp_receives_explicit_runtime_without_implicit_windows_path_scan(monkeypatch):
    monkeypatch.setattr(main, "LOCAL_NODE_BINARY", Path("missing-bundled-node.exe"))
    monkeypatch.setattr(main.shutil, "which", lambda name: "D:/tools/node.exe" if name == "node" else None)
    monkeypatch.setattr(main, "resolve_ffmpeg_binary", lambda: None)
    assert main.get_media_ydl_opts()["js_runtimes"] == {"node": {"path": "D:/tools/node.exe"}}


def test_ytdlp_prefers_bundled_runtime_without_system_node(monkeypatch, tmp_path):
    bundled = tmp_path / "node.exe"
    bundled.write_bytes(b"runtime-placeholder")
    monkeypatch.setattr(main, "LOCAL_NODE_BINARY", bundled)
    monkeypatch.setattr(main.shutil, "which", lambda _: None)
    monkeypatch.setattr(main, "resolve_ffmpeg_binary", lambda: None)
    assert main.get_media_ydl_opts()["js_runtimes"] == {"node": {"path": str(bundled)}}


def test_grouping_preserves_source_ids_and_flat_candidates():
    merged = merge_search_items([song(), song("youtube", "y1", title="Yellow (Official Audio)", artist="Coldplay - Topic", duration=270)])
    assert len(merged) == 1
    assert merged[0]["trackKey"] == "qqmusic:q1"
    assert [variant["sourceId"] for variant in merged[0]["variants"]] == ["q1", "y1"]
    assert all("variants" not in item for item in merged[0]["variants"])


@pytest.mark.parametrize("change", [
    {"artist": "Another Artist"}, {"artist": "Unknown Artist"}, {"artist": ""},
    {"title": "Yellow Live"}, {"title": "Yellow (cover)"}, {"title": "Yellow Remix"},
    {"title": "Yellow 伴奏"}, {"title": "Yellow (Acoustic)"}, {"title": "Yellow (2011 Remaster)"},
    {"duration": None}, {"duration": 285},
])
def test_grouping_does_not_guess_recordings(change):
    assert not same_recording(song(), song("youtube", "y1", **change))
    assert len(merge_search_items([song(), song("youtube", "y1", **change)])) == 2


def test_grouping_uses_pairwise_duration_checks():
    # A chain of small deltas must not connect two recordings outside tolerance.
    merged = merge_search_items([song(duration=100), song("youtube", "y1", duration=103), song("youtube", "y2", duration=106)])
    assert len(merged) == 2


def test_search_stream_delivers_first_provider_before_second_finishes(monkeypatch):
    release = threading.Event()
    def search(_query, _limit, source):
        if source == "youtube":
            assert release.wait(3)
        return [entry(source, "q1" if source == "qqmusic" else "y1")]
    monkeypatch.setattr(main, "search_entries_with_source", search)
    async def exercise():
        response = await main.search_tracks_stream(main.SearchRequest(query="Yellow"))
        iterator = response.body_iterator
        first = await anext(iterator)
        payload = json.loads(first.split("data: ")[1])
        assert payload["providers"] == ["qqmusic"]
        assert payload["pending"] == ["youtube"]
        assert len(payload["results"]) == 1
        release.set()
        second = json.loads((await anext(iterator)).split("data: ")[1])
        assert second["pending"] == []
        assert len(second["results"][0]["variants"]) == 2
        assert "event: done" in await anext(iterator)
    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_search_stream_partial_failure_keeps_other_results(monkeypatch):
    def search(_query, _limit, source):
        if source == "youtube":
            raise RuntimeError("unavailable")
        return [entry()]
    monkeypatch.setattr(main, "search_entries_with_source", search)
    async def exercise():
        response = await main.search_tracks_stream(main.SearchRequest(query="Yellow"))
        payloads = [json.loads(event.split("data: ")[1]) async for event in response.body_iterator if "event: results" in event]
        assert len(payloads[-1]["results"]) == 1
        assert payloads[-1]["errors"]["youtube"]
    asyncio.run(exercise())


def test_fast_visualize_uses_proxy_without_cover_work(monkeypatch):
    monkeypatch.setattr(main, "resolve_qqmusic_entry", fake_qq)
    monkeypatch.setattr(main, "get_dominant_colors", lambda _url: pytest.fail("fast playback must not extract colors"))
    monkeypatch.setattr(main, "warm_cover_colors", lambda _url: pytest.fail("fast playback must not schedule cover work"))
    payload = main.build_visualize_response_payload(source="qqmusic", source_id="q1", fast=True)
    assert payload["audioSrc"].startswith("/proxy-stream?url=")
    assert payload["streamMode"] == "proxy"
    assert payload["colors"] == main.DEFAULT_VISUAL_COLORS
    assert payload["expiresAt"] > time.time()


def test_same_resolve_is_shared_between_concurrent_requests(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []
    def resolve(source_id, candidate=None):
        calls.append(source_id)
        started.set()
        assert release.wait(3)
        return fake_qq(source_id, candidate)
    monkeypatch.setattr(main, "resolve_qqmusic_entry", resolve)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(main.build_visualize_response_payload, source="qqmusic", source_id="q1", fast=True) for _ in range(6)]
        assert started.wait(2)
        release.set()
        results = [future.result(timeout=3) for future in futures]
    assert calls == ["q1"]
    assert all(result["sourceId"] == "q1" for result in results)


def test_refresh_bypasses_positive_visualize_and_playback_cache(monkeypatch):
    calls = []
    def resolve(source_id, candidate=None):
        key = f"playback::qqmusic::{source_id}"
        cached = main.PLAYBACK_INFO_CACHE.get(key)
        if cached is not main.CACHE_MISS:
            return cached
        calls.append(source_id)
        payload = {**fake_qq(source_id), "audioUrl": f"https://example.com/audio-{len(calls)}.m4a"}
        main.PLAYBACK_INFO_CACHE.set(key, payload, 75)
        return payload
    monkeypatch.setattr(main, "resolve_qqmusic_entry", resolve)
    first = main.build_visualize_response_payload(source="qqmusic", source_id="q1", fast=True)
    again = main.build_visualize_response_payload(source="qqmusic", source_id="q1", fast=True)
    assert first["audioSrc"] == again["audioSrc"]
    refreshed = main.build_visualize_response_payload(source="qqmusic", source_id="q1", fast=True, refresh=True)
    assert first["audioSrc"] != refreshed["audioSrc"]
    assert calls == ["q1", "q1"]


def test_singleflight_errors_are_shared_and_retryable():
    flight = SingleFlight()
    with pytest.raises(ValueError):
        flight.run("key", lambda: (_ for _ in ()).throw(ValueError("failure")))
    assert flight.run("key", lambda: 42) == 42


def test_candidate_fallback_is_conservative_and_respects_source_mode(monkeypatch):
    calls = []
    def fail_qq(source_id, candidate=None):
        calls.append("qqmusic")
        raise RuntimeError("unavailable")
    def youtube(video_id):
        calls.append("youtube")
        return fake_youtube(video_id)
    monkeypatch.setattr(main, "resolve_qqmusic_entry", fail_qq)
    monkeypatch.setattr(main, "extract_playback_info", youtube)
    monkeypatch.setattr(main, "search_entries_with_source", lambda *args, **kwargs: pytest.fail("explicit candidates must not broad-search"))
    candidates = [song(), song("youtube", "y1")]
    auto = main.build_visualize_response_payload(source="qqmusic", source_id="q1", fast=True, candidates=candidates)
    assert auto["source"] == "youtube"
    assert auto["trackKey"] == "youtube:y1"
    assert auto["fallbackTrace"]
    with pytest.raises(HTTPException) as restricted:
        main.build_visualize_response_payload(source="qqmusic", source_id="q1", source_mode="qqmusic", fast=True, candidates=candidates)
    assert restricted.value.status_code == 502
    assert calls == ["qqmusic", "youtube", "qqmusic"]


def test_live_failure_does_not_fall_back_to_studio_or_query(monkeypatch):
    monkeypatch.setattr(main, "resolve_qqmusic_entry", lambda *args: (_ for _ in ()).throw(RuntimeError("unavailable")))
    monkeypatch.setattr(main, "extract_playback_info", lambda *args: pytest.fail("studio version must not play"))
    monkeypatch.setattr(main, "search_entries_with_source", lambda *args: pytest.fail("broad fallback must not run"))
    with pytest.raises(HTTPException):
        main.build_visualize_response_payload(query="Yellow live", source="qqmusic", source_id="q1", fast=True,
                                              candidates=[song(title="Yellow Live"), song("youtube", "y1")])


def test_forced_source_never_resolves_mismatched_direct_id(monkeypatch):
    monkeypatch.setattr(main, "resolve_qqmusic_entry", lambda *args: pytest.fail("forced YouTube must not resolve QQ"))
    monkeypatch.setattr(main, "extract_playback_info", fake_youtube)
    payload = main.build_visualize_response_payload(source="qqmusic", source_id="q1", source_mode="youtube", fast=True,
                                                     candidates=[song(), song("youtube", "y1")])
    assert payload["source"] == "youtube"


def test_metadata_only_radio_track_resolves_matching_initial_identity(monkeypatch):
    queried = []
    def search(query, limit, source):
        queried.append(source)
        return [entry(source, "wrong", title="Yellow Live"), entry(source, "correct")]
    monkeypatch.setattr(main, "search_entries_with_source", search)
    monkeypatch.setattr(main, "resolve_qqmusic_entry", fake_qq)
    candidate = {"title": "Yellow", "artist": "Coldplay", "query": "Yellow Coldplay"}
    payload = main.build_visualize_response_payload(query=candidate["query"], fast=True, candidates=[candidate],
                                                     title="Yellow", artist="Coldplay")
    assert payload["sourceId"] == "correct"
    assert queried == ["qqmusic"]


def test_metadata_only_radio_does_not_try_another_recording_after_failure(monkeypatch):
    attempted = []
    monkeypatch.setattr(main, "search_entries_with_source", lambda query, limit, source: [entry(source, "first"), entry(source, "second")])
    def fail(source_id, candidate=None):
        attempted.append(source_id)
        raise RuntimeError("unavailable")
    monkeypatch.setattr(main, "resolve_qqmusic_entry", fail)
    with pytest.raises(HTTPException):
        main.build_visualize_response_payload(query="Yellow Coldplay", fast=True,
                                              candidates=[{"title": "Yellow", "artist": "Coldplay"}])
    assert attempted == ["first"]


class MediaResponse:
    def __init__(self, data=b"abcdefghij", status=206, content_range="bytes 0-9/100"):
        self.data = data
        self.status_code = status
        self.headers = {"content-type": "audio/mpeg", "content-length": str(len(data)), "accept-ranges": "bytes"}
        if content_range:
            self.headers["content-range"] = content_range
        self.closed = False
        self.reads = 0

    def iter_content(self, chunk_size):
        self.reads += 1
        yield self.data

    def close(self):
        self.closed = True


@pytest.mark.parametrize("status,content_range", [(200, None), (206, "bytes 0-9/*"), (206, "bytes 10-19/100")])
def test_prepare_refuses_ignored_or_invalid_range_without_reading(monkeypatch, status, content_range):
    response = MediaResponse(status=status, content_range=content_range)
    monkeypatch.setattr(main, "request_media_response", lambda *args, **kwargs: (response, "direct"))
    result = main.prepare_media_prefix("https://example.com/audio", time.time() + 60, main.PREFIX_CACHE.reserve())
    assert result["prefetchedBytes"] == 0
    assert response.reads == 0
    assert response.closed


def test_prepare_fetches_and_caches_only_valid_prefix(monkeypatch):
    response = MediaResponse()
    seen = []
    def fetch(url, **kwargs):
        seen.append(kwargs["headers"]["Range"])
        return response, "direct"
    monkeypatch.setattr(main, "request_media_response", fetch)
    result = main.prepare_media_prefix("https://example.com/audio", time.time() + 60, main.PREFIX_CACHE.reserve())
    assert result == {"prefetchedBytes": 10, "rangeSupported": True}
    assert seen == ["bytes=0-2097151"]
    assert main.PREFIX_CACHE.get("https://example.com/audio")["data"] == b"abcdefghij"
    assert response.closed


def test_prepare_short_track_requests_smaller_prefix_instead_of_full_recording(monkeypatch):
    full = MediaResponse(data=b"abcdefghij", content_range="bytes 0-9/10")
    prefix = MediaResponse(data=b"ab", content_range="bytes 0-1/10")
    responses = iter([full, prefix])
    seen = []
    def fetch(url, **kwargs):
        seen.append(kwargs["headers"]["Range"])
        return next(responses), "direct"
    monkeypatch.setattr(main, "request_media_response", fetch)
    result = main.prepare_media_prefix("media", time.time() + 60, main.PREFIX_CACHE.reserve())
    assert result["prefetchedBytes"] == 2
    assert full.reads == 0
    assert full.closed and prefix.closed
    assert seen == ["bytes=0-2097151", "bytes=0-1"]


def test_prefix_replacement_bound_and_stale_prepare():
    cache = PrefixCache()
    old = cache.reserve()
    new = cache.reserve()
    assert not cache.store(old, "old", b"old", 3, {}, time.time() + 60)
    assert not cache.store(new, "too-big", b"a" * (cache.prefix_limit + 1), cache.prefix_limit + 1, {}, time.time() + 60)
    assert cache.store(new, "new", b"new", 3, {}, time.time() + 60)
    assert cache.get("old") is None
    assert cache.get("new")["data"] == b"new"


def test_stale_prepare_skips_network(monkeypatch):
    stale = main.PREFIX_CACHE.reserve()
    main.PREFIX_CACHE.reserve()
    monkeypatch.setattr(main, "request_media_response", lambda *args, **kwargs: pytest.fail("obsolete next track must not prefetch"))
    assert main.prepare_media_prefix("old-track", time.time() + 60, stale)["prefetchedBytes"] == 0


def request(range_header=None):
    headers = [(b"range", range_header.encode())] if range_header else []
    return Request({"type": "http", "method": "GET", "path": "/proxy-stream", "headers": headers})


async def body_of(response):
    if hasattr(response, "body"):
        return response.body
    return b"".join([chunk async for chunk in response.body_iterator])


def test_proxy_serves_cached_range_without_network(monkeypatch):
    main.PREFIX_CACHE.store(main.PREFIX_CACHE.reserve(), "media", b"abcdefghij", 100, {"content-type": "audio/mpeg"}, time.time() + 60)
    monkeypatch.setattr(main, "request_media_response", lambda *args, **kwargs: pytest.fail("cached range needs no upstream"))
    response = asyncio.run(main.proxy_stream("media", request("bytes=2-5")))
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 2-5/100"
    assert response.body == b"cdef"


@pytest.mark.parametrize("range_header,expected_status", [("bytes=0-19", 206), (None, 200)])
def test_proxy_combines_prefix_with_correct_tail_range(monkeypatch, range_header, expected_status):
    total = 20
    main.PREFIX_CACHE.store(main.PREFIX_CACHE.reserve(), "media", b"abcdefghij", total, {"content-type": "audio/mpeg"}, time.time() + 60)
    response = MediaResponse(data=b"klmnopqrst", content_range="bytes 10-19/20")
    seen = []
    def fetch(url, **kwargs):
        seen.append(kwargs["headers"]["Range"])
        return response, "direct"
    monkeypatch.setattr(main, "request_media_response", fetch)
    async def exercise():
        output = await main.proxy_stream("media", request(range_header))
        assert output.status_code == expected_status
        assert output.headers["content-length"] == "20"
        if range_header:
            assert output.headers["content-range"] == "bytes 0-19/20"
        else:
            assert "content-range" not in output.headers
        assert await body_of(output) == b"abcdefghijklmnopqrst"
    asyncio.run(exercise())
    assert seen == ["bytes=10-19"]
    assert response.closed


def test_proxy_range_ignored_does_not_duplicate_prefix(monkeypatch):
    main.PREFIX_CACHE.store(main.PREFIX_CACHE.reserve(), "media", b"abc", 6, {}, time.time() + 60)
    ignored = MediaResponse(data=b"abcdef", status=200, content_range=None)
    normal = MediaResponse(data=b"abcdef", status=200, content_range=None)
    responses = iter([ignored, normal])
    monkeypatch.setattr(main, "request_media_response", lambda *args, **kwargs: (next(responses), "direct"))
    async def exercise():
        output = await main.proxy_stream("media", request())
        assert output.status_code == 200
        assert await body_of(output) == b"abcdef"
    asyncio.run(exercise())
    assert ignored.closed and normal.closed


def test_proxy_preserves_upstream_range_error(monkeypatch):
    error_response = MediaResponse(status=416, content_range="bytes */100")
    def fetch(*args, **kwargs):
        raise requests.HTTPError("range", response=error_response)
    monkeypatch.setattr(main, "request_media_response", fetch)
    output = asyncio.run(main.proxy_stream("media", request("bytes=200-")))
    assert output.status_code == 416
    assert output.headers["content-range"] == "bytes */100"
    assert error_response.closed


def test_proxy_upstream_open_does_not_block_async_loop(monkeypatch):
    started, release = threading.Event(), threading.Event()
    def fetch(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return MediaResponse(), "direct"
    monkeypatch.setattr(main, "request_media_response", fetch)
    async def exercise():
        began = time.monotonic()
        pending = asyncio.create_task(main.proxy_stream("media", request()))
        while not started.is_set():
            await asyncio.sleep(0)
        assert time.monotonic() - began < 1
        release.set()
        response = await pending
        await body_of(response)
    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_fast_playback_http_contract_includes_refresh_and_expiry(monkeypatch):
    calls = []
    def resolve(source_id, candidate=None):
        calls.append(source_id)
        return fake_qq(source_id)
    monkeypatch.setattr(main, "resolve_qqmusic_entry", resolve)
    with TestClient(main.app) as client:
        response = client.post("/visualize", json={"source": "qqmusic", "sourceId": "q1", "fast": True, "candidates": [song()]})
        assert response.status_code == 200
        assert response.json()["expiresAt"] > time.time()
        assert response.json()["audioSrc"].startswith("/proxy-stream?")
        refreshed = client.post("/visualize", json={"source": "qqmusic", "sourceId": "q1", "fast": True, "candidates": [song()], "refresh": True})
        assert refreshed.status_code == 200
        assert calls == ["q1", "q1"]


def test_session_sanitization_drops_transient_audio_and_bounds_values():
    raw = {"version": 1, "queue": [{**song(), "entryId": "one", "audioSrc": "signed-url", "proxyAudioSrc": "signed-proxy",
             "variants": [{**song("youtube", "y1"), "audioSrc": "temporary", "variants": [song()]}]},
             {"entryId": "two", "title": "Local", "savedPath": "D:/Music/test.mp3", "offlineUrl": "/local-media?path=local"}],
           "currentEntryId": "one", "position": float("nan"), "repeat": "one", "shuffle": True,
           "history": ["missing", "one"], "shuffleBag": ["two", "two"], "effect": "rock"}
    session = sanitize_session(raw)
    assert session["position"] == 0
    assert session["history"] == ["one"]
    assert session["shuffleBag"] == ["two"]
    assert session["effect"] == "rock"
    assert "audioSrc" not in session["queue"][0]
    assert "proxyAudioSrc" not in session["queue"][0]
    assert "audioSrc" not in session["queue"][0]["variants"][0]
    assert "variants" not in session["queue"][0]["variants"][0]
    assert session["queue"][1]["offlineUrl"].startswith("/local-media")


def test_session_round_trip_existing_settings_table(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LIBRARY_DB", tmp_path / "playback.db")
    monkeypatch.setattr(main, "LIBRARY_MIGRATION_DONE", True)
    main.init_library_db()
    saved = asyncio.run(main.save_playback_session({"version": 1, "queue": [{**song(), "entryId": "one"}],
                                                   "currentEntryId": "one", "position": 42, "effect": "bass"}))
    restored = asyncio.run(main.get_playback_session())
    assert restored == saved
    assert restored["currentEntryId"] == "one"
    assert restored["position"] == 42
    assert "isPlaying" not in restored
    with main.get_db_connection() as connection:
        assert connection.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'playback_session_v1'").fetchone()


def test_session_rejects_unknown_version_and_limits_queue():
    with pytest.raises(ValueError):
        sanitize_session({"version": 2})
    session = sanitize_session({"queue": [song(source_id=f"q{i}") for i in range(400)], "position": -5, "repeat": "bad"})
    assert len(session["queue"]) == 300
    assert len({item["entryId"] for item in session["queue"]}) == 300
    assert session["position"] == 0
    assert session["repeat"] == "off"
