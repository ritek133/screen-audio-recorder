"""ErrorNotifier のユニットテスト.

**Validates: Requirements 4.5, 4.6, 6.4, 8.4**
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, call, patch

import pytest

from screen_audio_recorder.error_notifier import ErrorNotifier, _TKINTER_AVAILABLE


# ---------------------------------------------------------------------------
# ロギングのテスト
# ---------------------------------------------------------------------------


class TestErrorNotifierLogging:
    """ErrorNotifier がログを正しく記録することのテスト."""

    def test_show_warning_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """show_warning が WARNING レベルでログを記録する."""
        notifier = ErrorNotifier(root=None)

        with caplog.at_level(logging.WARNING, logger="screen_audio_recorder"):
            # tkinter ダイアログをモックして実際のダイアログを表示しない
            with patch("screen_audio_recorder.error_notifier.messagebox") as mock_mb:
                notifier.show_warning("テスト警告", "警告メッセージです")

        # WARNING レベルのログが記録されていることを確認
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1
        assert "テスト警告" in warning_records[0].message
        assert "警告メッセージです" in warning_records[0].message

    def test_show_error_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """show_error が ERROR レベルでログを記録する."""
        notifier = ErrorNotifier(root=None)

        with caplog.at_level(logging.ERROR, logger="screen_audio_recorder"):
            with patch("screen_audio_recorder.error_notifier.messagebox") as mock_mb:
                notifier.show_error("テストエラー", "エラーメッセージです")

        # ERROR レベルのログが記録されていることを確認
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1
        assert "テストエラー" in error_records[0].message
        assert "エラーメッセージです" in error_records[0].message

    def test_show_warning_does_not_log_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """show_warning は ERROR レベルのログを記録しない."""
        notifier = ErrorNotifier(root=None)

        with caplog.at_level(logging.DEBUG, logger="screen_audio_recorder"):
            with patch("screen_audio_recorder.error_notifier.messagebox"):
                notifier.show_warning("警告", "メッセージ")

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) == 0

    def test_show_error_does_not_log_warning_only(self, caplog: pytest.LogCaptureFixture) -> None:
        """show_error は WARNING ではなく ERROR レベルでログを記録する."""
        notifier = ErrorNotifier(root=None)

        with caplog.at_level(logging.DEBUG, logger="screen_audio_recorder"):
            with patch("screen_audio_recorder.error_notifier.messagebox"):
                notifier.show_error("エラー", "メッセージ")

        # ERROR レベルのログが存在することを確認
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1


# ---------------------------------------------------------------------------
# root=None の場合の動作テスト
# ---------------------------------------------------------------------------


class TestErrorNotifierWithoutRoot:
    """root=None の場合の ErrorNotifier の動作テスト."""

    def test_show_warning_without_root_calls_showwarning_directly(self) -> None:
        """root=None の場合、show_warning が messagebox.showwarning を直接呼び出す."""
        notifier = ErrorNotifier(root=None)

        with patch("screen_audio_recorder.error_notifier.messagebox") as mock_mb:
            with patch("screen_audio_recorder.error_notifier._TKINTER_AVAILABLE", True):
                notifier.show_warning("警告タイトル", "警告メッセージ")

        mock_mb.showwarning.assert_called_once_with("警告タイトル", "警告メッセージ")

    def test_show_error_without_root_calls_showerror_directly(self) -> None:
        """root=None の場合、show_error が messagebox.showerror を直接呼び出す."""
        notifier = ErrorNotifier(root=None)

        with patch("screen_audio_recorder.error_notifier.messagebox") as mock_mb:
            with patch("screen_audio_recorder.error_notifier._TKINTER_AVAILABLE", True):
                notifier.show_error("エラータイトル", "エラーメッセージ")

        mock_mb.showerror.assert_called_once_with("エラータイトル", "エラーメッセージ")

    def test_show_warning_without_root_does_not_raise(self) -> None:
        """root=None の場合、show_warning が例外を送出しない."""
        notifier = ErrorNotifier(root=None)

        with patch("screen_audio_recorder.error_notifier.messagebox"):
            # 例外が発生しないことを確認
            notifier.show_warning("タイトル", "メッセージ")

    def test_show_error_without_root_does_not_raise(self) -> None:
        """root=None の場合、show_error が例外を送出しない."""
        notifier = ErrorNotifier(root=None)

        with patch("screen_audio_recorder.error_notifier.messagebox"):
            # 例外が発生しないことを確認
            notifier.show_error("タイトル", "メッセージ")


# ---------------------------------------------------------------------------
# root が設定されている場合の動作テスト
# ---------------------------------------------------------------------------


class TestErrorNotifierWithRoot:
    """root が設定されている場合の ErrorNotifier の動作テスト."""

    def test_show_warning_with_root_uses_after_idle(self) -> None:
        """root が設定されている場合、show_warning が root.after_idle() を使用する."""
        mock_root = MagicMock()
        notifier = ErrorNotifier(root=mock_root)

        with patch("screen_audio_recorder.error_notifier._TKINTER_AVAILABLE", True):
            notifier.show_warning("警告", "メッセージ")

        # after_idle が呼ばれたことを確認
        mock_root.after_idle.assert_called_once()

    def test_show_error_with_root_uses_after_idle(self) -> None:
        """root が設定されている場合、show_error が root.after_idle() を使用する."""
        mock_root = MagicMock()
        notifier = ErrorNotifier(root=mock_root)

        with patch("screen_audio_recorder.error_notifier._TKINTER_AVAILABLE", True):
            notifier.show_error("エラー", "メッセージ")

        # after_idle が呼ばれたことを確認
        mock_root.after_idle.assert_called_once()

    def test_show_warning_with_root_does_not_call_messagebox_directly(self) -> None:
        """root が設定されている場合、show_warning が messagebox を直接呼び出さない."""
        mock_root = MagicMock()
        notifier = ErrorNotifier(root=mock_root)

        with patch("screen_audio_recorder.error_notifier.messagebox") as mock_mb:
            with patch("screen_audio_recorder.error_notifier._TKINTER_AVAILABLE", True):
                notifier.show_warning("警告", "メッセージ")

        # messagebox は直接呼ばれない（after_idle 経由で呼ばれる）
        mock_mb.showwarning.assert_not_called()


# ---------------------------------------------------------------------------
# tkinter 利用不可の場合のテスト
# ---------------------------------------------------------------------------


class TestErrorNotifierTkinterUnavailable:
    """tkinter が利用不可の場合の ErrorNotifier の動作テスト."""

    def test_show_warning_without_tkinter_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """tkinter が利用不可の場合、show_warning が例外を送出しない."""
        notifier = ErrorNotifier(root=None)

        with patch("screen_audio_recorder.error_notifier._TKINTER_AVAILABLE", False):
            with caplog.at_level(logging.WARNING, logger="screen_audio_recorder"):
                notifier.show_warning("警告", "メッセージ")

        # ログは記録される
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1

    def test_show_error_without_tkinter_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """tkinter が利用不可の場合、show_error が例外を送出しない."""
        notifier = ErrorNotifier(root=None)

        with patch("screen_audio_recorder.error_notifier._TKINTER_AVAILABLE", False):
            with caplog.at_level(logging.ERROR, logger="screen_audio_recorder"):
                notifier.show_error("エラー", "メッセージ")

        # ログは記録される
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1
