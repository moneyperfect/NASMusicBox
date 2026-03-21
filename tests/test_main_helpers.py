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

    system_check = main.get_system_check()
    assert system_check["appVersion"] == APP_VERSION
    assert system_check["libraryDbAvailable"] is True
    assert system_check["frontendBuilt"] is True
