"""自動更新機能モジュール."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .updater_models import (
    ApplyError,
    AssetInfo,
    BackupInfo,
    DownloadCancelledError,
    DownloadError,
    DownloadProgress,
    ReleaseInfo,
    RollbackError,
    UpdateCheckError,
    UpdateState,
    UpdateStatus,
    UpdateType,
    Version,
)

logger = logging.getLogger(__name__)


class VersionParser:
    """セマンティックバージョニング解析と比較.

    Validates: Requirements 8
    """

    _VERSION_PATTERN = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)$")

    @staticmethod
    def parse(version_str: str) -> Version | None:
        """バージョン文字列をパースする.

        "v" / "V" プレフィックスを除去し、MAJOR.MINOR.PATCH を抽出する。
        プレリリースサフィックス（ハイフン以降）を含む場合は None を返す。

        Returns:
            Version: パース成功時
            None: 不正なフォーマットまたはプレリリース版
        """
        if not version_str:
            logger.warning("不正なバージョン形式検出: 空文字列")
            return None

        # プレリリースサフィックス（ハイフン以降）を含む場合は None を返す
        if "-" in version_str:
            logger.warning("不正なバージョン形式検出: %s (プレリリースサフィックスを含む)", version_str)
            return None

        match = VersionParser._VERSION_PATTERN.match(version_str)
        if not match:
            logger.warning("不正なバージョン形式検出: %s", version_str)
            return None

        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3))

        return Version(major=major, minor=minor, patch=patch)

    @staticmethod
    def compare(current: Version, latest: Version) -> int:
        """バージョンを比較する.

        Returns:
            -1: current < latest（更新あり）
             0: current == latest（最新）
             1: current > latest（ダウングレード、無視）
        """
        if current < latest:
            return -1
        elif current == latest:
            return 0
        else:
            return 1


class GitHubClient:
    """GitHub Releases API との通信を担当するクライアント.

    Validates: Requirements 1, 9
    """

    API_TIMEOUT: int = 30  # 秒
    DOWNLOAD_TIMEOUT: int = 600  # 秒
    _CHUNK_SIZE: int = 8192  # 8KB

    # アセット名のパターン
    _ZIP_PATTERN = re.compile(
        r"^screen-audio-recorder-v\d+\.\d+\.\d+-full\.zip$", re.IGNORECASE
    )
    _EXE_PATTERN = re.compile(
        r"^screen-audio-recorder-v\d+\.\d+\.\d+\.exe$", re.IGNORECASE
    )

    def __init__(self, repo_owner: str, repo_name: str) -> None:
        """GitHubClient を初期化する."""
        self._repo_owner = repo_owner
        self._repo_name = repo_name
        self._api_url = (
            f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest"
        )
        self._ssl_context = ssl.create_default_context()

    def fetch_latest_release(self) -> ReleaseInfo:
        """最新リリース情報を取得する.

        Returns:
            ReleaseInfo: タグ名、アセット一覧、リリースノートを含む情報

        Raises:
            UpdateCheckError: 通信エラー、タイムアウト、パース失敗時
        """
        logger.debug("GET %s", self._api_url)

        request = urllib.request.Request(
            self._api_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"{self._repo_owner}/{self._repo_name}",
            },
        )

        try:
            response = urllib.request.urlopen(
                request, timeout=self.API_TIMEOUT, context=self._ssl_context
            )
        except urllib.error.HTTPError as e:
            logger.error(
                "API 接続失敗 url=%s status_code=%d error_message=%s",
                self._api_url,
                e.code,
                str(e.reason),
            )
            raise UpdateCheckError(
                f"GitHub API エラー: HTTP {e.code} {e.reason}"
            ) from e
        except urllib.error.URLError as e:
            # SSL 証明書エラーの判定
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                logger.error(
                    "SSL/TLS 証明書検証失敗 hostname=%s error_detail=%s",
                    f"api.github.com",
                    str(e.reason),
                )
                raise UpdateCheckError(
                    f"SSL 証明書検証失敗: {e.reason}"
                ) from e
            logger.error(
                "API 接続失敗 url=%s status_code=N/A error_message=%s",
                self._api_url,
                str(e.reason),
            )
            raise UpdateCheckError(
                f"GitHub API 接続エラー: {e.reason}"
            ) from e
        except TimeoutError as e:
            logger.error(
                "API 接続失敗 url=%s status_code=N/A error_message=タイムアウト(%d秒)",
                self._api_url,
                self.API_TIMEOUT,
            )
            raise UpdateCheckError(
                f"GitHub API タイムアウト ({self.API_TIMEOUT}秒)"
            ) from e

        status_code = response.getcode()
        logger.debug("GET %s -> %d", self._api_url, status_code)

        # JSON パース
        try:
            raw_data = response.read().decode("utf-8")
            data = json.loads(raw_data)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(
                "API 接続失敗 url=%s status_code=%d error_message=JSONパース失敗: %s",
                self._api_url,
                status_code,
                str(e),
            )
            raise UpdateCheckError(
                f"GitHub API レスポンスのパース失敗: {e}"
            ) from e

        # バージョンパース
        tag_name = data.get("tag_name", "")
        version = VersionParser.parse(tag_name)
        if version is None:
            # プレリリース版の場合
            if "-" in tag_name:
                logger.warning("プレリリース版スキップ: %s", tag_name)
            raise UpdateCheckError(
                f"無効なバージョンタグ: {tag_name}"
            )

        # アセット解析
        raw_assets = data.get("assets", [])
        assets: list[AssetInfo] = []
        zip_asset: AssetInfo | None = None
        exe_asset: AssetInfo | None = None

        for raw_asset in raw_assets:
            asset = AssetInfo(
                name=raw_asset.get("name", ""),
                size=raw_asset.get("size", 0),
                download_url=raw_asset.get("browser_download_url", ""),
            )
            assets.append(asset)

            if self._ZIP_PATTERN.match(asset.name):
                zip_asset = asset
            elif self._EXE_PATTERN.match(asset.name):
                exe_asset = asset

        # アセット判定: zip があれば FULL、exe のみなら EXE_ONLY
        if zip_asset is not None:
            update_type = UpdateType.FULL
            target_asset = zip_asset
        elif exe_asset is not None:
            update_type = UpdateType.EXE_ONLY
            target_asset = exe_asset
        else:
            raise UpdateCheckError(
                f"対応するアセットが見つかりません (tag: {tag_name})"
            )

        release_notes = data.get("body", "") or ""

        release_info = ReleaseInfo(
            tag_name=tag_name,
            version=version,
            release_notes=release_notes,
            assets=assets,
            update_type=update_type,
            target_asset=target_asset,
        )

        logger.info(
            "新しいバージョン検出 latest=%s update_type=%s",
            version,
            update_type.name,
        )

        return release_info

    def download_asset(
        self,
        url: str,
        dest_path: Path,
        expected_size: int,
        on_progress: Callable[[int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        """アセットファイルをダウンロードする.

        Args:
            url: ダウンロード URL
            dest_path: 保存先パス
            expected_size: 期待されるファイルサイズ（バイト）
            on_progress: 進捗コールバック (downloaded_bytes, total_bytes)
            cancel_event: キャンセル用イベント

        Returns:
            ダウンロード完了ファイルのパス

        Raises:
            DownloadError: ネットワークエラー、サイズ不一致時
            DownloadCancelledError: キャンセル時
        """
        logger.info(
            "ダウンロード開始 url=%s expected_size=%d",
            url,
            expected_size,
        )

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"{self._repo_owner}/{self._repo_name}",
            },
        )

        try:
            response = urllib.request.urlopen(
                request, timeout=self.DOWNLOAD_TIMEOUT, context=self._ssl_context
            )
        except urllib.error.HTTPError as e:
            logger.error(
                "ダウンロード中断 bytes_downloaded=0 total_bytes=%d reason=HTTP %d %s",
                expected_size,
                e.code,
                str(e.reason),
            )
            raise DownloadError(
                f"ダウンロードエラー: HTTP {e.code} {e.reason}"
            ) from e
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                logger.error(
                    "SSL/TLS 証明書検証失敗 hostname=%s error_detail=%s",
                    url,
                    str(e.reason),
                )
                raise DownloadError(
                    f"SSL 証明書検証失敗: {e.reason}"
                ) from e
            logger.error(
                "ダウンロード中断 bytes_downloaded=0 total_bytes=%d reason=%s",
                expected_size,
                str(e.reason),
            )
            raise DownloadError(
                f"ダウンロード接続エラー: {e.reason}"
            ) from e
        except TimeoutError as e:
            logger.error(
                "ダウンロード中断 bytes_downloaded=0 total_bytes=%d reason=タイムアウト(%d秒)",
                expected_size,
                self.DOWNLOAD_TIMEOUT,
            )
            raise DownloadError(
                f"ダウンロードタイムアウト ({self.DOWNLOAD_TIMEOUT}秒)"
            ) from e

        downloaded_bytes = 0
        start_time = time.time()
        last_speed_log_time = start_time

        # 親ディレクトリを作成
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(dest_path, "wb") as f:
                while True:
                    # キャンセルチェック
                    if cancel_event is not None and cancel_event.is_set():
                        logger.error(
                            "ダウンロード中断 bytes_downloaded=%d total_bytes=%d reason=ユーザーキャンセル",
                            downloaded_bytes,
                            expected_size,
                        )
                        # 一時ファイル削除
                        try:
                            dest_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                        raise DownloadCancelledError("ダウンロードがキャンセルされました")

                    # チャンク読み込み
                    try:
                        chunk = response.read(self._CHUNK_SIZE)
                    except (TimeoutError, urllib.error.URLError, OSError) as e:
                        logger.error(
                            "ダウンロード中断 bytes_downloaded=%d total_bytes=%d reason=%s",
                            downloaded_bytes,
                            expected_size,
                            str(e),
                        )
                        # 一時ファイル削除
                        try:
                            dest_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                        raise DownloadError(
                            f"ダウンロード中にエラーが発生: {e}"
                        ) from e

                    if not chunk:
                        break

                    f.write(chunk)
                    downloaded_bytes += len(chunk)

                    # 進捗通知
                    if on_progress is not None:
                        on_progress(downloaded_bytes, expected_size)

                    # 10秒ごとの速度ログ
                    current_time = time.time()
                    if current_time - last_speed_log_time >= 10.0:
                        elapsed = current_time - start_time
                        speed = downloaded_bytes / elapsed if elapsed > 0 else 0
                        logger.debug(
                            "ダウンロード進捗 %dMB/%dMB speed=%.1fMB/s",
                            downloaded_bytes // (1024 * 1024),
                            expected_size // (1024 * 1024),
                            speed / (1024 * 1024),
                        )
                        last_speed_log_time = current_time

        except (DownloadError, DownloadCancelledError):
            raise
        except OSError as e:
            logger.error(
                "ダウンロード中断 bytes_downloaded=%d total_bytes=%d reason=ファイル書き込みエラー: %s",
                downloaded_bytes,
                expected_size,
                str(e),
            )
            try:
                dest_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise DownloadError(
                f"ファイル書き込みエラー: {e}"
            ) from e

        # サイズ検証
        if downloaded_bytes != expected_size:
            logger.error(
                "ダウンロード中断 bytes_downloaded=%d total_bytes=%d reason=サイズ不一致 (expected=%d, actual=%d)",
                downloaded_bytes,
                expected_size,
                expected_size,
                downloaded_bytes,
            )
            try:
                dest_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise DownloadError(
                f"ファイルサイズ不一致: 期待={expected_size}, 実際={downloaded_bytes}"
            )

        elapsed_time = time.time() - start_time
        logger.info(
            "ダウンロード完了 elapsed=%.1fs size=%d",
            elapsed_time,
            downloaded_bytes,
        )

        return dest_path


class UpdateApplier:
    """バックアップ作成・更新スクリプト生成・実行.

    Validates: Requirements 4, 5
    """

    PROCESS_WAIT_TIMEOUT: int = 60  # 秒

    # バッチスクリプトテンプレート: 通常更新（exe 単体）
    _EXE_UPDATE_SCRIPT_TEMPLATE = r"""@echo off
setlocal

set "PID=%1"
set "NEW_EXE=%2"
set "TARGET_EXE=%3"
set "BACKUP_EXE=%4"

echo Waiting for process %PID% to exit...
:wait_loop
tasklist /FI "PID eq %PID%" 2>NUL | find /I "%PID%" >NUL
if %ERRORLEVEL%==0 (
    timeout /t 1 /nobreak >NUL
    set /a WAIT_COUNT+=1
    if %WAIT_COUNT% GEQ {timeout} (
        echo Timeout: process did not exit within {timeout} seconds.
        echo Restoring backup...
        move /Y "%BACKUP_EXE%" "%TARGET_EXE%"
        start "" "%TARGET_EXE%"
        goto :cleanup
    )
    goto :wait_loop
)

echo Moving new exe to target path...
move /Y "%NEW_EXE%" "%TARGET_EXE%"
if %ERRORLEVEL% NEQ 0 (
    echo Failed to move new exe. Restoring backup...
    move /Y "%BACKUP_EXE%" "%TARGET_EXE%"
    start "" "%TARGET_EXE%"
    goto :cleanup
)

echo Starting updated application...
start "" "%TARGET_EXE%"

:cleanup
del "%~f0"
"""

    # バッチスクリプトテンプレート: フル更新（zip）
    _FULL_UPDATE_SCRIPT_TEMPLATE = r"""@echo off
setlocal

set "PID=%1"
set "NEW_DIR=%2"
set "TARGET_DIR=%3"
set "BACKUP_DIR=%4"
set "EXE_NAME=%5"

echo Waiting for process %PID% to exit...
:wait_loop
tasklist /FI "PID eq %PID%" 2>NUL | find /I "%PID%" >NUL
if %ERRORLEVEL%==0 (
    timeout /t 1 /nobreak >NUL
    set /a WAIT_COUNT+=1
    if %WAIT_COUNT% GEQ {timeout} (
        echo Timeout: process did not exit within {timeout} seconds.
        echo Restoring backup...
        rmdir /S /Q "%TARGET_DIR%" 2>NUL
        move /Y "%BACKUP_DIR%" "%TARGET_DIR%"
        start "" "%TARGET_DIR%\%EXE_NAME%"
        goto :cleanup
    )
    goto :wait_loop
)

echo Moving new files to target path...
rmdir /S /Q "%TARGET_DIR%" 2>NUL
move /Y "%NEW_DIR%" "%TARGET_DIR%"
if %ERRORLEVEL% NEQ 0 (
    echo Failed to move new files. Restoring backup...
    move /Y "%BACKUP_DIR%" "%TARGET_DIR%"
    start "" "%TARGET_DIR%\%EXE_NAME%"
    goto :cleanup
)

echo Starting updated application...
start "" "%TARGET_DIR%\%EXE_NAME%"

:cleanup
del "%~f0"
"""

    # バッチスクリプトテンプレート: ロールバック（exe 単体）
    _EXE_ROLLBACK_SCRIPT_TEMPLATE = r"""@echo off
setlocal

set "PID=%1"
set "BACKUP_EXE=%2"
set "TARGET_EXE=%3"

echo Waiting for process %PID% to exit...
:wait_loop
tasklist /FI "PID eq %PID%" 2>NUL | find /I "%PID%" >NUL
if %ERRORLEVEL%==0 (
    timeout /t 1 /nobreak >NUL
    set /a WAIT_COUNT+=1
    if %WAIT_COUNT% GEQ {timeout} (
        echo Timeout: process did not exit within {timeout} seconds.
        echo Rollback failed: process did not exit. > "%~dp0rollback_error.log"
        goto :cleanup
    )
    goto :wait_loop
)

echo Restoring backup...
del /F /Q "%TARGET_EXE%" 2>NUL
move /Y "%BACKUP_EXE%" "%TARGET_EXE%"
if %ERRORLEVEL% NEQ 0 (
    echo Failed to restore backup. > "%~dp0rollback_error.log"
    goto :cleanup
)

echo Starting restored application...
start "" "%TARGET_EXE%"

:cleanup
del "%~f0"
"""

    # バッチスクリプトテンプレート: ロールバック（フル更新）
    _FULL_ROLLBACK_SCRIPT_TEMPLATE = r"""@echo off
setlocal

set "PID=%1"
set "BACKUP_DIR=%2"
set "TARGET_DIR=%3"
set "EXE_NAME=%4"

echo Waiting for process %PID% to exit...
:wait_loop
tasklist /FI "PID eq %PID%" 2>NUL | find /I "%PID%" >NUL
if %ERRORLEVEL%==0 (
    timeout /t 1 /nobreak >NUL
    set /a WAIT_COUNT+=1
    if %WAIT_COUNT% GEQ {timeout} (
        echo Timeout: process did not exit within {timeout} seconds.
        echo Rollback failed: process did not exit. > "%~dp0rollback_error.log"
        goto :cleanup
    )
    goto :wait_loop
)

echo Restoring backup...
rmdir /S /Q "%TARGET_DIR%" 2>NUL
move /Y "%BACKUP_DIR%" "%TARGET_DIR%"
if %ERRORLEVEL% NEQ 0 (
    echo Failed to restore backup. > "%~dp0rollback_error.log"
    goto :cleanup
)

echo Starting restored application...
start "" "%TARGET_DIR%\%EXE_NAME%"

:cleanup
del "%~f0"
"""

    def __init__(self, exe_path: Path, app_dir: Path) -> None:
        """UpdateApplier を初期化する.

        Args:
            exe_path: 現在実行中の exe パス
            app_dir: アプリケーションフォルダのパス（_internal の親）
        """
        self._exe_path = exe_path
        self._app_dir = app_dir

    def create_backup(self, current_version: str, update_type: UpdateType) -> BackupInfo:
        """現在のファイルをバックアップする.

        通常更新: exe を `{exe_name_without_ext}-v{version}.exe.bak` にリネーム
        フル更新: app_dir を `app-backup-v{version}` にリネーム

        Args:
            current_version: 現在のバージョン文字列
            update_type: EXE_ONLY または FULL

        Returns:
            BackupInfo: バックアップパスとバージョン情報

        Raises:
            ApplyError: リネーム失敗時
        """
        if update_type == UpdateType.EXE_ONLY:
            # 通常更新: exe を screen-audio-recorder-v0.1.0.exe.bak にリネーム
            exe_stem = self._exe_path.stem  # e.g. "screen-audio-recorder"
            backup_name = f"{exe_stem}-v{current_version}.exe.bak"
            backup_path = self._exe_path.parent / backup_name
        else:
            # フル更新: app_dir を app-backup-v0.1.0 にリネーム
            backup_name = f"app-backup-v{current_version}"
            backup_path = self._app_dir.parent / backup_name

        logger.debug("バックアップ先パス: %s", backup_path)

        try:
            if update_type == UpdateType.EXE_ONLY:
                logger.debug("リネーム元パス: %s -> %s", self._exe_path, backup_path)
                self._exe_path.rename(backup_path)
            else:
                logger.debug("リネーム元パス: %s -> %s", self._app_dir, backup_path)
                self._app_dir.rename(backup_path)
        except OSError as e:
            logger.error(
                "バックアップ作成失敗 source_path=%s dest_path=%s OSError=%s",
                self._exe_path if update_type == UpdateType.EXE_ONLY else self._app_dir,
                backup_path,
                str(e),
            )
            raise ApplyError(
                f"バックアップ作成に失敗しました: {e}"
            ) from e

        backup_info = BackupInfo(
            backup_path=backup_path,
            version=current_version,
            update_type=update_type,
            created_at=datetime.now(),
        )

        logger.info(
            "バックアップ作成完了 path=%s version=%s",
            backup_path,
            current_version,
        )

        return backup_info

    def generate_update_script(
        self,
        update_type: UpdateType,
        new_file_path: Path,
        target_path: Path,
        backup_info: BackupInfo,
    ) -> Path:
        """更新用バッチスクリプトを一時ディレクトリに生成する.

        Args:
            update_type: EXE_ONLY または FULL
            new_file_path: ダウンロードした新しいファイル/フォルダのパス
            target_path: 更新先のパス（exe パスまたは app_dir パス）
            backup_info: バックアップ情報

        Returns:
            生成したバッチファイルのパス

        Raises:
            ApplyError: スクリプト生成失敗時
        """
        pid = os.getpid()

        if update_type == UpdateType.EXE_ONLY:
            script_content = self._EXE_UPDATE_SCRIPT_TEMPLATE.format(
                timeout=self.PROCESS_WAIT_TIMEOUT
            )
            # バッチスクリプトの引数: PID, NEW_EXE, TARGET_EXE, BACKUP_EXE
            args = f'"{pid}" "{new_file_path}" "{target_path}" "{backup_info.backup_path}"'
        else:
            exe_name = self._exe_path.name
            script_content = self._FULL_UPDATE_SCRIPT_TEMPLATE.format(
                timeout=self.PROCESS_WAIT_TIMEOUT
            )
            # バッチスクリプトの引数: PID, NEW_DIR, TARGET_DIR, BACKUP_DIR, EXE_NAME
            args = f'"{pid}" "{new_file_path}" "{target_path}" "{backup_info.backup_path}" "{exe_name}"'

        try:
            # 一時ディレクトリにバッチファイルを生成
            temp_dir = tempfile.mkdtemp(prefix="update_")
            script_path = Path(temp_dir) / "update.bat"
            # 引数を先頭行のコメントとして記録し、実際のバッチは引数付きで呼び出す
            # バッチ自体にはコマンドライン引数として渡す形式
            script_path.write_text(script_content, encoding="shift_jis")
        except OSError as e:
            logger.error(
                "スクリプト生成失敗 target_path=%s error_detail=%s",
                script_path if "script_path" in locals() else "N/A",
                str(e),
            )
            raise ApplyError(
                f"更新スクリプトの生成に失敗しました: {e}"
            ) from e

        logger.debug("バッチスクリプト内容:\n%s", script_content)
        logger.debug("バッチスクリプト引数: %s", args)

        # 引数情報をメタファイルとして保存（launch_script_and_exit で使用）
        args_path = script_path.with_suffix(".args")
        try:
            args_path.write_text(args, encoding="utf-8")
        except OSError:
            pass

        return script_path

    def generate_rollback_script(self, backup_info: BackupInfo) -> Path:
        """ロールバック用バッチスクリプトを生成する.

        Args:
            backup_info: バックアップ情報

        Returns:
            生成したバッチファイルのパス

        Raises:
            ApplyError: スクリプト生成失敗時
        """
        pid = os.getpid()

        if backup_info.update_type == UpdateType.EXE_ONLY:
            script_content = self._EXE_ROLLBACK_SCRIPT_TEMPLATE.format(
                timeout=self.PROCESS_WAIT_TIMEOUT
            )
            # 引数: PID, BACKUP_EXE, TARGET_EXE
            args = f'"{pid}" "{backup_info.backup_path}" "{self._exe_path}"'
        else:
            exe_name = self._exe_path.name
            script_content = self._FULL_ROLLBACK_SCRIPT_TEMPLATE.format(
                timeout=self.PROCESS_WAIT_TIMEOUT
            )
            # 引数: PID, BACKUP_DIR, TARGET_DIR, EXE_NAME
            args = f'"{pid}" "{backup_info.backup_path}" "{self._app_dir}" "{exe_name}"'

        try:
            temp_dir = tempfile.mkdtemp(prefix="rollback_")
            script_path = Path(temp_dir) / "rollback.bat"
            script_path.write_text(script_content, encoding="shift_jis")
        except OSError as e:
            logger.error(
                "スクリプト生成失敗 target_path=%s error_detail=%s",
                script_path if "script_path" in locals() else "N/A",
                str(e),
            )
            raise ApplyError(
                f"ロールバックスクリプトの生成に失敗しました: {e}"
            ) from e

        logger.debug("ロールバックスクリプト内容:\n%s", script_content)
        logger.debug("ロールバックスクリプト引数: %s", args)

        # 引数情報をメタファイルとして保存
        args_path = script_path.with_suffix(".args")
        try:
            args_path.write_text(args, encoding="utf-8")
        except OSError:
            pass

        return script_path

    def launch_script_and_exit(self, script_path: Path) -> None:
        """バッチスクリプトを起動し、アプリケーションを終了する.

        Args:
            script_path: 実行するバッチファイルのパス
        """
        # 引数ファイルから引数を読み込み
        args_path = script_path.with_suffix(".args")
        args_str = ""
        try:
            if args_path.exists():
                args_str = args_path.read_text(encoding="utf-8").strip()
        except OSError:
            pass

        cmd = f'"{script_path}" {args_str}'

        logger.info(
            "更新スクリプト起動 script=%s PID=%d",
            script_path,
            os.getpid(),
        )

        # CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS でプロセス独立
        subprocess.Popen(
            cmd,
            shell=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        sys.exit(0)

    def find_backup(self) -> BackupInfo | None:
        """同一ディレクトリにバックアップが存在するか確認する.

        Returns:
            BackupInfo: バックアップが存在する場合
            None: バックアップが存在しない場合
        """
        exe_dir = self._exe_path.parent

        # 通常更新のバックアップを検索: *.exe.bak
        for bak_file in exe_dir.glob("*.exe.bak"):
            # バージョン文字列を抽出: screen-audio-recorder-v0.1.0.exe.bak
            name = bak_file.name
            # パターン: {app_name}-v{version}.exe.bak
            match = re.match(r".*-v(\d+\.\d+\.\d+)\.exe\.bak$", name)
            if match:
                version = match.group(1)
                try:
                    stat = bak_file.stat()
                    created_at = datetime.fromtimestamp(stat.st_mtime)
                except OSError:
                    created_at = datetime.now()

                return BackupInfo(
                    backup_path=bak_file,
                    version=version,
                    update_type=UpdateType.EXE_ONLY,
                    created_at=created_at,
                )

        # フル更新のバックアップを検索: app-backup-v*
        for backup_dir in exe_dir.glob("app-backup-v*"):
            if backup_dir.is_dir():
                # バージョン文字列を抽出: app-backup-v0.1.0
                name = backup_dir.name
                match = re.match(r"app-backup-v(\d+\.\d+\.\d+)$", name)
                if match:
                    version = match.group(1)
                    try:
                        stat = backup_dir.stat()
                        created_at = datetime.fromtimestamp(stat.st_mtime)
                    except OSError:
                        created_at = datetime.now()

                    return BackupInfo(
                        backup_path=backup_dir,
                        version=version,
                        update_type=UpdateType.FULL,
                        created_at=created_at,
                    )

        return None

    def cleanup_old_backups(self) -> None:
        """古いバックアップ（*.exe.bak, app-backup-v*）を削除する."""
        exe_dir = self._exe_path.parent

        # 通常更新のバックアップを削除: *.exe.bak
        for bak_file in exe_dir.glob("*.exe.bak"):
            try:
                bak_file.unlink()
                logger.info("古いバックアップ削除 path=%s", bak_file)
            except OSError as e:
                logger.error(
                    "バックアップ削除失敗 path=%s error=%s",
                    bak_file,
                    str(e),
                )

        # フル更新のバックアップを削除: app-backup-v*
        for backup_dir in exe_dir.glob("app-backup-v*"):
            if backup_dir.is_dir():
                try:
                    shutil.rmtree(backup_dir)
                    logger.info("古いバックアップ削除 path=%s", backup_dir)
                except OSError as e:
                    logger.error(
                        "バックアップ削除失敗 path=%s error=%s",
                        backup_dir,
                        str(e),
                    )


class Updater:
    """自動更新フロー制御モジュール.

    Validates: Requirements 1, 2, 3, 4, 5
    """

    def __init__(
        self,
        repo_owner: str,
        repo_name: str,
        current_version: str,
        exe_path: Path,
        on_status_changed: Callable[[UpdateStatus], None] | None = None,
        on_progress: Callable[[DownloadProgress], None] | None = None,
    ) -> None:
        """Updater を初期化する.

        Args:
            repo_owner: GitHub リポジトリオーナー
            repo_name: GitHub リポジトリ名
            current_version: 現在のアプリバージョン（例: "0.1.0"）
            exe_path: 現在実行中の exe のパス
            on_status_changed: ステータス変更コールバック（GUI スレッドに転送用）
            on_progress: ダウンロード進捗コールバック
        """
        self._repo_owner = repo_owner
        self._repo_name = repo_name
        self._current_version = current_version
        self._exe_path = exe_path
        self._on_status_changed = on_status_changed
        self._on_progress = on_progress

        # コンポーネント初期化
        self._github_client = GitHubClient(repo_owner, repo_name)
        self._app_dir = exe_path.parent
        self._applier = UpdateApplier(exe_path, self._app_dir)

        # スレッド制御
        self._cancel_event = threading.Event()
        self._latest_release: ReleaseInfo | None = None
        self._is_downloading: bool = False

    def check_for_update(self) -> None:
        """バックグラウンドスレッドで最新バージョンを確認する.

        結果は on_status_changed コールバックで通知する。
        """
        thread = threading.Thread(target=self._check_for_update_worker, daemon=True)
        thread.start()

    def _check_for_update_worker(self) -> None:
        """更新確認ワーカー（バックグラウンドスレッド）."""
        logger.info(
            "更新確認開始 current=%s repo=%s/%s",
            self._current_version,
            self._repo_owner,
            self._repo_name,
        )

        # CHECKING 状態を通知
        self._notify_status(UpdateStatus(
            state=UpdateState.CHECKING,
            message="更新を確認中...",
        ))

        try:
            release_info = self._github_client.fetch_latest_release()
        except UpdateCheckError as e:
            logger.error("更新確認失敗: %s", str(e))
            self._notify_status(UpdateStatus(
                state=UpdateState.ERROR,
                message="更新の確認に失敗しました",
                error=str(e),
            ))
            return

        # 現在のバージョンをパース
        current_version = VersionParser.parse(self._current_version)
        if current_version is None:
            logger.error("現在のバージョンのパースに失敗: %s", self._current_version)
            self._notify_status(UpdateStatus(
                state=UpdateState.ERROR,
                message="現在のバージョン情報が不正です",
                error=f"バージョンのパース失敗: {self._current_version}",
            ))
            return

        # バージョン比較
        comparison = VersionParser.compare(current_version, release_info.version)

        if comparison < 0:
            # 更新あり
            self._latest_release = release_info
            release_notes_preview = release_info.release_notes[:200]
            logger.info(
                "新しいバージョン検出 latest=%s update_type=%s",
                release_info.version,
                release_info.update_type.name,
            )
            self._notify_status(UpdateStatus(
                state=UpdateState.UPDATE_AVAILABLE,
                message=f"v{release_info.version} が利用可能です",
                version=str(release_info.version),
            ))
        else:
            # 最新
            logger.info("最新バージョンです current=%s", self._current_version)
            self._notify_status(UpdateStatus(
                state=UpdateState.UP_TO_DATE,
                message="最新バージョンです",
                version=self._current_version,
            ))

    def download_and_apply(self, release_info: ReleaseInfo) -> None:
        """バックグラウンドスレッドで更新をダウンロードし適用する.

        Args:
            release_info: ダウンロード対象のリリース情報
        """
        self._cancel_event.clear()
        thread = threading.Thread(
            target=self._download_and_apply_worker,
            args=(release_info,),
            daemon=True,
        )
        thread.start()

    def _download_and_apply_worker(self, release_info: ReleaseInfo) -> None:
        """ダウンロード＆適用ワーカー（バックグラウンドスレッド）."""
        self._is_downloading = True
        try:
            self._download_and_apply_impl(release_info)
        finally:
            self._is_downloading = False

    def _download_and_apply_impl(self, release_info: ReleaseInfo) -> None:
        """ダウンロード＆適用の実装（_is_downloading フラグ管理用に分離）."""
        # DOWNLOADING 状態を通知
        self._notify_status(UpdateStatus(
            state=UpdateState.DOWNLOADING,
            message="更新をダウンロード中...",
            version=str(release_info.version),
        ))

        target_asset = release_info.target_asset

        # ディスク容量チェック（アセットサイズの2倍が必要）
        try:
            disk_usage = shutil.disk_usage(self._exe_path.parent)
            required_space = target_asset.size * 2
            if disk_usage.free < required_space:
                free_mb = disk_usage.free / (1024 * 1024)
                required_mb = required_space / (1024 * 1024)
                logger.warning(
                    "ディスク空き容量が少ない available=%.1fMB required=%.1fMB",
                    free_mb,
                    required_mb,
                )
                self._notify_status(UpdateStatus(
                    state=UpdateState.ERROR,
                    message="ディスク容量が不足しています",
                    error=f"空き容量: {free_mb:.0f}MB, 必要容量: {required_mb:.0f}MB",
                ))
                return
        except OSError as e:
            logger.error("ディスク容量チェック失敗: %s", str(e))
            self._notify_status(UpdateStatus(
                state=UpdateState.ERROR,
                message="ディスク容量の確認に失敗しました",
                error=str(e),
            ))
            return

        # ダウンロード先の一時パスを決定
        temp_dir = tempfile.mkdtemp(prefix="updater_download_")
        dest_path = Path(temp_dir) / target_asset.name

        # ダウンロード開始時刻（速度計算用）
        download_start_time = time.time()

        def on_raw_progress(downloaded: int, total: int) -> None:
            """GitHubClient からの進捗コールバックを DownloadProgress に変換."""
            if self._on_progress is not None:
                elapsed = time.time() - download_start_time
                speed = downloaded / elapsed if elapsed > 0 else 0.0
                progress = DownloadProgress(
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    speed_bytes_per_sec=speed,
                    elapsed_seconds=elapsed,
                )
                self._on_progress(progress)

        # ダウンロード実行
        try:
            downloaded_path = self._github_client.download_asset(
                url=target_asset.download_url,
                dest_path=dest_path,
                expected_size=target_asset.size,
                on_progress=on_raw_progress,
                cancel_event=self._cancel_event,
            )
        except DownloadCancelledError:
            logger.info("ダウンロードがキャンセルされました")
            self._notify_status(UpdateStatus(
                state=UpdateState.IDLE,
                message="ダウンロードがキャンセルされました",
            ))
            # 一時ディレクトリをクリーンアップ
            self._cleanup_temp_dir(temp_dir)
            return
        except DownloadError as e:
            logger.error("ダウンロード失敗: %s", str(e))
            self._notify_status(UpdateStatus(
                state=UpdateState.ERROR,
                message="ダウンロードに失敗しました",
                error=str(e),
            ))
            self._cleanup_temp_dir(temp_dir)
            return

        # ファイルサイズ検証
        actual_size = downloaded_path.stat().st_size
        logger.debug(
            "ファイルサイズ検証 expected=%d actual=%d %s",
            target_asset.size,
            actual_size,
            "OK" if actual_size == target_asset.size else "NG",
        )
        if actual_size != target_asset.size:
            logger.error(
                "ファイルサイズ不一致 expected=%d actual=%d",
                target_asset.size,
                actual_size,
            )
            self._notify_status(UpdateStatus(
                state=UpdateState.ERROR,
                message="ダウンロードファイルのサイズが一致しません",
                error=f"期待: {target_asset.size}, 実際: {actual_size}",
            ))
            self._cleanup_temp_dir(temp_dir)
            return

        # フル更新時: zip 展開
        new_file_path = downloaded_path
        if release_info.update_type == UpdateType.FULL:
            extract_dir = Path(temp_dir) / "extracted"
            try:
                with zipfile.ZipFile(downloaded_path, "r") as zf:
                    # zip 構造検証: ルートレベルに exe が存在するか確認
                    names = zf.namelist()
                    logger.debug("zip 展開後ファイル一覧: %s", names)

                    exe_found = False
                    for name in names:
                        # ルートレベルの exe を検索（サブディレクトリ内は除外）
                        parts = Path(name).parts
                        if len(parts) == 1 and name.lower().endswith(".exe"):
                            exe_found = True
                            break
                        # 1階層のディレクトリ直下の exe も許容
                        if len(parts) == 2 and parts[1].lower().endswith(".exe"):
                            exe_found = True
                            break

                    if not exe_found:
                        logger.warning("zip 内に想定外のファイル構造を検出")
                        self._notify_status(UpdateStatus(
                            state=UpdateState.ERROR,
                            message="更新ファイルの構造が不正です",
                            error="zip 内にルートレベルの exe が見つかりません",
                        ))
                        self._cleanup_temp_dir(temp_dir)
                        return

                    zf.extractall(extract_dir)
            except zipfile.BadZipFile as e:
                logger.error("zip 展開失敗: %s", str(e))
                self._notify_status(UpdateStatus(
                    state=UpdateState.ERROR,
                    message="更新ファイルが破損しています",
                    error=str(e),
                ))
                self._cleanup_temp_dir(temp_dir)
                return
            except OSError as e:
                logger.error("zip 展開失敗: %s", str(e))
                self._notify_status(UpdateStatus(
                    state=UpdateState.ERROR,
                    message="更新ファイルの展開に失敗しました",
                    error=str(e),
                ))
                self._cleanup_temp_dir(temp_dir)
                return

            # 展開されたディレクトリを new_file_path として使用
            # 展開ディレクトリ内に単一のサブディレクトリがある場合はそれを使用
            extracted_items = list(extract_dir.iterdir())
            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                new_file_path = extracted_items[0]
            else:
                new_file_path = extract_dir

        # バックアップ作成
        try:
            backup_info = self._applier.create_backup(
                self._current_version, release_info.update_type
            )
        except ApplyError as e:
            logger.error("バックアップ作成失敗: %s", str(e))
            self._notify_status(UpdateStatus(
                state=UpdateState.ERROR,
                message="バックアップの作成に失敗しました",
                error=str(e),
            ))
            self._cleanup_temp_dir(temp_dir)
            return

        # 更新スクリプト生成
        target_path = (
            self._exe_path if release_info.update_type == UpdateType.EXE_ONLY
            else self._app_dir
        )
        try:
            script_path = self._applier.generate_update_script(
                update_type=release_info.update_type,
                new_file_path=new_file_path,
                target_path=target_path,
                backup_info=backup_info,
            )
        except ApplyError as e:
            logger.error("更新スクリプト生成失敗: %s", str(e))
            self._notify_status(UpdateStatus(
                state=UpdateState.ERROR,
                message="更新スクリプトの生成に失敗しました",
                error=str(e),
            ))
            self._cleanup_temp_dir(temp_dir)
            return

        # APPLYING 状態を通知
        self._notify_status(UpdateStatus(
            state=UpdateState.APPLYING,
            message="更新を適用中...",
            version=str(release_info.version),
        ))

        # COMPLETED 状態を通知
        self._notify_status(UpdateStatus(
            state=UpdateState.COMPLETED,
            message="更新が完了しました。アプリを再起動します。",
            version=str(release_info.version),
        ))

        # スクリプト起動 & 終了
        logger.info(
            "更新スクリプト起動 script=%s PID=%d",
            script_path,
            os.getpid(),
        )
        self._applier.launch_script_and_exit(script_path)

    def cancel_download(self) -> None:
        """進行中のダウンロードをキャンセルする."""
        self._cancel_event.set()

    def rollback(self) -> None:
        """バックアップから旧バージョンに復帰する."""
        backup_info = self._applier.find_backup()
        if backup_info is None:
            logger.error("ロールバック失敗: バックアップが見つかりません")
            self._notify_status(UpdateStatus(
                state=UpdateState.ERROR,
                message="ロールバックに失敗しました",
                error="バックアップが見つかりません",
            ))
            return

        logger.info("ロールバック実行 target_version=%s", backup_info.version)

        try:
            script_path = self._applier.generate_rollback_script(backup_info)
        except ApplyError as e:
            logger.error("ロールバックスクリプト生成失敗: %s", str(e))
            self._notify_status(UpdateStatus(
                state=UpdateState.ERROR,
                message="ロールバックに失敗しました",
                error=str(e),
            ))
            return

        self._applier.launch_script_and_exit(script_path)

    def find_backup(self) -> BackupInfo | None:
        """同一ディレクトリにバックアップが存在するか確認する."""
        return self._applier.find_backup()

    def cleanup_old_backups(self) -> None:
        """古いバックアップを削除する."""
        self._applier.cleanup_old_backups()

    def _notify_status(self, status: UpdateStatus) -> None:
        """ステータス変更をコールバックで通知する."""
        if self._on_status_changed is not None:
            self._on_status_changed(status)

    @staticmethod
    def _cleanup_temp_dir(temp_dir: str) -> None:
        """一時ディレクトリを安全に削除する."""
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except OSError:
            pass
