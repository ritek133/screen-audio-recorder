"""AboutTab: アプリケーションのバージョン情報タブ.

作者、会社、バージョンなどの情報を表示する。
更新機能 UI（更新確認ボタン、ステータス表示、ロールバックボタン）を含む。

Validates: Requirements 6, 7
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

import screen_audio_recorder
from screen_audio_recorder.updater_models import (
    UpdateState,
    UpdateStatus,
    UpdateType,
)

if TYPE_CHECKING:
    from screen_audio_recorder.updater import Updater

logger = logging.getLogger(__name__)

# ステータス表示の色マッピング
_STATUS_COLORS: dict[UpdateState, str] = {
    UpdateState.IDLE: "gray",
    UpdateState.CHECKING: "gray",
    UpdateState.UPDATE_AVAILABLE: "green",
    UpdateState.UP_TO_DATE: "green",
    UpdateState.DOWNLOADING: "blue",
    UpdateState.APPLYING: "gray",
    UpdateState.COMPLETED: "green",
    UpdateState.ERROR: "red",
}


class AboutTab:
    """「このアプリについて」タブのUIコンポーネント.

    Validates: Requirements 6, 7
    """

    def __init__(
        self,
        parent: ttk.Notebook,
        updater: "Updater | None" = None,
        is_recording: Callable[[], bool] | None = None,
    ) -> None:
        """AboutTab を初期化する.

        Args:
            parent: 親の Notebook ウィジェット
            updater: Updater インスタンス（None の場合は更新UI非表示）
            is_recording: 録画中判定コールバック
        """
        self._parent = parent
        self._updater = updater
        self._is_recording = is_recording

        self._frame = ttk.Frame(parent, padding=16)
        self._build_ui()

        if self._updater is not None:
            self._build_update_ui()

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

    def _build_update_ui(self) -> None:
        """更新機能 UI を構築する（updater が設定されている場合のみ）."""
        # 区切り線
        separator = ttk.Separator(self._frame, orient=tk.HORIZONTAL)
        separator.pack(fill=tk.X, pady=(16, 8))

        # 「更新を確認」ボタン
        self._check_update_button = ttk.Button(
            self._frame,
            text="更新を確認",
            command=self._on_check_update,
        )
        self._check_update_button.pack(pady=(8, 4))

        # ステータス表示エリア（tk.Label で fg 色を直接制御）
        self._status_label = tk.Label(
            self._frame,
            text="",
            font=("", 9),
            fg="gray",
        )
        self._status_label.pack(pady=(4, 8))

        # 「前のバージョンに戻す」ボタン（バックアップ存在時のみ表示）
        self._rollback_button = ttk.Button(
            self._frame,
            text="前のバージョンに戻す",
            command=self._on_rollback,
        )
        # 初期状態ではバックアップの有無を確認して表示/非表示を設定
        self._update_rollback_button_visibility()

        # ツールチップ用変数
        self._tooltip_window: tk.Toplevel | None = None

        # 録画中チェックのバインド
        if self._is_recording is not None:
            self._check_update_button.bind("<Enter>", self._on_button_enter)
            self._check_update_button.bind("<Leave>", self._on_button_leave)

    def _update_rollback_button_visibility(self) -> None:
        """ロールバックボタンの表示/非表示を更新する."""
        if self._updater is None:
            return

        backup_info = self._updater.find_backup()
        if backup_info is not None:
            self._rollback_button.configure(
                text=f"前のバージョンに戻す (v{backup_info.version})"
            )
            self._rollback_button.pack(pady=(4, 8))
        else:
            self._rollback_button.pack_forget()

    def _on_check_update(self) -> None:
        """「更新を確認」ボタンのイベントハンドラ."""
        # 録画中チェック
        if self._is_recording is not None and self._is_recording():
            messagebox.showinfo(
                "更新確認",
                "録画中は更新できません。録画を停止してから再度お試しください。",
            )
            return

        if self._updater is None:
            return

        # ボタンを無効化
        self._check_update_button.configure(state=tk.DISABLED)

        # ステータスコールバックを設定してから確認開始
        self._updater._on_status_changed = self._on_status_changed_from_thread

        # 更新確認を開始
        self._updater.check_for_update()

    def _on_status_changed_from_thread(self, status: UpdateStatus) -> None:
        """バックグラウンドスレッドからのステータス変更を GUI スレッドに転送する."""
        try:
            self._frame.after(0, self._on_status_changed, status)
        except tk.TclError:
            # ウィジェットが破棄されている場合
            pass

    def _on_status_changed(self, status: UpdateStatus) -> None:
        """ステータス変更時のコールバック（GUI スレッドで呼ばれる）.

        ステータスに応じて表示テキストと色を更新し、
        必要に応じて更新ダイアログを表示する。
        """
        color = _STATUS_COLORS.get(status.state, "gray")

        # ステータスメッセージの構築
        if status.state == UpdateState.CHECKING:
            text = "🔍 最新バージョンを確認中..."
        elif status.state == UpdateState.UPDATE_AVAILABLE:
            version_str = status.version or ""
            text = f"✅ 新しいバージョン v{version_str} が利用可能です"
        elif status.state == UpdateState.UP_TO_DATE:
            version_str = status.version or ""
            text = f"✅ 最新バージョンです (v{version_str})"
        elif status.state == UpdateState.DOWNLOADING:
            text = "⬇️ ダウンロード中..."
        elif status.state == UpdateState.APPLYING:
            text = "🔄 更新を適用中..."
        elif status.state == UpdateState.COMPLETED:
            text = "✅ 更新完了。再起動します..."
        elif status.state == UpdateState.ERROR:
            error_summary = status.error or status.message
            text = f"❌ エラー: {error_summary}"
        else:
            text = ""

        # ステータスラベルを更新
        self._status_label.configure(text=text, fg=color)

        # ボタン状態の復元（確認完了後）
        if status.state in (
            UpdateState.UPDATE_AVAILABLE,
            UpdateState.UP_TO_DATE,
            UpdateState.ERROR,
            UpdateState.IDLE,
        ):
            self._check_update_button.configure(state=tk.NORMAL)

        # 更新利用可能時: ダイアログ表示
        if status.state == UpdateState.UPDATE_AVAILABLE:
            self._show_update_available_dialog()

        # ロールバックボタンの状態を更新
        self._update_rollback_button_visibility()

    def _show_update_available_dialog(self) -> None:
        """更新利用可能時のダイアログを表示する."""
        if self._updater is None or self._updater._latest_release is None:
            return

        release_info = self._updater._latest_release
        release_notes_preview = release_info.release_notes[:200]
        if len(release_info.release_notes) > 200:
            release_notes_preview += "..."

        update_type_text = (
            "フル更新（_internal 含む）"
            if release_info.update_type == UpdateType.FULL
            else "通常更新（アプリ本体のみ）"
        )

        size_mb = release_info.target_asset.size / (1024 * 1024)

        message = (
            f"新しいバージョン v{release_info.version} が利用可能です。\n\n"
            f"更新種別: {update_type_text}\n"
            f"ファイルサイズ: {size_mb:.1f} MB\n\n"
            f"リリースノート:\n{release_notes_preview}"
        )

        result = messagebox.askyesno(
            "更新のお知らせ",
            message,
            default=messagebox.YES,
        )

        if result:
            self._start_download(release_info)

    def _start_download(self, release_info: "object") -> None:
        """ダウンロードを開始し、進捗ダイアログを表示する."""
        from screen_audio_recorder.gui.update_progress_dialog import (
            UpdateProgressDialog,
        )
        from screen_audio_recorder.updater_models import ReleaseInfo

        if self._updater is None:
            return

        # 型アサーション
        if not isinstance(release_info, ReleaseInfo):
            return

        # 進捗ダイアログを作成
        root = self._frame.winfo_toplevel()
        self._progress_dialog = UpdateProgressDialog(
            parent=root,
            on_cancel=self._on_download_cancel,
        )

        # 進捗コールバックを設定
        self._updater._on_progress = self._on_progress_from_thread

        # ダウンロード＆適用を開始
        self._updater.download_and_apply(release_info)

    def _on_progress_from_thread(self, progress: "object") -> None:
        """バックグラウンドスレッドからの進捗通知を GUI スレッドに転送する."""
        from screen_audio_recorder.updater_models import DownloadProgress

        if not isinstance(progress, DownloadProgress):
            return

        try:
            self._frame.after(0, self._on_progress_update, progress)
        except tk.TclError:
            pass

    def _on_progress_update(self, progress: "object") -> None:
        """進捗ダイアログを更新する（GUI スレッド）."""
        from screen_audio_recorder.updater_models import DownloadProgress

        if not isinstance(progress, DownloadProgress):
            return

        if hasattr(self, "_progress_dialog") and self._progress_dialog is not None:
            self._progress_dialog.update_progress(progress)

            # ステータスラベルも更新
            self._status_label.configure(
                text=f"⬇️ ダウンロード中... ({progress.percent}%)",
                fg="blue",
            )

    def _on_download_cancel(self) -> None:
        """ダウンロードキャンセルハンドラ."""
        if self._updater is not None:
            self._updater.cancel_download()

        # 進捗ダイアログを閉じる
        if hasattr(self, "_progress_dialog") and self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None

        # ステータスをリセット
        self._status_label.configure(text="", fg="gray")
        self._check_update_button.configure(state=tk.NORMAL)

    def _on_rollback(self) -> None:
        """「前のバージョンに戻す」ボタンのイベントハンドラ."""
        # 録画中チェック
        if self._is_recording is not None and self._is_recording():
            messagebox.showinfo(
                "ロールバック",
                "録画中はロールバックできません。録画を停止してから再度お試しください。",
            )
            return

        if self._updater is None:
            return

        backup_info = self._updater.find_backup()
        if backup_info is None:
            return

        # 確認ダイアログ
        result = messagebox.askyesno(
            "バージョンを戻す",
            f"バージョン {backup_info.version} に戻しますか？",
        )

        if result:
            self._updater.rollback()

    def _on_button_enter(self, event: "tk.Event[tk.Widget]") -> None:
        """ボタンにマウスが入った時のハンドラ（ツールチップ表示）."""
        if self._is_recording is not None and self._is_recording():
            # ツールチップを表示
            self._show_tooltip("録画中は更新できません")

    def _on_button_leave(self, event: "tk.Event[tk.Widget]") -> None:
        """ボタンからマウスが離れた時のハンドラ（ツールチップ非表示）."""
        self._hide_tooltip()

    def _show_tooltip(self, text: str) -> None:
        """ツールチップを表示する."""
        if self._tooltip_window is not None:
            return

        x = self._check_update_button.winfo_rootx() + 20
        y = self._check_update_button.winfo_rooty() + 30

        self._tooltip_window = tw = tk.Toplevel(self._frame)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            tw,
            text=text,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            font=("", 8),
        )
        label.pack()

    def _hide_tooltip(self) -> None:
        """ツールチップを非表示にする."""
        if self._tooltip_window is not None:
            self._tooltip_window.destroy()
            self._tooltip_window = None

    def update_recording_state(self) -> None:
        """録画状態に応じてボタンの有効/無効を更新する.

        外部から定期的に呼び出すことで、録画状態の変化を反映する。
        """
        if not hasattr(self, "_check_update_button"):
            return

        if self._is_recording is not None and self._is_recording():
            self._check_update_button.configure(state=tk.DISABLED)
        else:
            # ダウンロード中等でない場合のみ有効化
            self._check_update_button.configure(state=tk.NORMAL)
