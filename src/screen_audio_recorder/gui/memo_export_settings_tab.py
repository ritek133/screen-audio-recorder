"""MemoExportSettingsTab: メモエクスポート機能の設定用 GUI タブ.

ADR-004 参照。第1弾では HTML 継続出力の有効/無効・出力先・
output_file を含めるかの設定と、「今すぐ出力」を提供する。
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from screen_audio_recorder.export_settings_store import (
    load_export_settings,
    resolve_output_html_path,
    save_export_settings,
)
from screen_audio_recorder.models import ExportSettings

logger = logging.getLogger(__name__)


class MemoExportSettingsTab:
    """メモエクスポート設定用の GUI タブコンポーネント.

    Attributes:
        frame: 外部から参照可能なルートフレーム
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_settings_changed: Callable[[ExportSettings], None] | None = None,
        on_export_now: Callable[[], None] | None = None,
    ) -> None:
        """MemoExportSettingsTab を初期化する.

        Args:
            parent: 親ウィジェット
            on_settings_changed: 設定保存時に呼ばれるコールバック
                （ExportManager への設定反映に使う）
            on_export_now: 「今すぐ出力」ボタン押下時に呼ばれるコールバック
        """
        self._on_settings_changed = on_settings_changed
        self._on_export_now = on_export_now
        self.frame = ttk.Frame(parent, padding=8)

        # 現在の設定を読み込み
        self._settings = load_export_settings()

        # tkinter 変数
        self._html_enabled_var = tk.BooleanVar(value=self._settings.html_enabled)
        self._output_dir_var = tk.StringVar(value=self._settings.output_dir)
        self._include_path_var = tk.BooleanVar(
            value=self._settings.include_output_file_path
        )

        self._build_ui()

    def _build_ui(self) -> None:
        """UI コンポーネントを構築・配置する."""
        # --- HTML 出力設定 ---
        html_frame = ttk.LabelFrame(self.frame, text="HTML 継続出力", padding=6)
        html_frame.pack(fill=tk.X, pady=(0, 8))

        self._html_check = ttk.Checkbutton(
            html_frame,
            text="メモの追加・更新のたびに HTML を自動出力する",
            variable=self._html_enabled_var,
        )
        self._html_check.pack(anchor=tk.W, pady=(0, 4))

        ttk.Label(
            html_frame,
            text="要約と全文を閲覧しやすい単一 HTML ファイルに出力します。\n"
            "ファイルはブラウザでそのまま開けます（インターネット公開はしません）。",
            foreground="gray",
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 6))

        # 出力先ディレクトリ
        dir_row = ttk.Frame(html_frame)
        dir_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(dir_row, text="出力先:").pack(side=tk.LEFT, padx=(0, 4))
        self._output_dir_entry = ttk.Entry(
            dir_row, textvariable=self._output_dir_var, width=48
        )
        self._output_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(dir_row, text="参照...", command=self._browse_dir).pack(side=tk.LEFT)

        ttk.Label(
            html_frame,
            text="空欄の場合は既定の出力先（Documents/screen-audio-recorder/export）を使用します。",
            foreground="gray",
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 6))

        # output_file を含めるか
        self._include_check = ttk.Checkbutton(
            html_frame,
            text="録画ファイルのパス（output_file）も HTML に含める",
            variable=self._include_path_var,
        )
        self._include_check.pack(anchor=tk.W, pady=(0, 2))
        ttk.Label(
            html_frame,
            text="※ ローカルのフルパスが HTML に書き込まれます。通常はオフを推奨します。",
            foreground="gray",
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        # --- ボタン ---
        btn_frame = ttk.Frame(self.frame)
        btn_frame.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(
            btn_frame, text="設定を保存", command=self._on_save
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            btn_frame, text="今すぐ出力", command=self._on_export_now_clicked
        ).pack(side=tk.LEFT)

    def _browse_dir(self) -> None:
        """出力先ディレクトリ選択ダイアログを表示する."""
        path = filedialog.askdirectory(title="HTML の出力先フォルダを選択")
        if path:
            self._output_dir_var.set(path)

    def _collect_settings(self) -> ExportSettings:
        """UI の値から ExportSettings を構築する."""
        return ExportSettings(
            html_enabled=self._html_enabled_var.get(),
            output_dir=self._output_dir_var.get().strip(),
            include_output_file_path=self._include_path_var.get(),
        )

    def _on_save(self) -> None:
        """設定を保存する."""
        settings = self._collect_settings()
        try:
            save_export_settings(settings)
            self._settings = settings
            messagebox.showinfo("設定保存", "エクスポート設定を保存しました。")
            if self._on_settings_changed is not None:
                self._on_settings_changed(settings)
        except Exception as exc:
            logger.exception("エクスポート設定の保存に失敗しました。")
            messagebox.showerror("保存エラー", f"設定の保存に失敗しました:\n{exc}")

    def _on_export_now_clicked(self) -> None:
        """「今すぐ出力」ボタンのハンドラ."""
        # 保存前の UI 値を優先反映してから出力する
        settings = self._collect_settings()
        try:
            save_export_settings(settings)
            self._settings = settings
            if self._on_settings_changed is not None:
                self._on_settings_changed(settings)
            if self._on_export_now is not None:
                self._on_export_now()
            output_path = resolve_output_html_path(settings)
            messagebox.showinfo(
                "出力",
                f"HTML を出力しました。\n出力先:\n{output_path}",
            )
        except Exception as exc:
            logger.exception("HTML の出力に失敗しました。")
            messagebox.showerror("出力エラー", f"HTML の出力に失敗しました:\n{exc}")
