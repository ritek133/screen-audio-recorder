"""VersionParser のユニットテストおよびプロパティベーステスト.

**Validates: Requirements 8**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from screen_audio_recorder.updater import VersionParser
from screen_audio_recorder.updater_models import Version


# ---------------------------------------------------------------------------
# ユニットテスト: VersionParser.parse() 正常系
# ---------------------------------------------------------------------------


class TestVersionParserParseValid:
    """VersionParser.parse() の正常系テスト."""

    def test_parse_simple_version(self) -> None:
        """"0.1.0" をパースできる."""
        result = VersionParser.parse("0.1.0")
        assert result == Version(major=0, minor=1, patch=0)

    def test_parse_with_lowercase_v_prefix(self) -> None:
        """"v1.2.3" をパースできる."""
        result = VersionParser.parse("v1.2.3")
        assert result == Version(major=1, minor=2, patch=3)

    def test_parse_with_uppercase_v_prefix(self) -> None:
        """"V10.20.30" をパースできる."""
        result = VersionParser.parse("V10.20.30")
        assert result == Version(major=10, minor=20, patch=30)


# ---------------------------------------------------------------------------
# ユニットテスト: VersionParser.parse() 異常系
# ---------------------------------------------------------------------------


class TestVersionParserParseInvalid:
    """VersionParser.parse() の異常系テスト."""

    def test_parse_non_numeric_returns_none(self) -> None:
        """"abc" は None を返す."""
        assert VersionParser.parse("abc") is None

    def test_parse_two_parts_returns_none(self) -> None:
        """"1.2" は None を返す."""
        assert VersionParser.parse("1.2") is None

    def test_parse_four_parts_returns_none(self) -> None:
        """"1.2.3.4" は None を返す."""
        assert VersionParser.parse("1.2.3.4") is None

    def test_parse_prerelease_returns_none(self) -> None:
        """"1.2.3-beta" は None を返す."""
        assert VersionParser.parse("1.2.3-beta") is None

    def test_parse_empty_string_returns_none(self) -> None:
        """空文字列は None を返す."""
        assert VersionParser.parse("") is None


# ---------------------------------------------------------------------------
# ユニットテスト: VersionParser.compare()
# ---------------------------------------------------------------------------


class TestVersionParserCompare:
    """VersionParser.compare() のテスト."""

    def test_compare_less_than(self) -> None:
        """current < latest の場合は -1 を返す."""
        current = Version(major=1, minor=0, patch=0)
        latest = Version(major=2, minor=0, patch=0)
        assert VersionParser.compare(current, latest) == -1

    def test_compare_equal(self) -> None:
        """current == latest の場合は 0 を返す."""
        current = Version(major=1, minor=2, patch=3)
        latest = Version(major=1, minor=2, patch=3)
        assert VersionParser.compare(current, latest) == 0

    def test_compare_greater_than(self) -> None:
        """current > latest の場合は 1 を返す."""
        current = Version(major=2, minor=0, patch=0)
        latest = Version(major=1, minor=0, patch=0)
        assert VersionParser.compare(current, latest) == 1

    def test_compare_major_priority(self) -> None:
        """MAJOR が大きければ MINOR, PATCH に関わらず大きい."""
        current = Version(major=2, minor=0, patch=0)
        latest = Version(major=1, minor=99, patch=99)
        assert VersionParser.compare(current, latest) == 1

    def test_compare_minor_priority(self) -> None:
        """MAJOR が同じなら MINOR で比較される."""
        current = Version(major=1, minor=2, patch=0)
        latest = Version(major=1, minor=3, patch=0)
        assert VersionParser.compare(current, latest) == -1

    def test_compare_patch_priority(self) -> None:
        """MAJOR, MINOR が同じなら PATCH で比較される."""
        current = Version(major=1, minor=2, patch=3)
        latest = Version(major=1, minor=2, patch=4)
        assert VersionParser.compare(current, latest) == -1


# ---------------------------------------------------------------------------
# プロパティベーステスト
# ---------------------------------------------------------------------------


@given(
    st.tuples(st.integers(0, 99), st.integers(0, 99), st.integers(0, 99)),
    st.tuples(st.integers(0, 99), st.integers(0, 99), st.integers(0, 99)),
    st.tuples(st.integers(0, 99), st.integers(0, 99), st.integers(0, 99)),
)
@settings(max_examples=200)
def test_version_comparison_transitivity(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    c: tuple[int, int, int],
) -> None:
    """Property 1: バージョン比較の推移律.

    任意の 3つの有効なバージョン a, b, c に対して、
    a < b かつ b < c ならば a < c でなければならない。

    **Validates: Requirements 8.3**
    """
    va = Version(major=a[0], minor=a[1], patch=a[2])
    vb = Version(major=b[0], minor=b[1], patch=b[2])
    vc = Version(major=c[0], minor=c[1], patch=c[2])

    cmp_ab = VersionParser.compare(va, vb)
    cmp_bc = VersionParser.compare(vb, vc)
    cmp_ac = VersionParser.compare(va, vc)

    # a < b かつ b < c ならば a < c
    if cmp_ab == -1 and cmp_bc == -1:
        assert cmp_ac == -1, (
            f"推移律違反: {va} < {vb} かつ {vb} < {vc} だが {va} >= {vc}"
        )

    # a > b かつ b > c ならば a > c
    if cmp_ab == 1 and cmp_bc == 1:
        assert cmp_ac == 1, (
            f"推移律違反: {va} > {vb} かつ {vb} > {vc} だが {va} <= {vc}"
        )


@given(st.tuples(st.integers(0, 99), st.integers(0, 99), st.integers(0, 99)))
@settings(max_examples=100)
def test_version_comparison_reflexivity(
    v: tuple[int, int, int],
) -> None:
    """Property 2: バージョン比較の反射律.

    任意の有効なバージョン v に対して、compare(v, v) == 0 でなければならない。

    **Validates: Requirements 8.5**
    """
    version = Version(major=v[0], minor=v[1], patch=v[2])
    assert VersionParser.compare(version, version) == 0, (
        f"反射律違反: compare({version}, {version}) != 0"
    )


@given(st.integers(0, 99), st.integers(0, 99), st.integers(0, 99))
@settings(max_examples=100)
def test_version_prefix_normalization(
    major: int,
    minor: int,
    patch: int,
) -> None:
    """Property 4: "v" プレフィックスの正規化.

    任意の有効なバージョン文字列 X.Y.Z に対して、
    parse("vX.Y.Z") == parse("X.Y.Z") == parse("VX.Y.Z") でなければならない。

    **Validates: Requirements 8.2**
    """
    version_str = f"{major}.{minor}.{patch}"
    v_lower = f"v{version_str}"
    v_upper = f"V{version_str}"

    result_plain = VersionParser.parse(version_str)
    result_v_lower = VersionParser.parse(v_lower)
    result_v_upper = VersionParser.parse(v_upper)

    assert result_plain is not None, f"parse('{version_str}') が None を返した"
    assert result_plain == result_v_lower, (
        f"正規化違反: parse('{version_str}') != parse('{v_lower}')"
    )
    assert result_plain == result_v_upper, (
        f"正規化違反: parse('{version_str}') != parse('{v_upper}')"
    )


# ---------------------------------------------------------------------------
# GitHubClient テスト
# ---------------------------------------------------------------------------

import io
import json
import threading
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from screen_audio_recorder.updater import GitHubClient
from screen_audio_recorder.updater_models import (
    DownloadCancelledError,
    DownloadError,
    ReleaseInfo,
    UpdateCheckError,
    UpdateType,
)


def _make_release_json(
    tag_name: str = "v1.2.0",
    body: str = "Release notes",
    assets: list[dict] | None = None,
) -> bytes:
    """テスト用の GitHub API レスポンス JSON を生成する."""
    if assets is None:
        assets = []
    data = {
        "tag_name": tag_name,
        "body": body,
        "assets": assets,
    }
    return json.dumps(data).encode("utf-8")


def _make_asset(name: str, size: int = 1024, url: str = "") -> dict:
    """テスト用アセット辞書を生成する."""
    return {
        "name": name,
        "size": size,
        "browser_download_url": url or f"https://github.com/download/{name}",
    }


class TestGitHubClientFetchLatestRelease:
    """GitHubClient.fetch_latest_release() のモックテスト."""

    def _create_mock_response(self, data: bytes, status_code: int = 200) -> MagicMock:
        """urlopen の戻り値として使うモックレスポンスを作成する."""
        mock_response = MagicMock()
        mock_response.read.return_value = data
        mock_response.getcode.return_value = status_code
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        return mock_response

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_zip_and_exe_release_returns_full(self, mock_urlopen: MagicMock) -> None:
        """zip+exe リリースの場合、UpdateType.FULL と判定される."""
        assets = [
            _make_asset("screen-audio-recorder-v1.2.0-full.zip", size=400_000_000),
            _make_asset("screen-audio-recorder-v1.2.0.exe", size=50_000_000),
        ]
        data = _make_release_json(tag_name="v1.2.0", assets=assets)
        mock_urlopen.return_value = self._create_mock_response(data)

        client = GitHubClient("owner", "repo")
        result = client.fetch_latest_release()

        assert isinstance(result, ReleaseInfo)
        assert result.update_type == UpdateType.FULL
        assert result.version.major == 1
        assert result.version.minor == 2
        assert result.version.patch == 0
        assert result.target_asset.name == "screen-audio-recorder-v1.2.0-full.zip"

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_exe_only_release_returns_exe_only(self, mock_urlopen: MagicMock) -> None:
        """exe のみリリースの場合、UpdateType.EXE_ONLY と判定される."""
        assets = [
            _make_asset("screen-audio-recorder-v1.2.0.exe", size=50_000_000),
        ]
        data = _make_release_json(tag_name="v1.2.0", assets=assets)
        mock_urlopen.return_value = self._create_mock_response(data)

        client = GitHubClient("owner", "repo")
        result = client.fetch_latest_release()

        assert isinstance(result, ReleaseInfo)
        assert result.update_type == UpdateType.EXE_ONLY
        assert result.target_asset.name == "screen-audio-recorder-v1.2.0.exe"

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_release_notes_parsed(self, mock_urlopen: MagicMock) -> None:
        """リリースノートが正しくパースされる."""
        assets = [_make_asset("screen-audio-recorder-v1.0.0.exe")]
        data = _make_release_json(
            tag_name="v1.0.0", body="## 変更点\n- 新機能追加", assets=assets
        )
        mock_urlopen.return_value = self._create_mock_response(data)

        client = GitHubClient("owner", "repo")
        result = client.fetch_latest_release()

        assert result.release_notes == "## 変更点\n- 新機能追加"
        assert result.tag_name == "v1.0.0"

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_no_matching_assets_raises_error(self, mock_urlopen: MagicMock) -> None:
        """対応するアセットが見つからない場合は UpdateCheckError を送出する."""
        assets = [_make_asset("unrelated-file.txt")]
        data = _make_release_json(tag_name="v1.0.0", assets=assets)
        mock_urlopen.return_value = self._create_mock_response(data)

        client = GitHubClient("owner", "repo")
        with pytest.raises(UpdateCheckError, match="対応するアセットが見つかりません"):
            client.fetch_latest_release()


class TestGitHubClientFetchLatestReleaseErrors:
    """GitHubClient.fetch_latest_release() の異常系テスト."""

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_timeout_raises_update_check_error(self, mock_urlopen: MagicMock) -> None:
        """タイムアウト時に UpdateCheckError を送出する."""
        mock_urlopen.side_effect = TimeoutError("timed out")

        client = GitHubClient("owner", "repo")
        with pytest.raises(UpdateCheckError, match="タイムアウト"):
            client.fetch_latest_release()

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_http_404_raises_update_check_error(self, mock_urlopen: MagicMock) -> None:
        """HTTP 404 の場合に UpdateCheckError を送出する."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.github.com/repos/owner/repo/releases/latest",
            code=404,
            msg="Not Found",
            hdrs={},  # type: ignore[arg-type]
            fp=None,
        )

        client = GitHubClient("owner", "repo")
        with pytest.raises(UpdateCheckError, match="HTTP 404"):
            client.fetch_latest_release()

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_invalid_json_raises_update_check_error(
        self, mock_urlopen: MagicMock
    ) -> None:
        """不正 JSON の場合に UpdateCheckError を送出する."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"this is not json {{{}"
        mock_response.getcode.return_value = 200
        mock_urlopen.return_value = mock_response

        client = GitHubClient("owner", "repo")
        with pytest.raises(UpdateCheckError, match="パース失敗"):
            client.fetch_latest_release()

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_url_error_raises_update_check_error(self, mock_urlopen: MagicMock) -> None:
        """URLError（接続不能）の場合に UpdateCheckError を送出する."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        client = GitHubClient("owner", "repo")
        with pytest.raises(UpdateCheckError, match="接続エラー"):
            client.fetch_latest_release()

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_invalid_version_tag_raises_update_check_error(
        self, mock_urlopen: MagicMock
    ) -> None:
        """バージョンタグが不正な場合に UpdateCheckError を送出する."""
        assets = [_make_asset("screen-audio-recorder-v1.0.0.exe")]
        data = _make_release_json(tag_name="invalid-tag", assets=assets)
        mock_response = MagicMock()
        mock_response.read.return_value = data
        mock_response.getcode.return_value = 200
        mock_urlopen.return_value = mock_response

        client = GitHubClient("owner", "repo")
        with pytest.raises(UpdateCheckError, match="無効なバージョンタグ"):
            client.fetch_latest_release()


class TestGitHubClientDownloadAsset:
    """GitHubClient.download_asset() のモックテスト."""

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_download_with_progress_callback(
        self, mock_urlopen: MagicMock, tmp_path: Path
    ) -> None:
        """ダウンロード中に進捗コールバックが呼ばれる."""
        # 24KB のデータ（3チャンク分: 8KB + 8KB + 8KB）
        file_data = b"x" * 24576
        mock_response = MagicMock()
        # read() が 8KB ずつ返し、最後に空バイトを返す
        mock_response.read.side_effect = [
            file_data[:8192],
            file_data[8192:16384],
            file_data[16384:],
            b"",
        ]
        mock_urlopen.return_value = mock_response

        progress_calls: list[tuple[int, int]] = []

        def on_progress(downloaded: int, total: int) -> None:
            progress_calls.append((downloaded, total))

        dest = tmp_path / "download.exe"
        client = GitHubClient("owner", "repo")
        result = client.download_asset(
            url="https://github.com/download/test.exe",
            dest_path=dest,
            expected_size=24576,
            on_progress=on_progress,
        )

        assert result == dest
        assert dest.exists()
        assert dest.stat().st_size == 24576
        # 3 チャンクなので 3 回のコールバック
        assert len(progress_calls) == 3
        assert progress_calls[0] == (8192, 24576)
        assert progress_calls[1] == (16384, 24576)
        assert progress_calls[2] == (24576, 24576)

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_download_cancel_raises_cancelled_error(
        self, mock_urlopen: MagicMock, tmp_path: Path
    ) -> None:
        """キャンセルイベントが設定された場合、DownloadCancelledError を送出する."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"x" * 8192
        mock_urlopen.return_value = mock_response

        cancel_event = threading.Event()
        cancel_event.set()  # 事前にキャンセル状態にする

        dest = tmp_path / "download.exe"
        client = GitHubClient("owner", "repo")

        with pytest.raises(DownloadCancelledError, match="キャンセル"):
            client.download_asset(
                url="https://github.com/download/test.exe",
                dest_path=dest,
                expected_size=8192,
                cancel_event=cancel_event,
            )

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_download_size_mismatch_raises_download_error(
        self, mock_urlopen: MagicMock, tmp_path: Path
    ) -> None:
        """ダウンロードサイズが期待と不一致の場合、DownloadError を送出する."""
        # 期待サイズは 16384 だが実際は 8192 しかダウンロードされない
        mock_response = MagicMock()
        mock_response.read.side_effect = [b"x" * 8192, b""]
        mock_urlopen.return_value = mock_response

        dest = tmp_path / "download.exe"
        client = GitHubClient("owner", "repo")

        with pytest.raises(DownloadError, match="サイズ不一致"):
            client.download_asset(
                url="https://github.com/download/test.exe",
                dest_path=dest,
                expected_size=16384,
            )

        # サイズ不一致時は一時ファイルが削除される
        assert not dest.exists()

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_download_http_error_raises_download_error(
        self, mock_urlopen: MagicMock, tmp_path: Path
    ) -> None:
        """HTTP エラー時に DownloadError を送出する."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://github.com/download/test.exe",
            code=500,
            msg="Internal Server Error",
            hdrs={},  # type: ignore[arg-type]
            fp=None,
        )

        dest = tmp_path / "download.exe"
        client = GitHubClient("owner", "repo")

        with pytest.raises(DownloadError, match="HTTP 500"):
            client.download_asset(
                url="https://github.com/download/test.exe",
                dest_path=dest,
                expected_size=1024,
            )

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_download_timeout_raises_download_error(
        self, mock_urlopen: MagicMock, tmp_path: Path
    ) -> None:
        """ダウンロードタイムアウト時に DownloadError を送出する."""
        mock_urlopen.side_effect = TimeoutError("download timed out")

        dest = tmp_path / "download.exe"
        client = GitHubClient("owner", "repo")

        with pytest.raises(DownloadError, match="タイムアウト"):
            client.download_asset(
                url="https://github.com/download/test.exe",
                dest_path=dest,
                expected_size=1024,
            )

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_download_cancel_mid_transfer(
        self, mock_urlopen: MagicMock, tmp_path: Path
    ) -> None:
        """ダウンロード途中でキャンセルされた場合、DownloadCancelledError を送出する."""
        cancel_event = threading.Event()

        mock_response = MagicMock()
        mock_response.read.side_effect = [b"x" * 8192, b"x" * 8192, b""]
        mock_urlopen.return_value = mock_response

        # 最初のチャンク読み込み後にキャンセルを発行するコールバック
        def on_progress(downloaded: int, total: int) -> None:
            if downloaded >= 8192:
                cancel_event.set()

        dest = tmp_path / "download.exe"
        client = GitHubClient("owner", "repo")

        with pytest.raises(DownloadCancelledError):
            client.download_asset(
                url="https://github.com/download/test.exe",
                dest_path=dest,
                expected_size=24576,
                on_progress=on_progress,
                cancel_event=cancel_event,
            )

    @patch("screen_audio_recorder.updater.urllib.request.urlopen")
    def test_download_creates_parent_directory(
        self, mock_urlopen: MagicMock, tmp_path: Path
    ) -> None:
        """保存先の親ディレクトリが存在しない場合、自動作成される."""
        file_data = b"x" * 1024
        mock_response = MagicMock()
        mock_response.read.side_effect = [file_data, b""]
        mock_urlopen.return_value = mock_response

        dest = tmp_path / "subdir" / "nested" / "download.exe"
        client = GitHubClient("owner", "repo")
        result = client.download_asset(
            url="https://github.com/download/test.exe",
            dest_path=dest,
            expected_size=1024,
        )

        assert result == dest
        assert dest.exists()
        assert dest.stat().st_size == 1024


# ---------------------------------------------------------------------------
# UpdateApplier テスト
# ---------------------------------------------------------------------------

import shutil

from screen_audio_recorder.updater import UpdateApplier
from screen_audio_recorder.updater_models import ApplyError, BackupInfo


class TestUpdateApplierCreateBackup:
    """UpdateApplier.create_backup() のテスト."""

    def test_exe_only_backup_renames_exe(self, tmp_path: Path) -> None:
        """通常更新: exe を {stem}-v{version}.exe.bak にリネームする."""
        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"fake exe content")
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        result = applier.create_backup("0.1.0", UpdateType.EXE_ONLY)

        expected_backup = tmp_path / "screen-audio-recorder-v0.1.0.exe.bak"
        assert result.backup_path == expected_backup
        assert expected_backup.exists()
        assert not exe_path.exists()
        assert result.version == "0.1.0"
        assert result.update_type == UpdateType.EXE_ONLY

    def test_full_backup_renames_app_dir(self, tmp_path: Path) -> None:
        """フル更新: app_dir を app-backup-v{version} にリネームする."""
        exe_path = tmp_path / "app" / "screen-audio-recorder.exe"
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        exe_path.write_bytes(b"fake exe content")
        (app_dir / "_internal").mkdir()

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        result = applier.create_backup("1.2.3", UpdateType.FULL)

        expected_backup = tmp_path / "app-backup-v1.2.3"
        assert result.backup_path == expected_backup
        assert expected_backup.exists()
        assert expected_backup.is_dir()
        assert not app_dir.exists()
        assert result.version == "1.2.3"
        assert result.update_type == UpdateType.FULL


class TestUpdateApplierCreateBackupFailure:
    """UpdateApplier.create_backup() の失敗テスト."""

    def test_exe_not_exists_raises_apply_error(self, tmp_path: Path) -> None:
        """存在しない exe をバックアップしようとすると ApplyError が発生する."""
        exe_path = tmp_path / "nonexistent.exe"
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        with pytest.raises(ApplyError):
            applier.create_backup("0.1.0", UpdateType.EXE_ONLY)

    def test_app_dir_not_exists_raises_apply_error(self, tmp_path: Path) -> None:
        """存在しない app_dir をバックアップしようとすると ApplyError が発生する."""
        exe_path = tmp_path / "app" / "screen-audio-recorder.exe"
        app_dir = tmp_path / "app"  # 存在しない

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        with pytest.raises(ApplyError):
            applier.create_backup("0.1.0", UpdateType.FULL)


class TestUpdateApplierGenerateUpdateScript:
    """UpdateApplier.generate_update_script() のテスト."""

    def test_exe_only_script_contains_expected_keywords(self, tmp_path: Path) -> None:
        """通常更新スクリプトに move, start, PID 関連キーワードが含まれる."""
        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"fake")
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        backup_info = BackupInfo(
            backup_path=tmp_path / "screen-audio-recorder-v0.1.0.exe.bak",
            version="0.1.0",
            update_type=UpdateType.EXE_ONLY,
            created_at=datetime.now(),
        )

        new_file = tmp_path / "new.exe"
        new_file.write_bytes(b"new exe")
        target_path = exe_path

        script_path = applier.generate_update_script(
            update_type=UpdateType.EXE_ONLY,
            new_file_path=new_file,
            target_path=target_path,
            backup_info=backup_info,
        )

        assert script_path.exists()
        assert script_path.suffix == ".bat"
        content = script_path.read_text(encoding="shift_jis")
        assert "move" in content.lower()
        assert "start" in content.lower()
        assert "PID" in content

    def test_full_update_script_contains_expected_keywords(self, tmp_path: Path) -> None:
        """フル更新スクリプトに move, start, rmdir, PID 関連キーワードが含まれる."""
        exe_path = tmp_path / "app" / "screen-audio-recorder.exe"
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        exe_path.write_bytes(b"fake")

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        backup_info = BackupInfo(
            backup_path=tmp_path / "app-backup-v0.1.0",
            version="0.1.0",
            update_type=UpdateType.FULL,
            created_at=datetime.now(),
        )

        new_dir = tmp_path / "new_app"
        new_dir.mkdir()
        target_path = app_dir

        script_path = applier.generate_update_script(
            update_type=UpdateType.FULL,
            new_file_path=new_dir,
            target_path=target_path,
            backup_info=backup_info,
        )

        assert script_path.exists()
        assert script_path.suffix == ".bat"
        content = script_path.read_text(encoding="shift_jis")
        assert "move" in content.lower()
        assert "start" in content.lower()
        assert "rmdir" in content.lower()
        assert "PID" in content


class TestUpdateApplierGenerateRollbackScript:
    """UpdateApplier.generate_rollback_script() のテスト."""

    def test_exe_rollback_script_generated(self, tmp_path: Path) -> None:
        """EXE_ONLY のロールバックスクリプトが正しく生成される."""
        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"fake")
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        backup_info = BackupInfo(
            backup_path=tmp_path / "screen-audio-recorder-v0.1.0.exe.bak",
            version="0.1.0",
            update_type=UpdateType.EXE_ONLY,
            created_at=datetime.now(),
        )

        script_path = applier.generate_rollback_script(backup_info)

        assert script_path.exists()
        assert script_path.suffix == ".bat"
        content = script_path.read_text(encoding="shift_jis")
        assert "move" in content.lower()
        assert "start" in content.lower()
        assert "PID" in content

    def test_full_rollback_script_generated(self, tmp_path: Path) -> None:
        """FULL のロールバックスクリプトが正しく生成される."""
        exe_path = tmp_path / "app" / "screen-audio-recorder.exe"
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        exe_path.write_bytes(b"fake")

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        backup_info = BackupInfo(
            backup_path=tmp_path / "app-backup-v0.1.0",
            version="0.1.0",
            update_type=UpdateType.FULL,
            created_at=datetime.now(),
        )

        script_path = applier.generate_rollback_script(backup_info)

        assert script_path.exists()
        assert script_path.suffix == ".bat"
        content = script_path.read_text(encoding="shift_jis")
        assert "move" in content.lower()
        assert "start" in content.lower()
        assert "rmdir" in content.lower()
        assert "PID" in content


class TestUpdateApplierFindBackup:
    """UpdateApplier.find_backup() のテスト."""

    def test_find_exe_backup_exists(self, tmp_path: Path) -> None:
        """exe.bak ファイルが存在する場合、BackupInfo を返す."""
        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"current exe")
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        # バックアップファイルを作成
        backup_file = tmp_path / "screen-audio-recorder-v0.1.0.exe.bak"
        backup_file.write_bytes(b"old exe")

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        result = applier.find_backup()

        assert result is not None
        assert result.backup_path == backup_file
        assert result.version == "0.1.0"
        assert result.update_type == UpdateType.EXE_ONLY

    def test_find_full_backup_exists(self, tmp_path: Path) -> None:
        """app-backup-v* ディレクトリが存在する場合、BackupInfo を返す."""
        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"current exe")
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        # バックアップディレクトリを作成
        backup_dir = tmp_path / "app-backup-v1.0.0"
        backup_dir.mkdir()

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        result = applier.find_backup()

        assert result is not None
        assert result.backup_path == backup_dir
        assert result.version == "1.0.0"
        assert result.update_type == UpdateType.FULL

    def test_find_backup_none_when_no_backup(self, tmp_path: Path) -> None:
        """バックアップが存在しない場合、None を返す."""
        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"current exe")
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        result = applier.find_backup()

        assert result is None


class TestUpdateApplierCleanupOldBackups:
    """UpdateApplier.cleanup_old_backups() のテスト."""

    def test_cleanup_removes_exe_bak_files(self, tmp_path: Path) -> None:
        """*.exe.bak ファイルが削除される."""
        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"current exe")
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        # バックアップファイルを作成
        bak1 = tmp_path / "screen-audio-recorder-v0.1.0.exe.bak"
        bak1.write_bytes(b"old exe 1")
        bak2 = tmp_path / "screen-audio-recorder-v0.2.0.exe.bak"
        bak2.write_bytes(b"old exe 2")

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        applier.cleanup_old_backups()

        assert not bak1.exists()
        assert not bak2.exists()

    def test_cleanup_removes_backup_directories(self, tmp_path: Path) -> None:
        """app-backup-v* ディレクトリが削除される."""
        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"current exe")
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        # バックアップディレクトリを作成
        backup_dir1 = tmp_path / "app-backup-v0.1.0"
        backup_dir1.mkdir()
        (backup_dir1 / "some_file.txt").write_text("content")
        backup_dir2 = tmp_path / "app-backup-v0.2.0"
        backup_dir2.mkdir()

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        applier.cleanup_old_backups()

        assert not backup_dir1.exists()
        assert not backup_dir2.exists()

    def test_cleanup_preserves_non_backup_files(self, tmp_path: Path) -> None:
        """バックアップ以外のファイルは削除されない."""
        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"current exe")
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        # バックアップファイル
        bak = tmp_path / "screen-audio-recorder-v0.1.0.exe.bak"
        bak.write_bytes(b"old")
        # 通常のファイル（削除されるべきでない）
        other_file = tmp_path / "config.json"
        other_file.write_text("{}")

        applier = UpdateApplier(exe_path=exe_path, app_dir=app_dir)
        applier.cleanup_old_backups()

        assert not bak.exists()
        assert other_file.exists()


# ---------------------------------------------------------------------------
# Updater クラスのテスト
# ---------------------------------------------------------------------------

import time

from screen_audio_recorder.updater import Updater
from screen_audio_recorder.updater_models import (
    AssetInfo,
    DownloadProgress,
    RollbackError,
    UpdateState,
    UpdateStatus,
)


class TestUpdaterCheckForUpdateAvailable:
    """Updater.check_for_update() - 更新ありの場合."""

    @patch("screen_audio_recorder.updater.GitHubClient.fetch_latest_release")
    def test_update_available_notifies_checking_then_available(
        self, mock_fetch: MagicMock, tmp_path: Path
    ) -> None:
        """更新がある場合、CHECKING → UPDATE_AVAILABLE の順にコールバックされる."""
        release_info = ReleaseInfo(
            tag_name="v2.0.0",
            version=Version(major=2, minor=0, patch=0),
            release_notes="New version",
            assets=[],
            update_type=UpdateType.EXE_ONLY,
            target_asset=AssetInfo(
                name="screen-audio-recorder-v2.0.0.exe",
                size=50_000_000,
                download_url="https://github.com/download/test.exe",
            ),
        )
        mock_fetch.return_value = release_info

        statuses: list[UpdateStatus] = []
        done_event = threading.Event()

        def on_status_changed(status: UpdateStatus) -> None:
            statuses.append(status)
            if status.state in (UpdateState.UPDATE_AVAILABLE, UpdateState.ERROR):
                done_event.set()

        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"fake")

        updater = Updater(
            repo_owner="owner",
            repo_name="repo",
            current_version="1.0.0",
            exe_path=exe_path,
            on_status_changed=on_status_changed,
        )
        updater.check_for_update()

        assert done_event.wait(timeout=5), "コールバックがタイムアウトしました"

        assert len(statuses) >= 2
        assert statuses[0].state == UpdateState.CHECKING
        assert statuses[1].state == UpdateState.UPDATE_AVAILABLE
        assert statuses[1].version == "2.0.0"


class TestUpdaterCheckForUpdateUpToDate:
    """Updater.check_for_update() - 最新の場合."""

    @patch("screen_audio_recorder.updater.GitHubClient.fetch_latest_release")
    def test_up_to_date_notifies_checking_then_up_to_date(
        self, mock_fetch: MagicMock, tmp_path: Path
    ) -> None:
        """最新バージョンの場合、CHECKING → UP_TO_DATE の順にコールバックされる."""
        release_info = ReleaseInfo(
            tag_name="v1.0.0",
            version=Version(major=1, minor=0, patch=0),
            release_notes="Current version",
            assets=[],
            update_type=UpdateType.EXE_ONLY,
            target_asset=AssetInfo(
                name="screen-audio-recorder-v1.0.0.exe",
                size=50_000_000,
                download_url="https://github.com/download/test.exe",
            ),
        )
        mock_fetch.return_value = release_info

        statuses: list[UpdateStatus] = []
        done_event = threading.Event()

        def on_status_changed(status: UpdateStatus) -> None:
            statuses.append(status)
            if status.state in (UpdateState.UP_TO_DATE, UpdateState.ERROR):
                done_event.set()

        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"fake")

        updater = Updater(
            repo_owner="owner",
            repo_name="repo",
            current_version="1.0.0",
            exe_path=exe_path,
            on_status_changed=on_status_changed,
        )
        updater.check_for_update()

        assert done_event.wait(timeout=5), "コールバックがタイムアウトしました"

        assert len(statuses) >= 2
        assert statuses[0].state == UpdateState.CHECKING
        assert statuses[1].state == UpdateState.UP_TO_DATE


class TestUpdaterCheckForUpdateError:
    """Updater.check_for_update() - エラーの場合."""

    @patch("screen_audio_recorder.updater.GitHubClient.fetch_latest_release")
    def test_error_notifies_checking_then_error(
        self, mock_fetch: MagicMock, tmp_path: Path
    ) -> None:
        """エラーが発生した場合、CHECKING → ERROR の順にコールバックされる."""
        mock_fetch.side_effect = UpdateCheckError("接続タイムアウト")

        statuses: list[UpdateStatus] = []
        done_event = threading.Event()

        def on_status_changed(status: UpdateStatus) -> None:
            statuses.append(status)
            if status.state == UpdateState.ERROR:
                done_event.set()

        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"fake")

        updater = Updater(
            repo_owner="owner",
            repo_name="repo",
            current_version="1.0.0",
            exe_path=exe_path,
            on_status_changed=on_status_changed,
        )
        updater.check_for_update()

        assert done_event.wait(timeout=5), "コールバックがタイムアウトしました"

        assert len(statuses) >= 2
        assert statuses[0].state == UpdateState.CHECKING
        assert statuses[1].state == UpdateState.ERROR
        assert "接続タイムアウト" in (statuses[1].error or "")


class TestUpdaterDownloadAndApply:
    """Updater.download_and_apply() - 正常系."""

    @patch("screen_audio_recorder.updater.UpdateApplier.launch_script_and_exit")
    @patch("screen_audio_recorder.updater.UpdateApplier.generate_update_script")
    @patch("screen_audio_recorder.updater.UpdateApplier.create_backup")
    @patch("screen_audio_recorder.updater.GitHubClient.download_asset")
    @patch("screen_audio_recorder.updater.shutil.disk_usage")
    def test_download_and_apply_success_exe_only(
        self,
        mock_disk_usage: MagicMock,
        mock_download: MagicMock,
        mock_backup: MagicMock,
        mock_gen_script: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """EXE_ONLY の正常更新フロー: ダウンロード → バックアップ → スクリプト生成 → 起動."""
        # ディスク容量: 十分な空き
        mock_disk_usage.return_value = MagicMock(free=500_000_000)

        # ダウンロード: 一時ファイルを返す
        download_dest = tmp_path / "download" / "screen-audio-recorder-v2.0.0.exe"
        download_dest.parent.mkdir(parents=True, exist_ok=True)
        download_dest.write_bytes(b"x" * 50_000_000)

        def fake_download(url, dest_path, expected_size, on_progress=None, cancel_event=None):
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"x" * expected_size)
            return dest_path

        mock_download.side_effect = fake_download

        # バックアップ: BackupInfo を返す
        backup_info = BackupInfo(
            backup_path=tmp_path / "screen-audio-recorder-v1.0.0.exe.bak",
            version="1.0.0",
            update_type=UpdateType.EXE_ONLY,
            created_at=datetime.now(),
        )
        mock_backup.return_value = backup_info

        # スクリプト生成: スクリプトパスを返す
        script_path = tmp_path / "update.bat"
        script_path.write_text("@echo off")
        mock_gen_script.return_value = script_path

        # launch_script_and_exit: 何もしない（sys.exit を防ぐ）
        mock_launch.return_value = None

        statuses: list[UpdateStatus] = []
        done_event = threading.Event()

        def on_status_changed(status: UpdateStatus) -> None:
            statuses.append(status)
            if status.state in (UpdateState.COMPLETED, UpdateState.ERROR):
                done_event.set()

        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"fake exe")

        updater = Updater(
            repo_owner="owner",
            repo_name="repo",
            current_version="1.0.0",
            exe_path=exe_path,
            on_status_changed=on_status_changed,
        )

        release_info = ReleaseInfo(
            tag_name="v2.0.0",
            version=Version(major=2, minor=0, patch=0),
            release_notes="New version",
            assets=[],
            update_type=UpdateType.EXE_ONLY,
            target_asset=AssetInfo(
                name="screen-audio-recorder-v2.0.0.exe",
                size=50_000_000,
                download_url="https://github.com/download/test.exe",
            ),
        )
        updater.download_and_apply(release_info)

        assert done_event.wait(timeout=5), "コールバックがタイムアウトしました"

        # バックアップ作成が呼ばれたことを確認
        mock_backup.assert_called_once_with("1.0.0", UpdateType.EXE_ONLY)

        # スクリプト生成が呼ばれたことを確認
        mock_gen_script.assert_called_once()

        # launch_script_and_exit が呼ばれたことを確認
        mock_launch.assert_called_once_with(script_path)

        # ステータス遷移の確認
        states = [s.state for s in statuses]
        assert UpdateState.DOWNLOADING in states
        assert UpdateState.APPLYING in states
        assert UpdateState.COMPLETED in states


class TestUpdaterDownloadAndApplyDiskSpace:
    """Updater.download_and_apply() - ディスク容量不足."""

    @patch("screen_audio_recorder.updater.shutil.disk_usage")
    def test_disk_space_insufficient_notifies_error(
        self, mock_disk_usage: MagicMock, tmp_path: Path
    ) -> None:
        """ディスク容量不足の場合、ERROR ステータスが通知される."""
        # 空き容量: 1MB（必要: 100MB = 50MB * 2）
        mock_disk_usage.return_value = MagicMock(free=1_000_000)

        statuses: list[UpdateStatus] = []
        done_event = threading.Event()

        def on_status_changed(status: UpdateStatus) -> None:
            statuses.append(status)
            if status.state == UpdateState.ERROR:
                done_event.set()

        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"fake exe")

        updater = Updater(
            repo_owner="owner",
            repo_name="repo",
            current_version="1.0.0",
            exe_path=exe_path,
            on_status_changed=on_status_changed,
        )

        release_info = ReleaseInfo(
            tag_name="v2.0.0",
            version=Version(major=2, minor=0, patch=0),
            release_notes="New version",
            assets=[],
            update_type=UpdateType.EXE_ONLY,
            target_asset=AssetInfo(
                name="screen-audio-recorder-v2.0.0.exe",
                size=50_000_000,
                download_url="https://github.com/download/test.exe",
            ),
        )
        updater.download_and_apply(release_info)

        assert done_event.wait(timeout=5), "コールバックがタイムアウトしました"

        # ERROR ステータスにディスク容量のエラーが含まれる
        error_statuses = [s for s in statuses if s.state == UpdateState.ERROR]
        assert len(error_statuses) == 1
        assert "ディスク容量" in error_statuses[0].message


class TestUpdaterCancelDownload:
    """Updater.cancel_download() のテスト."""

    def test_cancel_sets_cancel_event(self, tmp_path: Path) -> None:
        """cancel_download() を呼ぶと内部の _cancel_event がセットされる."""
        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"fake")

        updater = Updater(
            repo_owner="owner",
            repo_name="repo",
            current_version="1.0.0",
            exe_path=exe_path,
        )

        # 初期状態ではセットされていない
        assert not updater._cancel_event.is_set()

        # cancel_download() でセットされる
        updater.cancel_download()
        assert updater._cancel_event.is_set()


class TestUpdaterRollback:
    """Updater.rollback() のテスト."""

    @patch("screen_audio_recorder.updater.UpdateApplier.launch_script_and_exit")
    @patch("screen_audio_recorder.updater.UpdateApplier.generate_rollback_script")
    @patch("screen_audio_recorder.updater.UpdateApplier.find_backup")
    def test_rollback_triggers_script_generation_and_launch(
        self,
        mock_find_backup: MagicMock,
        mock_gen_rollback: MagicMock,
        mock_launch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """バックアップが存在する場合、ロールバックスクリプトを生成して起動する."""
        backup_info = BackupInfo(
            backup_path=tmp_path / "screen-audio-recorder-v1.0.0.exe.bak",
            version="1.0.0",
            update_type=UpdateType.EXE_ONLY,
            created_at=datetime.now(),
        )
        mock_find_backup.return_value = backup_info

        script_path = tmp_path / "rollback.bat"
        script_path.write_text("@echo off")
        mock_gen_rollback.return_value = script_path

        mock_launch.return_value = None

        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"fake")

        updater = Updater(
            repo_owner="owner",
            repo_name="repo",
            current_version="2.0.0",
            exe_path=exe_path,
        )
        updater.rollback()

        mock_find_backup.assert_called_once()
        mock_gen_rollback.assert_called_once_with(backup_info)
        mock_launch.assert_called_once_with(script_path)

    @patch("screen_audio_recorder.updater.UpdateApplier.find_backup")
    def test_rollback_no_backup_notifies_error(
        self, mock_find_backup: MagicMock, tmp_path: Path
    ) -> None:
        """バックアップが存在しない場合、ERROR ステータスが通知される."""
        mock_find_backup.return_value = None

        statuses: list[UpdateStatus] = []

        def on_status_changed(status: UpdateStatus) -> None:
            statuses.append(status)

        exe_path = tmp_path / "screen-audio-recorder.exe"
        exe_path.write_bytes(b"fake")

        updater = Updater(
            repo_owner="owner",
            repo_name="repo",
            current_version="2.0.0",
            exe_path=exe_path,
            on_status_changed=on_status_changed,
        )
        updater.rollback()

        assert len(statuses) == 1
        assert statuses[0].state == UpdateState.ERROR
        assert "バックアップが見つかりません" in (statuses[0].error or "")
