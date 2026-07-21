"""UpdateProgressDialog: ダウンロード進捗を表示するモーダルダイアログ.

Validates: Requirements 3, 6
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from screen_audio_recorder.updater_models import DownloadProgress


class UpdateProgressDialog:
    """ダウンロード進捗を表示するモーダルダイアログ.

    Validates: Requirements 3, 6
    """

    UPDATE_INTERVAL_MS: int = 500  # GUI 更新間隔

    def __init__(self, parent: tk.Tk, on_cancel: Callable[[], None]) -> None:
        """進捗ダイアログを初期化する.

        Args:
            parent: 親ウィンドウ
            on_cancel: キャンセルボタン押下時のコールバック
        """
        self._parent = parent
        self._on_cancel = on_cancel
        self._latest_progress: DownloadProgress | None = None
        self._closed = False
        self._after_id: str | None = None

        # Toplevel ウィンドウの作成
        self._dialog = tk.Toplevel(parent)
        self._dialog.title("更新のダウンロード")
        self._dialog.resizable(False, False)
        self._dialog.transient(parent)
        self._dialog.protocol("WM_DELETE_WINDOW", self._handle_cancel)

        # ウィンドウサイズと位置（親ウィンドウ中央）
        width = 400
        height = 200
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        x = parent_x + (parent_w - width) // 2
        y = parent_y + (parent_h - height) // 2
        self._dialog.geometry(f"{width}x{height}+{x}+{y}")

        # UI 構築
        self._build_ui()

        # モーダル設定
        self._dialog.grab_set()

        # 定期更新を開始
        self._schedule_update()

    def _build_ui(self) -> None:
        """UI コンポーネントを構築する."""
        main_frame = ttk.Frame(self._dialog, padding=16)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # タイトルラベル
        title_label = ttk.Label(
            main_frame,
            text="⬇️ 更新をダウンロード中...",
            font=("", 11, "bold"),
        )
        title_label.pack(anchor=tk.W, pady=(0, 12))

        # プログレスバーとパーセント表示のフレーム
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 8))

        self._progressbar = ttk.Progressbar(
            progress_frame,
            orient=tk.HORIZONTAL,
            length=320,
            mode="determinate",
            maximum=100,
        )
        self._progressbar.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._percent_label = ttk.Label(
            progress_frame,
            text="0%",
            font=("", 9),
            width=5,
        )
        self._percent_label.pack(side=tk.LEFT, padx=(8, 0))

        # サイズと速度のフレーム
        info_frame = ttk.Frame(main_frame)
        info_frame.pack(fill=tk.X, pady=(0, 4))

        self._size_label = ttk.Label(
            info_frame,
            text="0.0 MB / 0.0 MB",
            font=("", 9),
        )
        self._size_label.pack(side=tk.LEFT)

        self._speed_label = ttk.Label(
            info_frame,
            text="0.0 MB/s",
            font=("", 9),
        )
        self._speed_label.pack(side=tk.RIGHT)

        # 残り時間ラベル
        self._eta_label = ttk.Label(
            main_frame,
            text="計算中...",
            font=("", 9),
        )
        self._eta_label.pack(anchor=tk.W, pady=(0, 12))

        # キャンセルボタン
        self._cancel_button = ttk.Button(
            main_frame,
            text="キャンセル",
            command=self._handle_cancel,
        )
        self._cancel_button.pack()

    def update_progress(self, progress: DownloadProgress) -> None:
        """ダウンロード進捗を更新する.

        進捗情報をバッファし、次回の定期更新で表示に反映する。

        Args:
            progress: ダウンロード進捗情報
        """
        self._latest_progress = progress

    def close(self) -> None:
        """ダイアログを閉じる."""
        if self._closed:
            return
        self._closed = True
        if self._after_id is not None:
            self._dialog.after_cancel(self._after_id)
            self._after_id = None
        self._dialog.grab_release()
        self._dialog.destroy()

    def _handle_cancel(self) -> None:
        """キャンセルボタンまたはウィンドウ閉じのハンドラ."""
        self._on_cancel()

    def _schedule_update(self) -> None:
        """500ms ごとの定期 GUI 更新をスケジュールする."""
        if self._closed:
            return
        self._refresh_display()
        self._after_id = self._dialog.after(
            self.UPDATE_INTERVAL_MS, self._schedule_update
        )

    def _refresh_display(self) -> None:
        """バッファされた進捗情報で表示を更新する."""
        progress = self._latest_progress
        if progress is None:
            return

        # プログレスバー
        self._progressbar["value"] = progress.percent

        # パーセント表示
        self._percent_label.configure(text=f"{progress.percent}%")

        # サイズ表示
        self._size_label.configure(
            text=f"{progress.downloaded_mb} / {progress.total_mb}"
        )

        # 速度表示
        self._speed_label.configure(text=progress.speed_mb_s)

        # 残り時間表示
        eta = progress.eta_seconds
        if eta is None:
            self._eta_label.configure(text="計算中...")
        else:
            self._eta_label.configure(text=f"残り約 {eta:.0f} 秒")
