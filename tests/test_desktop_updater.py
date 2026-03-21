from __future__ import annotations

from desktop_updater import is_newer_version, parse_release


def test_is_newer_version_handles_semver_numbers():
    assert is_newer_version("v1.10.0", "1.9.9") is True
    assert is_newer_version("1.1.1", "1.1.0") is True
    assert is_newer_version("1.1.0", "1.1.0") is False
    assert is_newer_version("1.0.9", "1.1.0") is False


def test_parse_release_prefers_installer_and_portable_assets():
    release = parse_release(
        {
            "tag_name": "v1.2.0",
            "name": "NAS音乐器 1.2.0",
            "html_url": "https://github.com/moneyperfect/NASMusicBox/releases/tag/v1.2.0",
            "published_at": "2026-03-21T00:00:00Z",
            "assets": [
                {
                    "name": "NASMusicBox-portable-v1.2.0.zip",
                    "browser_download_url": "https://example.com/portable.zip",
                    "size": 2048,
                    "content_type": "application/zip",
                },
                {
                    "name": "NASMusicBox-Setup-v1.2.0.exe",
                    "browser_download_url": "https://example.com/setup.exe",
                    "size": 4096,
                    "content_type": "application/vnd.microsoft.portable-executable",
                },
            ],
        }
    )

    assert release is not None
    assert release.version == "1.2.0"
    assert release.installer_asset is not None
    assert release.installer_asset.name.endswith(".exe")
    assert release.portable_asset is not None
    assert release.portable_asset.name.endswith(".zip")
    assert release.preferred_asset == release.installer_asset
