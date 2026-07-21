"""AboutTab のユニットテスト.

ボタン初期状態、録画中無効化、ステータスラベル遷移、ロールバックボタン表示/非表示をテストする。

**Validates: Requirements 6, 7**
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from unittest.mock import MagicMock

import pytest

from screen_audio_recorder.gui.about_tab import AboutTab
from screen_audio_recorder.updater_models import (
    BackupInfo,
    UpdateState,
    UpdateStatus,
    UpdateType,
)


# ---------------------------------------------------------------------------
# テスト用フィクスチャ
# ---------------------------------------------------------------------------


@pytest.fixture
def root():
    """テスト用の tk.Tk ルートウィンドウを作成する."""
    try:
        _root = tk.Tk()
        _root.withdraw()
        yield _root
    except tk.TclError:
        pytest.skip("tkinter display not available")
    finally:
        try:
            _root.destroy()
        except Exception:
            pass


@pytest.fixture
def mock_updater():
    """モック Updater を作成する."""
    updater = MagicMock()
    updater.find_backup.return_value = None
    updater._latest_release = None
    return updater


# ---------------------------------------------------------------------------
# 1. ボタン初期状態テスト
# ---------------------------------------------------------------------------


class TestButtonInitialState:
    """ボタン初期状態のテスト."""

    def test_check_update_button_exists_when_updater_provided(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """updater が提供されている場合、「更新を確認」ボタンが存在し有効である."""
        notebook = ttk.Notebook(root)
        about_tab = AboutTab(notebook, updater=mock_updater, is_recording=lambda: False)

        assert hasattr(about_tab, "_check_update_button")
        assert str(about_tab._check_update_button.cget("state")) in ("normal", "!disabled")

    def test_check_update_button_is_enabled(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """updater が提供されている場合、ボタンが有効（NORMAL）状態である."""
        notebook = ttk.Notebook(root)
        about_tab = AboutTab(notebook, updater=mock_updater, is_recording=lambda: False)

        # ttk.Button のstateを確認
        state = about_tab._check_update_button.state()
        assert "disabled" not in state

    def test_no_update_ui_when_updater_is_none(self, root: tk.Tk) -> None:
        """updater が None の場合、更新 UI が表示されない."""
        notebook = ttk.Notebook(root)
        about_tab = AboutTab(notebook, updater=None, is_recording=None)

        assert not hasattr(about_tab, "_check_update_button")
        assert not hasattr(about_tab, "_status_label")
        assert not hasattr(about_tab, "_rollback_button")


# ---------------------------------------------------------------------------
# 2. 録画中無効化テスト
# ---------------------------------------------------------------------------


class TestRecordingDisable:
    """録画中のボタン無効化テスト."""

    def test_button_disabled_when_recording(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """録画中は「更新を確認」ボタンが無効になる."""
        notebook = ttk.Notebook(root)
        about_tab = AboutTab(
            notebook, updater=mock_updater, is_recording=lambda: True
        )

        # update_recording_state を呼び出す
        about_tab.update_recording_state()

        state = about_tab._check_update_button.state()
        assert "disabled" in state

    def test_button_enabled_when_not_recording(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """録画していない場合はボタンが有効."""
        notebook = ttk.Notebook(root)
        about_tab = AboutTab(
            notebook, updater=mock_updater, is_recording=lambda: False
        )

        about_tab.update_recording_state()

        state = about_tab._check_update_button.state()
        assert "disabled" not in state

    def test_on_check_update_does_not_call_updater_during_recording(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """録画中に _on_check_update が呼ばれても updater.check_for_update() を呼ばない."""
        notebook = ttk.Notebook(root)
        about_tab = AboutTab(
            notebook, updater=mock_updater, is_recording=lambda: True
        )

        # messagebox をモックして実行（ダイアログが出ないように）
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("screen_audio_recorder.gui.about_tab.messagebox.showinfo", lambda *a, **kw: None)
            about_tab._on_check_update()

        mock_updater.check_for_update.assert_not_called()


# ---------------------------------------------------------------------------
# 3. ステータスラベル遷移テスト
# ---------------------------------------------------------------------------


class TestStatusLabelTransition:
    """ステータスラベル遷移テスト."""

    def test_checking_state_shows_checking_text(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """CHECKING ステートで「確認中」テキストとグレー色が表示される."""
        notebook = ttk.Notebook(root)
        about_tab = AboutTab(notebook, updater=mock_updater, is_recording=lambda: False)

        status = UpdateStatus(state=UpdateState.CHECKING, message="確認中...")
        about_tab._on_status_changed(status)

        label_text = about_tab._status_label.cget("text")
        label_fg = about_tab._status_label.cget("fg")

        assert "確認中" in label_text
        assert label_fg == "gray"

    def test_update_available_state_shows_version(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """UPDATE_AVAILABLE ステートでバージョン番号と緑色が表示される."""
        notebook = ttk.Notebook(root)
        about_tab = AboutTab(notebook, updater=mock_updater, is_recording=lambda: False)

        status = UpdateStatus(
            state=UpdateState.UPDATE_AVAILABLE,
            message="新しいバージョンが利用可能",
            version="2.0.0",
        )
        # _show_update_available_dialog をモックしてダイアログ表示を防ぐ
        about_tab._show_update_available_dialog = MagicMock()
        about_tab._on_status_changed(status)

        label_text = about_tab._status_label.cget("text")
        label_fg = about_tab._status_label.cget("fg")

        assert "2.0.0" in label_text
        assert label_fg == "green"

    def test_up_to_date_state_shows_latest(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """UP_TO_DATE ステートで「最新」テキストと緑色が表示される."""
        notebook = ttk.Notebook(root)
        about_tab = AboutTab(notebook, updater=mock_updater, is_recording=lambda: False)

        status = UpdateStatus(
            state=UpdateState.UP_TO_DATE,
            message="最新バージョンです",
            version="1.0.0",
        )
        about_tab._on_status_changed(status)

        label_text = about_tab._status_label.cget("text")
        label_fg = about_tab._status_label.cget("fg")

        assert "最新" in label_text
        assert label_fg == "green"

    def test_error_state_shows_error_text(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """ERROR ステートで「エラー」テキストと赤色が表示される."""
        notebook = ttk.Notebook(root)
        about_tab = AboutTab(notebook, updater=mock_updater, is_recording=lambda: False)

        status = UpdateStatus(
            state=UpdateState.ERROR,
            message="接続失敗",
            error="接続失敗",
        )
        about_tab._on_status_changed(status)

        label_text = about_tab._status_label.cget("text")
        label_fg = about_tab._status_label.cget("fg")

        assert "エラー" in label_text
        assert label_fg == "red"


# ---------------------------------------------------------------------------
# 4. ロールバックボタンの表示/非表示テスト
# ---------------------------------------------------------------------------


class TestRollbackButtonVisibility:
    """ロールバックボタンの表示/非表示テスト."""

    def test_rollback_button_hidden_when_no_backup(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """バックアップがない場合、ロールバックボタンは pack されていない."""
        mock_updater.find_backup.return_value = None

        notebook = ttk.Notebook(root)
        about_tab = AboutTab(notebook, updater=mock_updater, is_recording=lambda: False)

        # pack_forget されたウィジェットは pack_info() で TclError を発生させる
        with pytest.raises(tk.TclError):
            about_tab._rollback_button.pack_info()

    def test_rollback_button_visible_when_backup_exists(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """バックアップが存在する場合、ロールバックボタンが表示される."""
        backup_info = BackupInfo(
            backup_path=Path("C:/app/screen-audio-recorder.exe.bak"),
            version="1.0.0",
            update_type=UpdateType.EXE_ONLY,
            created_at=datetime(2025, 6, 1, 12, 0, 0),
        )
        mock_updater.find_backup.return_value = backup_info

        notebook = ttk.Notebook(root)
        about_tab = AboutTab(notebook, updater=mock_updater, is_recording=lambda: False)

        # pack_info() が成功 = ボタンが表示されている
        info = about_tab._rollback_button.pack_info()
        assert info is not None

        # ボタンテキストにバージョンが含まれている
        button_text = about_tab._rollback_button.cget("text")
        assert "1.0.0" in button_text

    def test_rollback_button_updates_visibility_on_status_change(
        self, root: tk.Tk, mock_updater: MagicMock
    ) -> None:
        """ステータス変更後にロールバックボタンの表示が更新される."""
        # 最初はバックアップなし
        mock_updater.find_backup.return_value = None

        notebook = ttk.Notebook(root)
        about_tab = AboutTab(notebook, updater=mock_updater, is_recording=lambda: False)

        # 初期状態: 非表示
        with pytest.raises(tk.TclError):
            about_tab._rollback_button.pack_info()

        # バックアップが存在する状態に変更
        backup_info = BackupInfo(
            backup_path=Path("C:/app/screen-audio-recorder.exe.bak"),
            version="0.9.0",
            update_type=UpdateType.EXE_ONLY,
            created_at=datetime(2025, 6, 1, 12, 0, 0),
        )
        mock_updater.find_backup.return_value = backup_info

        # ステータス変更をトリガー（UP_TO_DATE で更新完了を通知）
        status = UpdateStatus(
            state=UpdateState.UP_TO_DATE,
            message="最新バージョンです",
            version="1.0.0",
        )
        about_tab._on_status_changed(status)

        # ボタンが表示されるようになった
        info = about_tab._rollback_button.pack_info()
        assert info is not None
        button_text = about_tab._rollback_button.cget("text")
        assert "0.9.0" in button_text
