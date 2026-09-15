"""RawTranscriptStore のユニットテスト.

文字起こし生データを個別ファイルで管理する RawTranscriptStore の
保存・読込・ファイル名生成・衝突回避を検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from screen_audio_recorder.raw_transcript_store import RawTranscriptStore


@pytest.fixture()
def store(tmp_path: Path) -> RawTranscriptStore:
    """一時ディレクトリを使用した RawTranscriptStore インスタンスを返す."""
    return RawTranscriptStore(base_dir=tmp_path / "transcripts")


class TestRawTranscriptStoreInit:
    """初期化テスト."""

    def test_base_dir_created_automatically(self, tmp_path: Path) -> None:
        """初期化時に保存先ディレクトリが自動作成される."""
        base = tmp_path / "transcripts"
        RawTranscriptStore(base_dir=base)
        assert base.exists()

    def test_default_base_dir_under_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """デフォルトの保存先が Path.home() 配下にある."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = RawTranscriptStore()
        assert store.base_dir.is_relative_to(tmp_path)


class TestRawTranscriptStoreSave:
    """save() のテスト."""

    def test_save_creates_file(self, store: RawTranscriptStore, tmp_path: Path) -> None:
        """save() でファイルが作成される."""
        path = store.save("生テキスト", tmp_path / "2024-01-15_10-30-00.mp4")
        assert path.exists()

    def test_save_writes_text(self, store: RawTranscriptStore, tmp_path: Path) -> None:
        """save() が生テキストを正しく書き込む."""
        text = "これは文字起こしの生データです。句読点なし"
        path = store.save(text, tmp_path / "rec.wav")
        assert path.read_text(encoding="utf-8") == text

    def test_save_filename_matches_output_stem(
        self, store: RawTranscriptStore, tmp_path: Path
    ) -> None:
        """ファイル名が録画ファイルの stem に対応する."""
        path = store.save("text", tmp_path / "2024-01-15_10-30-00.mp4")
        assert path.name == "2024-01-15_10-30-00.txt"

    def test_save_empty_text_creates_file(
        self, store: RawTranscriptStore, tmp_path: Path
    ) -> None:
        """生テキストが空でもファイルを作成する（メモとの1対1対応を保つ）."""
        path = store.save("", tmp_path / "rec.mp4")
        assert path.exists()
        assert path.read_text(encoding="utf-8") == ""

    def test_save_collision_appends_suffix(
        self, store: RawTranscriptStore, tmp_path: Path
    ) -> None:
        """同名ファイルが存在する場合は連番を付与する."""
        output = tmp_path / "rec.mp4"
        path1 = store.save("最初", output)
        path2 = store.save("2回目", output)
        assert path1 != path2
        assert path1.read_text(encoding="utf-8") == "最初"
        assert path2.read_text(encoding="utf-8") == "2回目"

    def test_save_under_base_dir(self, store: RawTranscriptStore, tmp_path: Path) -> None:
        """保存先が base_dir 配下である."""
        path = store.save("text", tmp_path / "rec.mp4")
        assert path.parent == store.base_dir

    def test_save_invalid_stem_falls_back(
        self, store: RawTranscriptStore, tmp_path: Path
    ) -> None:
        """ファイル名に使えない stem の場合でも保存できる."""
        # stem に不正文字（コロン）を含むパスを stem 経由で渡す想定
        # Path.stem は拡張子を除いた部分。ここでは不正文字を含むファイル名を検証。
        path = store.save("text", Path("a:b*c.mp4"))
        assert path.exists()
        assert path.suffix == ".txt"


class TestRawTranscriptStoreLoad:
    """load() のテスト."""

    def test_load_returns_saved_text(
        self, store: RawTranscriptStore, tmp_path: Path
    ) -> None:
        """save() したテキストを load() で読み戻せる."""
        text = "生データ本文"
        path = store.save(text, tmp_path / "rec.mp4")
        assert store.load(path) == text

    def test_load_nonexistent_returns_none(
        self, store: RawTranscriptStore, tmp_path: Path
    ) -> None:
        """存在しないファイルの load() は None を返す."""
        assert store.load(tmp_path / "does_not_exist.txt") is None

    def test_save_load_round_trip_empty(
        self, store: RawTranscriptStore, tmp_path: Path
    ) -> None:
        """空テキストのラウンドトリップ."""
        path = store.save("", tmp_path / "rec.mp4")
        assert store.load(path) == ""
