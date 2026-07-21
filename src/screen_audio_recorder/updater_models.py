"""自動更新機能のデータモデルと例外クラス."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


# ============================================================
# Data Models
# ============================================================


@dataclass(frozen=True)
class Version:
    """セマンティックバージョン."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __lt__(self, other: "Version") -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) < (
            other.major,
            other.minor,
            other.patch,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) == (
            other.major,
            other.minor,
            other.patch,
        )

    def __le__(self, other: "Version") -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self == other or self < other

    def __gt__(self, other: "Version") -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) > (
            other.major,
            other.minor,
            other.patch,
        )

    def __ge__(self, other: "Version") -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self == other or self > other

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch))


class UpdateType(Enum):
    """更新種別."""

    EXE_ONLY = "exe_only"  # 通常更新（exe 単体）
    FULL = "full"  # フル更新（zip: exe + _internal）


class UpdateState(Enum):
    """更新ステート."""

    IDLE = "idle"
    CHECKING = "checking"
    UPDATE_AVAILABLE = "update_available"
    UP_TO_DATE = "up_to_date"
    DOWNLOADING = "downloading"
    APPLYING = "applying"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class AssetInfo:
    """リリースアセット情報."""

    name: str
    size: int
    download_url: str


@dataclass
class ReleaseInfo:
    """GitHub リリース情報."""

    tag_name: str
    version: Version
    release_notes: str
    assets: list[AssetInfo]
    update_type: UpdateType
    target_asset: AssetInfo


@dataclass
class UpdateStatus:
    """更新ステータス（GUI 表示用）."""

    state: UpdateState
    message: str
    version: str | None = None
    error: str | None = None


@dataclass
class DownloadProgress:
    """ダウンロード進捗情報."""

    downloaded_bytes: int
    total_bytes: int
    speed_bytes_per_sec: float
    elapsed_seconds: float

    @property
    def percent(self) -> int:
        """進捗率（0〜100）."""
        if self.total_bytes == 0:
            return 0
        return min(100, int(self.downloaded_bytes * 100 / self.total_bytes))

    @property
    def eta_seconds(self) -> float | None:
        """推定残り時間（秒）. 速度が 0 の場合は None."""
        if self.speed_bytes_per_sec <= 0:
            return None
        remaining = self.total_bytes - self.downloaded_bytes
        return remaining / self.speed_bytes_per_sec

    @property
    def downloaded_mb(self) -> str:
        """人間可読なダウンロード済みサイズ."""
        return f"{self.downloaded_bytes / (1024 * 1024):.1f} MB"

    @property
    def total_mb(self) -> str:
        """人間可読な総サイズ."""
        return f"{self.total_bytes / (1024 * 1024):.1f} MB"

    @property
    def speed_mb_s(self) -> str:
        """人間可読な速度."""
        return f"{self.speed_bytes_per_sec / (1024 * 1024):.1f} MB/s"


@dataclass
class BackupInfo:
    """バックアップ情報."""

    backup_path: Path
    version: str
    update_type: UpdateType
    created_at: datetime


# ============================================================
# Exception Hierarchy
# ============================================================


class UpdateError(Exception):
    """更新処理の基底例外."""


class UpdateCheckError(UpdateError):
    """バージョン確認失敗."""


class DownloadError(UpdateError):
    """ダウンロード失敗."""


class DownloadCancelledError(DownloadError):
    """ダウンロードがキャンセルされた."""


class ApplyError(UpdateError):
    """更新適用失敗."""


class RollbackError(UpdateError):
    """ロールバック失敗."""
