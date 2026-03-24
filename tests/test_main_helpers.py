from __future__ import annotations

import asyncio

import pytest

import main
from app_meta import APP_VERSION


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
    main.DOWNLOAD_JOBS.clear()
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
                savedPath=str((isolated_library.parent / "downloads" / "yoasobi.m4a")),
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
    assert main.fetch_saved_lyrics_offset(track_key="track-1") == pytest.approx(1.25)

    library = asyncio.run(main.get_library())
    assert library["favorites"][0]["title"] == "夜に駆ける"
    assert library["recentDownloads"][0]["filename"].endswith(".m4a")
    assert library["recentDownloads"][0]["savedPath"].endswith("yoasobi.m4a")

    system_check = main.get_system_check()
    assert system_check["appVersion"] == APP_VERSION
    assert system_check["libraryDbAvailable"] is True
    assert system_check["frontendBuilt"] is True
    assert system_check["downloadDirectory"]


def test_search_youtube_entries_uses_backend_cache(monkeypatch):
    main.SEARCH_RESULTS_CACHE.clear()
    calls = {"count": 0}
    monkeypatch.setattr(main, "search_provider_order", lambda: ["legacy_ytdlp"])

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


def test_search_provider_uses_youtube_data_api_when_available(monkeypatch):
    main.SEARCH_RESULTS_CACHE.clear()
    monkeypatch.setattr(main, "YOUTUBE_DATA_API_KEY", "demo-key")
    monkeypatch.setattr(main, "NAS_SEARCH_PROVIDER", "auto")

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
    monkeypatch.setattr(main, "search_provider_order", lambda: ["youtube_data_api"])

    payload = main.build_search_response_payload("Yellow Coldplay", 5)

    assert payload["provider"] == "youtube_data_api"
    assert payload["results"][0].videoId == "video-1"
    assert payload["results"][0].duration == 266


def test_normalize_ytmusic_language_handles_web_locales():
    assert main.normalize_ytmusic_language("zh-CN") == "zh_CN"
    assert main.normalize_ytmusic_language("zh-TW") == "zh_TW"
    assert main.normalize_ytmusic_language("fr-FR") == "fr"
    assert main.normalize_ytmusic_language("xx-YY") == "en"


def test_preferred_video_thumbnail_upgrades_low_res_urls():
    assert main.preferred_video_thumbnail("abc123", "https://lh3.googleusercontent.com/=w120-h120") == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"
    assert main.preferred_video_thumbnail("abc123", "https://i.ytimg.com/vi/abc123/hqdefault.jpg") == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"


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
    monkeypatch.setattr(main, "search_provider_order", lambda: ["ytmusicapi"])

    def fake_search(query, limit):
        normalized = query.lower()
        if "coldplay" in normalized:
            return [
                {"id": "song-1", "title": "Clocks", "uploader": "Coldplay", "thumbnail": "", "duration": 307},
                {"id": "song-2", "title": "Adventure of a Lifetime", "uploader": "Coldplay", "thumbnail": "", "duration": 264},
            ][:limit]
        if "weeknd" in normalized:
            return [
                {"id": "song-3", "title": "Save Your Tears", "uploader": "The Weeknd", "thumbnail": "", "duration": 215},
                {"id": "song-4", "title": "Starboy", "uploader": "The Weeknd", "thumbnail": "", "duration": 230},
            ][:limit]
        return []

    main.SEARCH_RESULTS_CACHE.set(
        main.build_search_cache_key("Coldplay", 6, "ytmusicapi"),
        fake_search("Coldplay", 6),
        main.SEARCH_CACHE_TTL_SECONDS,
    )
    main.SEARCH_RESULTS_CACHE.set(
        main.build_search_cache_key("The Weeknd", 6, "ytmusicapi"),
        fake_search("The Weeknd", 6),
        main.SEARCH_CACHE_TTL_SECONDS,
    )

    payload = main.build_recommendations_payload()
    sections = {section.id: section for section in payload["sections"]}

    assert payload["mode"] == "mixed"
    assert "continue-listening" in sections
    assert "for-you" in sections
    assert "nas-curated" in sections
    assert sections["continue-listening"].items[0].title == "Take On Me"
    assert len(sections["for-you"].items) >= 2


def test_app_settings_roundtrip(isolated_library):
    settings = asyncio.run(main.get_app_settings())
    assert settings["runtimeMode"] in {"source", "packaged"}
    assert settings["downloadDirectory"]

    updated = asyncio.run(main.update_app_settings(main.AppSettingsUpdateRequest(downloadDirectory="~/Downloads/TestNAS")))
    assert updated["downloadDirectory"].endswith("TestNAS")
