from __future__ import annotations

import asyncio
import sqlite3

import pytest

import main
from app_meta import APP_VERSION, APP_VERSION_LABEL, display_version


@pytest.fixture()
def isolated_library(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    frontend_dist = tmp_path / "frontend" / "dist"
    frontend_index = frontend_dist / "index.html"
    db_path = data_dir / "nas_local.db"

    def ensure_dirs() -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        frontend_dist.mkdir(parents=True, exist_ok=True)

    ensure_dirs()
    frontend_index.write_text("<!doctype html><html></html>", encoding="utf-8")
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "LIBRARY_DB", db_path)
    monkeypatch.setattr(main, "FRONTEND_DIST", frontend_dist)
    monkeypatch.setattr(main, "FRONTEND_INDEX", frontend_index)
    monkeypatch.setattr(main, "ensure_runtime_directories", ensure_dirs)
    monkeypatch.setattr(main, "resolve_ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(main, "port_is_open", lambda _port: False)

    main.init_library_db()
    main.SEARCH_RESULTS_CACHE.clear()
    main.PLAYBACK_INFO_CACHE.clear()
    main.VISUALIZE_CACHE.clear()
    main.LYRICS_CACHE.clear()
    main.COLOR_CACHE.clear()
    main.RECOMMENDATIONS_CACHE.clear()
    return db_path


def test_download_filename_helpers():
    assert main.safe_download_filename(' "夜に駆ける" / YOASOBI \\.m4a ') == "夜に駆ける YOASOBI .m4a"
    assert main.ascii_download_filename("夜に駆ける - YOASOBI.m4a") == "- YOASOBI.m4a"
    assert main.guess_download_media_type("track.m4a", "") == "audio/mp4"
    assert main.guess_download_media_type("track.mp3", "") == "audio/mpeg"
    assert main.guess_download_media_type("track.unknown", "audio/custom") == "audio/custom"


def test_select_preferred_audio_format_prefers_audio_only():
    video_info = {
        "formats": [
            {"format_id": "18", "url": "https://example.com/video.mp4", "acodec": "mp4a.40.2", "vcodec": "avc1", "ext": "mp4", "protocol": "https", "abr": 128},
            {"format_id": "140", "url": "https://example.com/audio.m4a", "acodec": "mp4a.40.2", "vcodec": "none", "ext": "m4a", "protocol": "https", "abr": 128},
            {"format_id": "251", "url": "https://example.com/audio.webm", "acodec": "opus", "vcodec": "none", "ext": "webm", "protocol": "https", "abr": 160},
        ]
    }

    selected = main.select_preferred_audio_format(video_info)
    assert selected is not None
    assert selected["format_id"] == "140"


def test_library_roundtrip_and_system_check(isolated_library):
    asyncio.run(
        main.upsert_favorite(
            main.LibraryTrack(
                key="track-1",
                title="夜に駆ける",
                artist="YOASOBI",
                cover="https://example.com/cover.jpg",
                query="夜に駆ける YOASOBI",
                videoId="x8VYWazR5mE",
            )
        )
    )
    asyncio.run(
        main.upsert_history(
            main.LibraryTrack(
                key="track-1",
                title="夜に駆ける",
                artist="YOASOBI",
                cover="https://example.com/cover.jpg",
                query="夜に駆ける YOASOBI",
                videoId="x8VYWazR5mE",
            )
        )
    )
    asyncio.run(main.upsert_search_history(main.SearchHistoryEntry(query="夜に駆ける")))
    asyncio.run(
        main.create_download_history(
            main.DownloadHistoryEntry(
                key="track-1",
                title="夜に駆ける",
                artist="YOASOBI",
                filename="夜に駆ける - YOASOBI.m4a",
                sourceUrl="https://example.com/audio.m4a",
                savedPath=str(main.default_download_directory() / "track-1.m4a"),
                cover="https://example.com/cover.jpg",
                query="YOASOBI track-1",
                videoId="x8VYWazR5mE",
            )
        )
    )
    asyncio.run(
        main.save_lyrics_offset(
            main.LyricsOffsetEntry(
                trackKey="track-1",
                videoId="x8VYWazR5mE",
                title="夜に駆ける",
                artist="YOASOBI",
                offsetSeconds=1.25,
            )
        )
    )

    stats = main.get_library_stats()
    assert stats == {
        "favorites": 1,
        "history": 1,
        "searches": 1,
        "downloads": 1,
        "lyricsOffsets": 1,
    }
    assert main.fetch_saved_lyrics_offset(track_key="youtube:x8VYWazR5mE") == pytest.approx(1.25)
    assert main.fetch_saved_lyrics_offset(source=main.SOURCE_YOUTUBE, source_id="x8VYWazR5mE") == pytest.approx(1.25)

    library = asyncio.run(main.get_library())
    assert library["favorites"][0]["key"] == "youtube:x8VYWazR5mE"
    assert library["favorites"][0]["title"] == "夜に駆ける"
    assert library["favorites"][0]["source"] == main.SOURCE_YOUTUBE
    assert library["favorites"][0]["sourceId"] == "x8VYWazR5mE"
    assert library["recentDownloads"][0]["filename"].endswith(".m4a")
    assert library["recentDownloads"][0]["key"] == "youtube:x8VYWazR5mE"
    assert library["recentDownloads"][0]["source"] == main.SOURCE_YOUTUBE
    assert library["recentDownloads"][0]["sourceId"] == "x8VYWazR5mE"

    system_check = main.get_system_check()
    assert system_check["appVersion"] == APP_VERSION
    assert system_check["appVersionLabel"] == APP_VERSION_LABEL
    assert system_check["libraryDbAvailable"] is True
    assert system_check["frontendBuilt"] is True
    assert "envProxyAvailable" in system_check
    assert system_check["downloadDirectory"]


def test_display_version_formats_trailing_zero_patch():
    assert display_version("1.6.0") == "1.60"
    assert display_version("1.5.1") == "1.5.1"
    assert display_version("2.10.0") == "2.10"


def test_delete_favorite_accepts_stable_key_for_legacy_video_rows(isolated_library):
    with main.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO favorites (track_key, title, artist, cover, query, video_id, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("vid:video-1", "Yellow", "Coldplay", "", "Yellow Coldplay", "video-1", main.utc_now_iso()),
        )

    asyncio.run(main.delete_favorite("youtube:video-1"))

    with main.get_db_connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
    assert count == 0


def test_search_provider_order_prefers_qqmusic_and_respects_fallback(monkeypatch):
    monkeypatch.setattr(main, "NAS_SEARCH_PROVIDER", "auto")
    monkeypatch.setattr(main, "NAS_ENABLE_YOUTUBE_FALLBACK", True)
    assert main.search_provider_order() == [main.SOURCE_QQMUSIC, main.SOURCE_YOUTUBE]

    monkeypatch.setattr(main, "NAS_ENABLE_YOUTUBE_FALLBACK", False)
    assert main.search_provider_order() == [main.SOURCE_QQMUSIC]

    monkeypatch.setattr(main, "NAS_SEARCH_PROVIDER", main.SOURCE_YOUTUBE)
    assert main.search_provider_order() == [main.SOURCE_YOUTUBE]


def test_build_search_response_payload_respects_requested_source(monkeypatch):
    calls = []

    def fake_search(query, limit, source, allow_network=True):
        calls.append(source)
        return [
            {
                "id": "video-1",
                "source": main.SOURCE_YOUTUBE,
                "sourceId": "video-1",
                "trackKey": "youtube:video-1",
                "title": "Yellow",
                "uploader": "Coldplay",
                "thumbnail": "",
                "provider": "youtube_data_api",
                "duration": 266,
            }
        ]

    monkeypatch.setattr(main, "search_entries_with_source", fake_search)
    monkeypatch.setattr(main, "search_catalog_entries", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("auto search should not run")))

    payload = main.build_search_response_payload("Yellow Coldplay", 5, source=main.SOURCE_YOUTUBE)

    assert calls == [main.SOURCE_YOUTUBE]
    assert payload["provider"] == main.SOURCE_YOUTUBE
    assert payload["results"][0].source == main.SOURCE_YOUTUBE
    assert payload["results"][0].trackKey == "youtube:video-1"


def test_search_youtube_entries_uses_backend_cache(monkeypatch):
    main.SEARCH_RESULTS_CACHE.clear()
    calls = {"count": 0}
    monkeypatch.setattr(main, "youtube_search_provider_order", lambda: ["legacy_ytdlp"])

    class FakeYoutubeDL:
        def __init__(self, _opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, _query, download=False):
            calls["count"] += 1
            return {
                "entries": [
                    {
                        "id": "video-1",
                        "title": "Yellow",
                        "uploader": "Coldplay",
                        "thumbnail": "https://example.com/yellow.jpg",
                        "duration": 266,
                    }
                ]
            }

    monkeypatch.setattr(main.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    first = main.search_youtube_entries("Yellow Coldplay", 5)
    second = main.search_youtube_entries("Yellow Coldplay", 5)

    assert calls["count"] == 1
    assert first[0]["id"] == "video-1"
    assert second[0]["title"] == "Yellow"


def test_visualize_prefers_direct_video_lookup_without_search(monkeypatch):
    main.VISUALIZE_CACHE.clear()
    main.PLAYBACK_INFO_CACHE.clear()
    main.COLOR_CACHE.clear()

    monkeypatch.setattr(
        main,
        "extract_playback_info",
        lambda video_id: {
            "id": video_id,
            "title": "Yellow",
            "uploader": "Coldplay",
            "thumbnail": "",
            "formats": [
                {
                    "format_id": "140",
                    "url": "https://example.com/audio.m4a",
                    "acodec": "mp4a.40.2",
                    "vcodec": "none",
                    "ext": "m4a",
                    "protocol": "https",
                    "abr": 128,
                }
            ],
        },
    )
    monkeypatch.setattr(main, "search_youtube_entries", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("search should not run")))

    payload = main.build_visualize_response_payload(query="Yellow Coldplay", video_id="video-1")

    assert payload["videoId"] == "video-1"
    assert payload["audioExt"] == "m4a"
    assert payload["audioSrc"] == "https://example.com/audio.m4a"
    assert payload["proxyAudioSrc"].startswith("/proxy-stream?url=")
    assert payload["streamMode"] == "direct"


def test_visualize_resolves_qqmusic_source(monkeypatch):
    main.VISUALIZE_CACHE.clear()
    main.PLAYBACK_INFO_CACHE.clear()
    main.COLOR_CACHE.clear()

    monkeypatch.setattr(
        main,
        "resolve_qqmusic_entry",
        lambda source_id, candidate=None: {
            "source": main.SOURCE_QQMUSIC,
            "sourceId": source_id,
            "trackKey": f"qqmusic:{source_id}",
            "title": "一路向北",
            "uploader": "周杰伦",
            "thumbnail": "",
            "audioUrl": "https://example.com/audio.mp3",
            "audioExt": "mp3",
        },
    )

    payload = main.build_visualize_response_payload(
        query="一路向北 周杰伦",
        source=main.SOURCE_QQMUSIC,
        source_id="qq-mid-1",
    )

    assert payload["source"] == main.SOURCE_QQMUSIC
    assert payload["sourceId"] == "qq-mid-1"
    assert payload["trackKey"] == "qqmusic:qq-mid-1"
    assert payload["audioExt"] == "mp3"
    assert payload["audioSrc"] == "https://example.com/audio.mp3"
    assert payload["proxyAudioSrc"].startswith("/proxy-stream?url=")


def test_resolve_qqmusic_entry_classifies_empty_vip_purl(monkeypatch):
    main.PLAYBACK_INFO_CACHE.clear()
    candidate = {
        "source": main.SOURCE_QQMUSIC,
        "sourceId": "vip-mid",
        "title": "VIP Song",
        "uploader": "Artist",
        "qqMediaMid": "media-mid",
        "qqFile": {"size_128mp3": 1234},
    }

    monkeypatch.setattr(
        main,
        "fetch_qqmusic_vkey_info",
        lambda *_args, **_kwargs: {
            "url": "",
            "purl": "",
            "reason": main.QQMUSIC_FAILURE_VIP_REQUIRED,
            "message": "need vip",
        },
    )

    with pytest.raises(main.QQMusicResolveError) as exc_info:
        main.resolve_qqmusic_entry("vip-mid", candidate)

    assert exc_info.value.reason == main.QQMUSIC_FAILURE_VIP_REQUIRED
    assert exc_info.value.attempts[0]["reason"] == main.QQMUSIC_FAILURE_VIP_REQUIRED


def test_resolve_qqmusic_entry_refreshes_stale_403_vkey(monkeypatch):
    main.PLAYBACK_INFO_CACHE.clear()
    probe_calls = {"count": 0}
    candidate = {
        "source": main.SOURCE_QQMUSIC,
        "sourceId": "fresh-mid",
        "title": "Fresh Song",
        "uploader": "Artist",
        "qqMediaMid": "media-mid",
        "qqFile": {"size_128mp3": 1234},
    }

    monkeypatch.setattr(
        main,
        "fetch_qqmusic_vkey_info",
        lambda *_args, **_kwargs: {
            "url": "https://isure.stream.qqmusic.qq.com/fresh.m4a",
            "purl": "fresh.m4a",
            "reason": "",
            "message": "",
        },
    )

    def fake_probe(_url):
        probe_calls["count"] += 1
        if probe_calls["count"] == 1:
            return {"ok": False, "reason": main.QQMUSIC_FAILURE_HTTP_403, "statusCode": 403, "error": "HTTPError"}
        return {"ok": True, "reason": "", "statusCode": 206, "error": ""}

    monkeypatch.setattr(main, "probe_playable_media_url_info", fake_probe)

    payload = main.resolve_qqmusic_entry("fresh-mid", candidate)

    assert payload["audioUrl"] == "https://isure.stream.qqmusic.qq.com/fresh.m4a"
    assert probe_calls["count"] == 2
    assert payload["resolveAttempts"][0]["reason"] == main.QQMUSIC_FAILURE_STALE_VKEY


def test_visualize_skips_unplayable_qqmusic_candidate_and_falls_back_to_youtube(monkeypatch):
    main.VISUALIZE_CACHE.clear()
    main.PLAYBACK_INFO_CACHE.clear()
    main.COLOR_CACHE.clear()

    monkeypatch.setattr(main, "search_provider_order", lambda: [main.SOURCE_QQMUSIC, main.SOURCE_YOUTUBE])
    monkeypatch.setattr(
        main,
        "search_entries_with_source",
        lambda query, limit, source, allow_network=True: (
            [
                {
                    "source": main.SOURCE_QQMUSIC,
                    "sourceId": "locked-mid",
                    "trackKey": "qqmusic:locked-mid",
                    "title": "Locked Song",
                    "uploader": "Artist",
                    "thumbnail": "",
                    "provider": main.SOURCE_QQMUSIC,
                }
            ]
            if source == main.SOURCE_QQMUSIC
            else [
                {
                    "id": "video-2",
                    "source": main.SOURCE_YOUTUBE,
                    "sourceId": "video-2",
                    "trackKey": "youtube:video-2",
                    "title": "Fallback Song",
                    "uploader": "Artist",
                    "thumbnail": "",
                    "provider": "ytmusicapi",
                }
            ]
        ),
    )
    monkeypatch.setattr(main, "resolve_qqmusic_entry", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("locked")))
    monkeypatch.setattr(
        main,
        "extract_playback_info",
        lambda video_id: {
            "id": video_id,
            "title": "Fallback Song",
            "uploader": "Artist",
            "thumbnail": "",
            "formats": [
                {
                    "format_id": "140",
                    "url": "https://example.com/fallback.m4a",
                    "acodec": "mp4a.40.2",
                    "vcodec": "none",
                    "ext": "m4a",
                    "protocol": "https",
                    "abr": 128,
                }
            ],
        },
    )

    payload = main.build_visualize_response_payload(query="Locked Song Artist")

    assert payload["source"] == main.SOURCE_YOUTUBE
    assert payload["sourceId"] == "video-2"
    assert payload["trackKey"] == "youtube:video-2"
    assert payload["videoId"] == "video-2"
    assert payload["audioSrc"] == "https://example.com/fallback.m4a"


def test_visualize_tries_next_qqmusic_candidate_before_youtube(monkeypatch):
    main.VISUALIZE_CACHE.clear()
    main.PLAYBACK_INFO_CACHE.clear()
    main.COLOR_CACHE.clear()

    monkeypatch.setattr(main, "search_provider_order", lambda: [main.SOURCE_QQMUSIC, main.SOURCE_YOUTUBE])
    monkeypatch.setattr(
        main,
        "search_entries_with_source",
        lambda query, limit, source, allow_network=True: (
            [
                {
                    "source": main.SOURCE_QQMUSIC,
                    "sourceId": "vip-mid",
                    "trackKey": "qqmusic:vip-mid",
                    "title": "Song",
                    "uploader": "Artist",
                    "thumbnail": "",
                    "provider": main.SOURCE_QQMUSIC,
                },
                {
                    "source": main.SOURCE_QQMUSIC,
                    "sourceId": "playable-mid",
                    "trackKey": "qqmusic:playable-mid",
                    "title": "Song",
                    "uploader": "Artist",
                    "thumbnail": "",
                    "provider": main.SOURCE_QQMUSIC,
                },
            ]
            if source == main.SOURCE_QQMUSIC
            else (_ for _ in ()).throw(AssertionError("youtube should not run"))
        ),
    )

    def fake_resolve(source_id, candidate=None):
        if source_id == "vip-mid":
            raise main.QQMusicResolveError(
                main.QQMUSIC_FAILURE_VIP_REQUIRED,
                "need vip",
                [
                    {
                        "source": main.SOURCE_QQMUSIC,
                        "sourceId": source_id,
                        "title": "Song",
                        "artist": "Artist",
                        "reason": main.QQMUSIC_FAILURE_VIP_REQUIRED,
                        "message": "need vip",
                    }
                ],
            )
        return {
            **(candidate or {}),
            "audioUrl": "https://example.com/playable.m4a",
            "audioExt": "m4a",
        }

    monkeypatch.setattr(main, "resolve_qqmusic_entry", fake_resolve)

    payload = main.build_visualize_response_payload(query="Song Artist")

    assert payload["source"] == main.SOURCE_QQMUSIC
    assert payload["sourceId"] == "playable-mid"
    assert payload["fallbackReason"] == "auto_fallback"
    assert payload["fallbackTrace"][0]["reason"] == main.QQMUSIC_FAILURE_VIP_REQUIRED
    assert payload["audioSrc"] == "https://example.com/playable.m4a"


def test_visualize_source_mode_restricts_search_provider(monkeypatch):
    main.VISUALIZE_CACHE.clear()
    main.PLAYBACK_INFO_CACHE.clear()
    main.COLOR_CACHE.clear()
    calls = []

    monkeypatch.setattr(main, "search_provider_order", lambda: [main.SOURCE_QQMUSIC, main.SOURCE_YOUTUBE])

    def fake_search(query, limit, source, allow_network=True):
        calls.append(source)
        if source == main.SOURCE_QQMUSIC:
            raise AssertionError("QQ search should not run for forced YouTube mode")
        return [
            {
                "id": "video-3",
                "source": main.SOURCE_YOUTUBE,
                "sourceId": "video-3",
                "trackKey": "youtube:video-3",
                "title": "Forced Song",
                "uploader": "Artist",
                "thumbnail": "",
                "provider": "ytmusicapi",
            }
        ]

    monkeypatch.setattr(main, "search_entries_with_source", fake_search)
    monkeypatch.setattr(
        main,
        "extract_playback_info",
        lambda video_id: {
            "id": video_id,
            "title": "Forced Song",
            "uploader": "Artist",
            "thumbnail": "",
            "formats": [
                {
                    "format_id": "140",
                    "url": "https://example.com/forced.m4a",
                    "acodec": "mp4a.40.2",
                    "vcodec": "none",
                    "ext": "m4a",
                    "protocol": "https",
                    "abr": 128,
                }
            ],
        },
    )
    monkeypatch.setattr(main, "get_cached_cover_colors", lambda _url: ["#111111", "#222222"])
    monkeypatch.setattr(main, "warm_cover_colors", lambda _url: ["#111111", "#222222"])

    payload = main.build_visualize_response_payload(
        query="Forced Song Artist",
        source=main.SOURCE_YOUTUBE,
        source_mode=main.SOURCE_YOUTUBE,
    )

    assert calls == [main.SOURCE_YOUTUBE]
    assert payload["source"] == main.SOURCE_YOUTUBE
    assert payload["audioSrc"] == "https://example.com/forced.m4a"


def test_search_provider_uses_youtube_data_api_when_available(monkeypatch):
    main.SEARCH_RESULTS_CACHE.clear()
    monkeypatch.setattr(main, "YOUTUBE_DATA_API_KEY", "demo-key")
    monkeypatch.setattr(main, "NAS_SEARCH_PROVIDER", main.SOURCE_YOUTUBE)

    def fake_request_json(url, *, params=None, timeout=12, kind="metadata"):
        if "youtube/v3/search" in url:
            return {
                "items": [
                    {
                        "id": {"videoId": "video-1"},
                        "snippet": {
                            "title": "Yellow",
                            "description": "Official audio",
                            "channelTitle": "Coldplay",
                            "thumbnails": {"high": {"url": "https://example.com/yellow.jpg"}},
                        },
                    }
                ]
            }
        if "youtube/v3/videos" in url:
            return {"items": [{"id": "video-1", "contentDetails": {"duration": "PT4M26S"}}]}
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(main, "request_json", fake_request_json)
    monkeypatch.setattr(main, "youtube_search_provider_order", lambda: ["youtube_data_api"])

    payload = main.build_search_response_payload("Yellow Coldplay", 5)

    assert payload["provider"] == main.SOURCE_YOUTUBE
    assert payload["results"][0].videoId == "video-1"
    assert payload["results"][0].provider == "youtube_data_api"
    assert payload["results"][0].source == main.SOURCE_YOUTUBE
    assert payload["results"][0].sourceId == "video-1"
    assert payload["results"][0].trackKey == "youtube:video-1"
    assert payload["results"][0].duration == 266


def test_build_search_diagnostics_payload_reports_reachable_search(monkeypatch):
    monkeypatch.setattr(main, "env_proxy_available", lambda: False)
    monkeypatch.setattr(main, "metadata_proxy_mode", lambda: "direct")
    monkeypatch.setattr(main, "YOUTUBE_DATA_API_KEY", "")
    monkeypatch.setattr(main, "search_provider_order", lambda: [main.SOURCE_QQMUSIC, main.SOURCE_YOUTUBE])
    monkeypatch.setattr(main, "youtube_search_provider_order", lambda: ["ytmusicapi", "legacy_ytdlp"])
    monkeypatch.setattr(
        main,
        "diagnose_http_endpoint",
        lambda endpoint_id, label, url, timeout=6: {
            "id": endpoint_id,
            "label": label,
            "url": url,
            "ok": True,
            "statusCode": 200,
            "error": "",
        },
    )
    monkeypatch.setattr(
        main,
        "search_catalog_entries",
        lambda query, limit, allow_network=True: [
            {"title": "Yellow", "uploader": "Coldplay", "source": main.SOURCE_QQMUSIC, "sourceId": "qq-1", "provider": main.SOURCE_QQMUSIC},
            {"title": "Clocks", "uploader": "Coldplay", "source": main.SOURCE_QQMUSIC, "sourceId": "qq-2", "provider": main.SOURCE_QQMUSIC},
        ][:limit],
    )

    payload = main.build_search_diagnostics_payload("Yellow Coldplay")

    assert payload["appVersionLabel"] == APP_VERSION_LABEL
    assert payload["searchProbe"]["ok"] is True
    assert payload["searchProbe"]["provider"] == main.SOURCE_QQMUSIC
    assert payload["likelyNeedsProxy"] is False
    assert payload["checks"][0]["statusCode"] == 200


def test_normalize_ytmusic_language_handles_web_locales():
    assert main.normalize_ytmusic_language("zh-CN") == "zh_CN"
    assert main.normalize_ytmusic_language("zh-TW") == "zh_TW"
    assert main.normalize_ytmusic_language("fr-FR") == "fr"
    assert main.normalize_ytmusic_language("xx-YY") == "en"


def test_fetch_lyrics_payload_prefers_synced_sources_over_plain_fallback(monkeypatch):
    main.LYRICS_CACHE.clear()

    monkeypatch.setattr(
        main,
        "fetch_ytmusic_lyrics",
        lambda _video_id: {
            "syncedLyrics": None,
            "plainLyrics": "plain fallback lyrics",
            "source": "ytmusicapi",
        },
    )
    monkeypatch.setattr(
        main,
        "fetch_youtube_captions",
        lambda _video_id, _target_lang: {
            "syncedLyrics": "[00:01.00]synced caption",
            "plainLyrics": "synced caption",
            "source": "youtube_subtitles",
        },
    )

    def fake_request_json(url, *, params=None, timeout=12, kind="metadata"):
        if "lrclib.net/api/get" in url:
            return {
                "trackName": "Song",
                "artistName": "Artist",
                "duration": 200,
                "syncedLyrics": None,
                "plainLyrics": "plain lrclib lyrics",
            }
        if "lrclib.net/api/search" in url:
            return []
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(main, "request_json", fake_request_json)

    payload = main.fetch_lyrics_payload("Song", "Artist", 200, "video-1")

    assert payload["source"] == "youtube_subtitles"
    assert payload["syncedLyrics"] == "[00:01.00]synced caption"


def test_fetch_lyrics_payload_returns_plain_fallback_when_no_synced_source(monkeypatch):
    main.LYRICS_CACHE.clear()

    monkeypatch.setattr(
        main,
        "fetch_ytmusic_lyrics",
        lambda _video_id: {
            "syncedLyrics": None,
            "plainLyrics": "plain fallback lyrics",
            "source": "ytmusicapi",
        },
    )
    monkeypatch.setattr(main, "fetch_youtube_captions", lambda *_args, **_kwargs: None)

    def fake_request_json(url, *, params=None, timeout=12, kind="metadata"):
        if "lrclib.net/api/get" in url:
            return None
        if "lrclib.net/api/search" in url:
            return []
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(main, "request_json", fake_request_json)

    payload = main.fetch_lyrics_payload("Song", "Artist", 200, "video-1")

    assert payload["source"] == "ytmusicapi"
    assert payload["plainLyrics"] == "plain fallback lyrics"


def test_local_library_payload_detects_duplicates(isolated_library, tmp_path):
    download_dir = tmp_path / "offline-library"
    first_dir = download_dir / "set-a"
    second_dir = download_dir / "set-b"
    first_dir.mkdir(parents=True, exist_ok=True)
    second_dir.mkdir(parents=True, exist_ok=True)

    first_file = first_dir / "nightcall-a.m4a"
    second_file = second_dir / "nightcall-b.m4a"
    first_file.write_bytes(b"audio-a")
    second_file.write_bytes(b"audio-b")

    main.set_app_setting(main.APP_SETTING_DOWNLOAD_DIRECTORY, str(download_dir))

    asyncio.run(
        main.create_download_history(
            main.DownloadHistoryEntry(
                key="nightcall-a",
                title="Nightcall",
                artist="Kavinsky",
                filename=first_file.name,
                sourceUrl="https://example.com/nightcall-a.m4a",
                savedPath=str(first_file),
                cover="https://example.com/nightcall.jpg",
                query="Nightcall Kavinsky",
                videoId="video-1",
            )
        )
    )
    asyncio.run(
        main.create_download_history(
            main.DownloadHistoryEntry(
                key="nightcall-b",
                title="Nightcall",
                artist="Kavinsky",
                filename=second_file.name,
                sourceUrl="https://example.com/nightcall-b.m4a",
                savedPath=str(second_file),
                query="Nightcall Kavinsky",
                videoId="video-1",
            )
        )
    )

    payload = main.build_local_library_payload()

    assert payload["downloadDirectory"] == str(download_dir.resolve())
    assert payload["totalTracks"] == 2
    assert payload["duplicateGroups"] == 1
    assert payload["duplicateTracks"] == 2
    assert payload["items"][0]["offlineUrl"].startswith("/local-media?path=")
    assert all(item["duplicateCount"] == 2 for item in payload["items"])


def test_merge_library_databases_restores_legacy_favorites(tmp_path):
    source_db = tmp_path / "source.db"
    target_db = tmp_path / "target.db"

    original_db = main.LIBRARY_DB
    original_legacy_db = main.LEGACY_SOURCE_LIBRARY_DB
    original_migration_done = main.LIBRARY_MIGRATION_DONE
    try:
        main.LEGACY_SOURCE_LIBRARY_DB = tmp_path / "missing-legacy.db"
        main.LIBRARY_MIGRATION_DONE = True
        main.LIBRARY_DB = source_db
        main.init_library_db()
        asyncio.run(
            main.upsert_favorite(
                main.LibraryTrack(
                    key="legacy-fav",
                    title="夜に駆ける",
                    artist="YOASOBI",
                    query="夜に駆ける YOASOBI",
                    videoId="legacy-video",
                )
            )
        )

        main.LIBRARY_DB = target_db
        main.init_library_db()
        stats = main.merge_library_databases(source_db, target_db)

        connection = sqlite3.connect(target_db)
        try:
            count = connection.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
            row = connection.execute("SELECT title, artist FROM favorites WHERE track_key = 'youtube:legacy-video'").fetchone()
        finally:
            connection.close()
    finally:
        main.LIBRARY_DB = original_db
        main.LEGACY_SOURCE_LIBRARY_DB = original_legacy_db
        main.LIBRARY_MIGRATION_DONE = original_migration_done

    assert stats["favorites"] == 1
    assert count == 1
    assert row == ("夜に駆ける", "YOASOBI")


def test_frontend_routes_disable_index_cache_and_do_not_fallback_missing_assets(isolated_library):
    response = asyncio.run(main.serve_index())
    assert response.headers["cache-control"].startswith("no-store")

    with pytest.raises(main.HTTPException) as exc_info:
        asyncio.run(main.serve_frontend_resource("assets/missing-bundle.js"))

    assert exc_info.value.status_code == 404


def test_search_ytmusicapi_entries_filters_metric_labels_and_skips_extra_queries(monkeypatch):
    calls = []

    class FakeClient:
        def search(self, query, filter=None, limit=20):
            calls.append((query, filter, limit))
            if filter != "songs":
                raise AssertionError("videos search should be skipped when songs already filled the page")
            return [
                {
                    "videoId": f"song-{index}",
                    "title": f"Track {index}",
                    "artists": [{"name": "Coldplay"}, {"name": "播放次数：23亿"}],
                    "duration_seconds": 240 + index,
                    "thumbnails": [{"url": f"https://example.com/{index}.jpg", "width": 120, "height": 120}],
                    "category": "歌曲",
                    "resultType": "song",
                }
                for index in range(1, 7)
            ]

    monkeypatch.setattr(main, "ytmusic_client", lambda: FakeClient())

    entries = main.search_ytmusicapi_entries("Yellow Coldplay", 5)

    assert len(entries) == 6
    assert calls == [("Yellow Coldplay", "songs", 7)]
    assert entries[0]["uploader"] == "Coldplay"
    assert entries[0]["provider"] == "ytmusicapi"


def test_recommendations_mix_history_and_personalized_results(isolated_library, monkeypatch):
    asyncio.run(
        main.upsert_favorite(
            main.LibraryTrack(
                key="fav-1",
                title="Yellow",
                artist="Coldplay",
                cover="",
                query="Yellow Coldplay",
                videoId="fav-1",
            )
        )
    )
    asyncio.run(
        main.upsert_history(
            main.LibraryTrack(
                key="hist-1",
                title="Take On Me",
                artist="a-ha",
                cover="",
                query="Take On Me a-ha",
                videoId="hist-1",
            )
        )
    )
    asyncio.run(main.upsert_search_history(main.SearchHistoryEntry(query="The Weeknd")))

    def fake_search(query, limit, allow_network=True):
        normalized = query.lower()
        if "coldplay" in normalized:
            return [
                {"id": "song-1", "title": "Clocks", "uploader": "Coldplay", "thumbnail": "https://example.com/clocks.jpg", "duration": 307, "provider": "ytmusicapi"},
                {"id": "song-2", "title": "Adventure of a Lifetime", "uploader": "Coldplay", "thumbnail": "https://example.com/adventure.jpg", "duration": 264, "provider": "ytmusicapi"},
            ][:limit]
        if "weeknd" in normalized:
            return [
                {"id": "song-3", "title": "Save Your Tears", "uploader": "The Weeknd", "thumbnail": "https://example.com/syt.jpg", "duration": 215, "provider": "ytmusicapi"},
                {"id": "song-4", "title": "Starboy", "uploader": "The Weeknd", "thumbnail": "https://example.com/starboy.jpg", "duration": 230, "provider": "ytmusicapi"},
            ][:limit]
        if "a-ha" in normalized:
            return [
                {"id": "song-5", "title": "Hunting High and Low", "uploader": "a-ha", "thumbnail": "https://example.com/hhal.jpg", "duration": 221, "provider": "ytmusicapi"},
            ][:limit]
        return []

    monkeypatch.setattr(main, "search_catalog_entries", fake_search)

    payload = main.build_recommendations_payload()
    sections = {section.id: section for section in payload["sections"]}

    assert payload["mode"] == "mixed"
    assert "continue-listening" in sections
    assert "for-you" in sections
    assert "nas-curated" in sections
    assert sections["continue-listening"].items[0].title == "Take On Me"
    assert len(sections["for-you"].items) >= 2
    assert sections["for-you"].items[0].videoId
    assert sections["nas-curated"].items[0].videoId
