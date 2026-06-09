"""AdvancedSettingsTab: 詳細設定用の GUI タブ.

ログレベル切り替えなど、アプリケーション全般の詳細設定を提供する。
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from screen_audio_recorder.app_settings_store import load_app_settings, save_app_settings
from screen_audio_recorder.models import AppSettings

logger = logging.getLogger(__name__)


class AdvancedSettingsTab:
    """詳細設定用の GUI タブコンポーネント.

    Attributes:
        frame: 外部から参照可能なルートフレーム
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_settings_changed: Callable[[AppSettings], None] | None = None,
    ) -> None:
        """AdvancedSettingsTab を初期化する.

        Args:
            parent: 親ウィジェット
            on_settings_changed: 設定保存時に呼ばれるコールバック
        """
        self._on_settings_changed = on_settings_changed
        self.frame = ttk.Frame(parent, padding=8)

        # 現在の設定を読み込み
        self._settings = load_app_settings()

        # tkinter 変数
        self._verbose_var = tk.BooleanVar(value=self._settings.verbose_logging)

        self._build_ui()

    def _build_ui(self) -> None:
        """UI コンポーネントを構築・配置する."""
        # --- ログ設定 ---
        log_frame = ttk.LabelFrame(self.frame, text="ログ設定", padding=6)
        log_frame.pack(fill=tk.X, pady=(0, 8))

        self._verbose_check = ttk.Checkbutton(
            log_frame,
            text="詳細ログを有効にする（デバッグ用）",
            variable=self._verbose_var,
        )
        self._verbose_check.pack(anchor=tk.W, pady=(0, 4))

        ttk.Label(
            log_frame,
            text="有効にすると、音量情報やストリーム診断など詳細なログが出力されます。\n"
            "通常運用では無効のままで問題ありません。\n"
            "※ 設定変更はアプリ再起動後に反映されます。",
            foreground="gray",
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        # --- ボタン ---
        btn_frame = ttk.Frame(self.frame)
        btn_frame.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(
            btn_frame, text="設定を保存", command=self._on_save
        ).pack(side=tk.LEFT, padx=(0, 6))

    def _on_save(self) -> None:
        """設定を保存する."""
        settings = AppSettings(
            verbose_logging=self._verbose_var.get(),
        )
        try:
            save_app_settings(settings)
            self._settings = settings
            messagebox.showinfo(
                "設定保存",
                "詳細設定を保存しました。\nログレベルの変更はアプリ再起動後に反映されます。",
            )
            if self._on_settings_changed is not None:
                self._on_settings_changed(settings)
        except Exception as exc:
            logger.exception("詳細設定の保存に失敗しました。")
            messagebox.showerror("保存エラー", f"設定の保存に失敗しました:\n{exc}")
