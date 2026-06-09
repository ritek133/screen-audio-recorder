"""FileStore のユニットテスト.

**Validates: Requirements 1.3, 8.2**
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from screen_audio_recorder.file_store import FileStore


class TestFileStoreInit:
    """FileStore の初期化テスト."""

    def test_base_dir_is_under_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """base_dir が Path.home() 配下にある."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        assert store.base_dir.is_relative_to(tmp_path)

    def test_base_dir_created_automatically(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """初期化時に recordings ディレクトリが自動作成される."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        assert store.base_dir.exists()
        assert store.base_dir.is_dir()

    def test_base_dir_path_structure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """base_dir が ~/.screen-audio-recorder/recordings/ の構造を持つ."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        expected = tmp_path / ".screen-audio-recorder" / "recordings"
        assert store.base_dir == expected

    def test_init_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """既にディレクトリが存在する場合でも初期化が成功する."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        FileStore()  # 1回目
        FileStore()  # 2回目（既存ディレクトリ）


class TestGetOutputPath:
    """FileStore.get_output_path() のテスト."""

    def test_returns_path_under_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """生成されるパスが Path.home() 配下にある（要件 1.3、8.2）."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        path = store.get_output_path("mp4")
        assert path.is_relative_to(tmp_path)

    def test_returns_path_under_base_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """生成されるパスが base_dir 配下にある."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        path = store.get_output_path("mp4")
        assert path.is_relative_to(store.base_dir)

    def test_extension_mp4(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """mp4 拡張子が正しく付与される."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        path = store.get_output_path("mp4")
        assert path.suffix == ".mp4"

    def test_extension_mp3(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """mp3 拡張子が正しく付与される."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        path = store.get_output_path("mp3")
        assert path.suffix == ".mp3"

    def test_extension_wav(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """wav 拡張子が正しく付与される."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        path = store.get_output_path("wav")
        assert path.suffix == ".wav"

    def test_extension_with_leading_dot(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """先頭にドットがある拡張子も正しく処理される."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        path = store.get_output_path(".mp4")
        assert path.suffix == ".mp4"

    def test_filename_timestamp_format(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ファイル名が YYYY-MM-DD_HH-MM-SS.ext の形式になっている."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        path = store.get_output_path("mp4")
        pattern = r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.mp4$"
        assert re.match(pattern, path.name), (
            f"ファイル名 {path.name!r} が期待するフォーマット YYYY-MM-DD_HH-MM-SS.mp4 に一致しない"
        )

    def test_returns_absolute_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """返されるパスが絶対パスである."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        path = store.get_output_path("mp4")
        assert path.is_absolute()

    def test_different_calls_may_differ(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """複数回呼び出しても有効なパスが返される."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = FileStore()
        path1 = store.get_output_path("mp4")
        path2 = store.get_output_path("mp4")
        # どちらも有効なパスであること
        assert path1.is_relative_to(tmp_path)
        assert path2.is_relative_to(tmp_path)
