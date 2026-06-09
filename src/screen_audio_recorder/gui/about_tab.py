"""AboutTab: アプリケーションのバージョン情報タブ.

作者、会社、バージョンなどの情報を表示する。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import screen_audio_recorder


class AboutTab:
    """「このアプリについて」タブのUIコンポーネント."""

    def __init__(self, parent: ttk.Notebook) -> None:
        """AboutTab を初期化する.

        Args:
            parent: 親の Notebook ウィジェット
        """
        self._frame = ttk.Frame(parent, padding=16)
        self._build_ui()

    @property
    def frame(self) -> ttk.Frame:
        """タブのフレームを返す."""
        return self._frame

    def _build_ui(self) -> None:
        """UI コンポーネントを構築する."""
        # アプリ名
        app_name_label = ttk.Label(
            self._frame,
            text="Screen Audio Recorder",
            font=("", 16, "bold"),
        )
        app_name_label.pack(pady=(16, 4))

        # バージョン
        version_label = ttk.Label(
            self._frame,
            text=f"バージョン: {screen_audio_recorder.__version__}",
            font=("", 10),
        )
        version_label.pack(pady=(0, 16))

        # 区切り線
        separator = ttk.Separator(self._frame, orient=tk.HORIZONTAL)
        separator.pack(fill=tk.X, pady=8)

        # 情報テーブル
        info_frame = ttk.Frame(self._frame)
        info_frame.pack(pady=8)

        info_items = [
            ("作者:", screen_audio_recorder.__author__),
            ("会社:", screen_audio_recorder.__company__),
            ("ライセンス:", screen_audio_recorder.__license__),
        ]

        for row, (label_text, value_text) in enumerate(info_items):
            label = ttk.Label(info_frame, text=label_text, font=("", 10, "bold"))
            label.grid(row=row, column=0, sticky=tk.E, padx=(0, 8), pady=4)

            value = ttk.Label(info_frame, text=value_text, font=("", 10))
            value.grid(row=row, column=1, sticky=tk.W, pady=4)

        # 説明
        desc_label = ttk.Label(
            self._frame,
            text="Windows 画面・音声録画 & 文字起こしアプリケーション",
            font=("", 9),
            foreground="gray",
        )
        desc_label.pack(pady=(16, 0))

        # 著作権表示
        copyright_label = ttk.Label(
            self._frame,
            text=f"© 2025 {screen_audio_recorder.__company__}",
            font=("", 9),
            foreground="gray",
        )
        copyright_label.pack(pady=(8, 0))
