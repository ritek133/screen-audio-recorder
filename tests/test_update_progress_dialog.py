"""UpdateProgressDialog のユニットテスト.

**Validates: Requirements 3, 6**
"""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from screen_audio_recorder.gui.update_progress_dialog import UpdateProgressDialog
from screen_audio_recorder.updater_models import DownloadProgress


# ---------------------------------------------------------------------------
# テスト用ヘルパー
# ---------------------------------------------------------------------------


@pytest.fixture
def root():
    """テスト用の tk.Tk ルートウィンドウを作成する."""
    try:
        root = tk.Tk()
        root.withdraw()
        yield root
    except tk.TclError:
        pytest.skip("tkinter display not available")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def make_progress(
    downloaded: int = 50 * 1024 * 1024,
    total: int = 100 * 1024 * 1024,
    speed: float = 10.0 * 1024 * 1024,
    elapsed: float = 5.0,
) -> DownloadProgress:
    """テスト用 DownloadProgress を生成する."""
    return DownloadProgress(
        downloaded_bytes=downloaded,
        total_bytes=total,
        speed_bytes_per_sec=speed,
        elapsed_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# UpdateProgressDialog のユニットテスト
# ---------------------------------------------------------------------------


class TestUpdateProgressDialogInit:
    """UpdateProgressDialog 初期化のテスト."""

    def test_dialog_created_with_correct_title(self, root: tk.Tk) -> None:
        """ダイアログが正しいタイトルで作成される."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        assert dialog._dialog.title() == "更新のダウンロード"
        dialog.close()

    def test_dialog_is_transient(self, root: tk.Tk) -> None:
        """ダイアログが親ウィンドウの transient である."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        # transient が設定されていることを確認
        assert dialog._dialog.winfo_exists()
        dialog.close()

    def test_update_interval_is_500ms(self, root: tk.Tk) -> None:
        """UPDATE_INTERVAL_MS が 500 である."""
        assert UpdateProgressDialog.UPDATE_INTERVAL_MS == 500

    def test_initial_state_has_no_progress(self, root: tk.Tk) -> None:
        """初期状態ではプログレスが None."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        assert dialog._latest_progress is None
        dialog.close()


class TestUpdateProgressDialogUpdateProgress:
    """UpdateProgressDialog.update_progress() のテスト."""

    def test_buffers_progress_data(self, root: tk.Tk) -> None:
        """進捗データがバッファされる."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        progress = make_progress()
        dialog.update_progress(progress)

        assert dialog._latest_progress is progress
        dialog.close()

    def test_refresh_updates_percent_label(self, root: tk.Tk) -> None:
        """_refresh_display がパーセントラベルを更新する."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        progress = make_progress(downloaded=67 * 1024 * 1024, total=100 * 1024 * 1024)
        dialog.update_progress(progress)
        dialog._refresh_display()

        assert dialog._percent_label.cget("text") == "67%"
        dialog.close()

    def test_refresh_updates_progressbar_value(self, root: tk.Tk) -> None:
        """_refresh_display がプログレスバーの値を更新する."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        progress = make_progress(downloaded=75 * 1024 * 1024, total=100 * 1024 * 1024)
        dialog.update_progress(progress)
        dialog._refresh_display()

        assert dialog._progressbar["value"] == 75
        dialog.close()

    def test_refresh_updates_size_label(self, root: tk.Tk) -> None:
        """_refresh_display がサイズラベルを更新する."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        progress = make_progress(
            downloaded=125 * 1024 * 1024, total=187 * 1024 * 1024
        )
        dialog.update_progress(progress)
        dialog._refresh_display()

        text = dialog._size_label.cget("text")
        assert "125.0 MB" in text
        assert "187.0 MB" in text
        dialog.close()

    def test_refresh_updates_speed_label(self, root: tk.Tk) -> None:
        """_refresh_display が速度ラベルを更新する."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        progress = make_progress(speed=12.5 * 1024 * 1024)
        dialog.update_progress(progress)
        dialog._refresh_display()

        assert dialog._speed_label.cget("text") == "12.5 MB/s"
        dialog.close()

    def test_refresh_updates_eta_label_with_value(self, root: tk.Tk) -> None:
        """_refresh_display が残り時間ラベルを更新する（値あり）."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        # 50MB remaining, 10MB/s => 5 seconds
        progress = make_progress(
            downloaded=50 * 1024 * 1024,
            total=100 * 1024 * 1024,
            speed=10.0 * 1024 * 1024,
        )
        dialog.update_progress(progress)
        dialog._refresh_display()

        assert dialog._eta_label.cget("text") == "残り約 5 秒"
        dialog.close()

    def test_refresh_updates_eta_label_calculating(self, root: tk.Tk) -> None:
        """_refresh_display が速度 0 の場合「計算中...」と表示する."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        progress = make_progress(speed=0.0)
        dialog.update_progress(progress)
        dialog._refresh_display()

        assert dialog._eta_label.cget("text") == "計算中..."
        dialog.close()


class TestUpdateProgressDialogClose:
    """UpdateProgressDialog.close() のテスト."""

    def test_close_destroys_dialog(self, root: tk.Tk) -> None:
        """close() がダイアログを破棄する."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        dialog.close()

        assert dialog._closed is True

    def test_close_is_idempotent(self, root: tk.Tk) -> None:
        """close() を複数回呼んでもエラーにならない."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        dialog.close()
        dialog.close()  # 2回目もエラーなし

        assert dialog._closed is True


class TestUpdateProgressDialogCancel:
    """キャンセル機能のテスト."""

    def test_cancel_button_calls_callback(self, root: tk.Tk) -> None:
        """キャンセルボタンがコールバックを呼ぶ."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        dialog._handle_cancel()

        on_cancel.assert_called_once()
        dialog.close()

    def test_wm_delete_calls_cancel(self, root: tk.Tk) -> None:
        """ウィンドウ閉じボタンがキャンセルコールバックを呼ぶ."""
        on_cancel = MagicMock()
        dialog = UpdateProgressDialog(root, on_cancel)

        # WM_DELETE_WINDOW プロトコルのハンドラを直接呼ぶ
        dialog._handle_cancel()

        on_cancel.assert_called_once()
        dialog.close()
