"""ErrorNotifier: エラー・警告ダイアログの表示とログ記録を担当するクラス.

**Validates: Requirements 4.5, 4.6, 6.4, 8.4**
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

# tkinter は Windows 以外の環境や headless 環境では利用不可の場合があるため
# try/except でインポートし、利用不可の場合はログのみ行う
try:
    import tkinter as tk
    from tkinter import messagebox

    _TKINTER_AVAILABLE = True
except ImportError:
    tk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    _TKINTER_AVAILABLE = False


def _setup_logger() -> logging.Logger:
    """アプリケーションロガーを取得する.

    ハンドラの設定は main.py の _setup_logging() に委譲する。
    ここではロガーの取得のみ行う。

    Returns:
        Logger インスタンス
    """
    return logging.getLogger("screen_audio_recorder")


logger = _setup_logger()


class ErrorNotifier:
    """エラー・警告ダイアログの表示とログ記録を担当するクラス.

    すべての通知は GUI スレッドから ``root.after_idle()`` 経由で呼び出す。
    ``root`` が ``None`` の場合は直接呼び出す。

    tkinter が利用不可の場合はログのみ行う。

    Attributes:
        _root: tkinter ルートウィンドウ。None の場合は直接呼び出し。
    """

    def __init__(self, root: "tk.Tk | None" = None) -> None:
        """ErrorNotifier を初期化する.

        Args:
            root: tkinter ルートウィンドウ。None の場合は直接呼び出し。
        """
        self._root = root

    def show_warning(self, title: str, message: str) -> None:
        """警告ダイアログを表示する（処理は継続）.

        ログに WARNING レベルで記録し、tkinter の警告ダイアログを表示する。
        処理は継続するため、呼び出し元はこのメソッドの後も処理を続ける。

        Args:
            title: ダイアログのタイトル
            message: 警告メッセージ
        """
        logger.warning("[%s] %s", title, message)
        self._schedule_dialog("warning", title, message)

    def show_error(self, title: str, message: str) -> None:
        """エラーダイアログを表示する（処理は中止）.

        ログに ERROR レベルで記録し、tkinter のエラーダイアログを表示する。
        処理は中止するため、呼び出し元はこのメソッドの後に処理を中止すること。

        Args:
            title: ダイアログのタイトル
            message: エラーメッセージ
        """
        logger.error("[%s] %s", title, message)
        self._schedule_dialog("error", title, message)

    def _schedule_dialog(self, dialog_type: str, title: str, message: str) -> None:
        """ダイアログ表示をスケジュールする.

        root が設定されている場合は ``root.after_idle()`` 経由で GUI スレッドから呼び出す。
        root が None の場合は直接呼び出す。

        Args:
            dialog_type: "warning" または "error"
            title: ダイアログのタイトル
            message: メッセージ
        """
        if not _TKINTER_AVAILABLE:
            # tkinter が利用不可の場合はログのみ（既にログ済み）
            return

        def _show() -> None:
            if dialog_type == "warning":
                messagebox.showwarning(title, message)
            else:
                messagebox.showerror(title, message)

        if self._root is not None:
            # GUI スレッドから after_idle() 経由で呼び出す
            self._root.after_idle(_show)
        else:
            # root が None の場合は直接呼び出す
            _show()
