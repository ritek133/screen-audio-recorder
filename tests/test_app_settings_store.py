"""app_settings_store の永続化テスト.

メモ領域の折りたたみ状態を含む AppSettings の保存・読み込みを検証する。
"""

from __future__ import annotations

import json
from pathlib import Path

from screen_audio_recorder.app_settings_store import (
    load_app_settings,
    save_app_settings,
)
from screen_audio_recorder.models import AppSettings


class TestLoadDefaults:
    """設定ファイルが無い／不正なときのデフォルト挙動."""

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        """ファイルが存在しない場合は全展開のデフォルトを返す."""
        settings = load_app_settings(tmp_path / "not_exist.json")

        assert settings.verbose_logging is False
        assert settings.memo_tree_expanded is True
        assert settings.memo_summary_expanded is True
        assert settings.memo_detail_expanded is True

    def test_broken_json_returns_defaults(self, tmp_path: Path) -> None:
        """JSON が壊れている場合はデフォルトを返す."""
        path = tmp_path / "app_settings.json"
        path.write_text("{ broken json", encoding="utf-8")

        settings = load_app_settings(path)

        assert settings.memo_tree_expanded is True
        assert settings.memo_summary_expanded is True
        assert settings.memo_detail_expanded is True

    def test_old_json_without_collapse_keys_defaults_to_expanded(
        self, tmp_path: Path
    ) -> None:
        """折りたたみキーが無い旧設定ファイルでも全展開にフォールバックする（後方互換）."""
        path = tmp_path / "app_settings.json"
        path.write_text(
            json.dumps({"verbose_logging": True}), encoding="utf-8"
        )

        settings = load_app_settings(path)

        assert settings.verbose_logging is True
        assert settings.memo_tree_expanded is True
        assert settings.memo_summary_expanded is True
        assert settings.memo_detail_expanded is True


class TestSaveLoadRoundTrip:
    """折りたたみ状態の保存→読み込み往復."""

    def test_collapse_state_round_trip(self, tmp_path: Path) -> None:
        """保存した折りたたみ状態が次回読み込みで復元される."""
        path = tmp_path / "app_settings.json"
        original = AppSettings(
            verbose_logging=True,
            memo_tree_expanded=False,
            memo_summary_expanded=True,
            memo_detail_expanded=False,
        )

        save_app_settings(original, path)
        loaded = load_app_settings(path)

        assert loaded.verbose_logging is True
        assert loaded.memo_tree_expanded is False
        assert loaded.memo_summary_expanded is True
        assert loaded.memo_detail_expanded is False

    def test_saved_json_contains_collapse_keys(self, tmp_path: Path) -> None:
        """保存された JSON に折りたたみキーが含まれる."""
        path = tmp_path / "app_settings.json"
        save_app_settings(
            AppSettings(memo_summary_expanded=False), path
        )

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["memo_tree_expanded"] is True
        assert data["memo_summary_expanded"] is False
        assert data["memo_detail_expanded"] is True

    def test_save_preserves_other_fields(self, tmp_path: Path) -> None:
        """一部フィールドだけ更新して保存しても他フィールドは保持される（読み込み→更新→保存パターン）."""
        path = tmp_path / "app_settings.json"
        # 初期状態: verbose=True, 全展開
        save_app_settings(AppSettings(verbose_logging=True), path)

        # 折りたたみ状態だけ更新するパターン（実装が採用する手順）
        settings = load_app_settings(path)
        settings.memo_detail_expanded = False
        save_app_settings(settings, path)

        loaded = load_app_settings(path)
        # verbose_logging は上書きされず保持される
        assert loaded.verbose_logging is True
        assert loaded.memo_detail_expanded is False
        assert loaded.memo_tree_expanded is True
