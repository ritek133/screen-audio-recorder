"""MainWindow: アプリケーションのメインウィンドウ.

tkinter を使用して録画開始・停止ボタン、モード選択、
マイクデバイス選択、ステータスバー、MemoListView、LLM 設定タブを提供する。

**Validates: Requirements 2.1, 2.4, 5.1, 5.2, 11.1**
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from screen_audio_recorder.models import LlmSettings, RecordingMode, RecordingRegion

if TYPE_CHECKING:
    from screen_audio_recorder.audio_capture import AudioCapture
    from screen_audio_recorder.memo_store import MemoStore
    from screen_audio_recorder.recorder_controller import RecorderController

logger = logging.getLogger(__name__)

# デフォルト録画領域
_DEFAULT_REGION = RecordingRegion(x=0, y=0, width=1280, height=720)


class MainWindow:
    """アプリケーションのメインウィンドウクラス.

    録画開始・停止ボタン、モード選択（画面+音声 / 音声のみ）、
    マイクデバイス選択コンボボックス、ステータスバー、
    MemoListView を配置する。

    Attributes:
        _root: tkinter ルートウィンドウ
        _recorder_controller: 録画制御コントローラ
        _memo_store: メモストア
        _audio_capture: 音声キャプチャ
    """

    def __init__(
        self,
        root: tk.Tk,
        recorder_controller: RecorderController,
        memo_store: MemoStore,
        audio_capture: AudioCapture,
        on_llm_settings_changed: callable | None = None,
    ) -> None:
        """MainWindow を初期化する.

        Args:
            root: tkinter ルートウィンドウ
            recorder_controller: 録画制御コントローラ
            memo_store: メモストア
            audio_capture: 音声キャプチャ（マイクデバイス一覧取得に使用）
            on_llm_settings_changed: LLM 設定変更時のコールバック
        """
        self._root = root
        self._recorder_controller = recorder_controller
        self._memo_store = memo_store
        self._audio_capture = audio_capture
        self._on_llm_settings_changed = on_llm_settings_changed

        self._root.title("Screen Audio Recorder")
        self._root.resizable(True, True)

        # 録画モード変数
        self._mode_var = tk.StringVar(value=RecordingMode.SCREEN_AND_AUDIO.value)

        # マイクデバイス変数
        self._mic_var = tk.StringVar()

        # ステータス変数
        self._status_var = tk.StringVar(value="モデル読み込み中...")

        # 初期化完了フラグ
        self._ready = False

        self._build_ui()
        self._load_mic_devices()

        # 初期化中は録画ボタンを無効化
        self._start_btn.config(state=tk.DISABLED)

        # 文字起こし完了後にメモ一覧を自動更新するコールバックを登録
        self._recorder_controller.set_on_memo_saved(self._on_memo_saved)

        # 録画領域オーバーレイ（画面+音声モード用）
        from screen_audio_recorder.gui.region_overlay import RegionOverlay
        self._region_overlay = RegionOverlay(self._root)

        # モード変更時にオーバーレイの表示/非表示を切り替え
        self._mode_var.trace_add("write", self._on_mode_changed)
        # 初期表示
        self._on_mode_changed()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """UI コンポーネントを構築・配置する."""
        # --- ステータスバー（先に pack して下部スペースを確保）---
        status_bar = ttk.Label(
            self._root,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(4, 2),
        )
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # メインフレーム
        main_frame = ttk.Frame(self._root, padding=8)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- タブコントロール ---
        self._notebook = ttk.Notebook(main_frame)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        # --- 録画タブ ---
        record_tab = ttk.Frame(self._notebook, padding=4)
        self._notebook.add(record_tab, text="録画")

        # --- コントロールパネル ---
        control_frame = ttk.LabelFrame(record_tab, text="録画コントロール", padding=6)
        control_frame.pack(fill=tk.X, pady=(0, 6))

        # モード選択
        mode_frame = ttk.Frame(control_frame)
        mode_frame.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(mode_frame, text="録画モード:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Radiobutton(
            mode_frame,
            text="画面 + 音声",
            variable=self._mode_var,
            value=RecordingMode.SCREEN_AND_AUDIO.value,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(
            mode_frame,
            text="音声のみ",
            variable=self._mode_var,
            value=RecordingMode.AUDIO_ONLY.value,
        ).pack(side=tk.LEFT)

        # マイクデバイス選択
        mic_frame = ttk.Frame(control_frame)
        mic_frame.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(mic_frame, text="マイク:").pack(side=tk.LEFT, padx=(0, 6))
        self._mic_combo = ttk.Combobox(
            mic_frame,
            textvariable=self._mic_var,
            state="readonly",
            width=40,
        )
        self._mic_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 録画ボタン
        btn_frame = ttk.Frame(control_frame)
        btn_frame.pack(fill=tk.X)

        self._start_btn = ttk.Button(
            btn_frame,
            text="録画開始",
            command=self._on_start,
        )
        self._start_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._stop_btn = ttk.Button(
            btn_frame,
            text="録画停止",
            command=self._on_stop,
            state=tk.DISABLED,
        )
        self._stop_btn.pack(side=tk.LEFT)

        # --- MemoListView ---
        from screen_audio_recorder.gui.memo_list_view import MemoListView

        self._memo_list_view = MemoListView(
            record_tab,
            self._memo_store,
            text_post_processor=getattr(self._recorder_controller, "_text_post_processor", None),
            root=self._root,
        )
        self._memo_list_view.frame.pack(fill=tk.BOTH, expand=True)

        # --- LLM 設定タブ ---
        from screen_audio_recorder.gui.llm_settings_tab import LlmSettingsTab

        self._llm_settings_tab = LlmSettingsTab(
            self._notebook,
            on_settings_changed=self._on_llm_settings_changed_internal,
        )
        self._notebook.add(self._llm_settings_tab.frame, text="LLM 設定")

        # --- 詳細設定タブ ---
        from screen_audio_recorder.gui.advanced_settings_tab import AdvancedSettingsTab

        self._advanced_settings_tab = AdvancedSettingsTab(self._notebook)
        self._notebook.add(self._advanced_settings_tab.frame, text="詳細設定")

        # --- バージョン情報タブ ---
        from screen_audio_recorder.gui.about_tab import AboutTab

        self._about_tab = AboutTab(self._notebook)
        self._notebook.add(self._about_tab.frame, text="このアプリについて")

    def _on_llm_settings_changed_internal(self, settings: LlmSettings) -> None:
        """LLM 設定変更時の内部ハンドラ."""
        if self._on_llm_settings_changed is not None:
            self._on_llm_settings_changed(settings)

    # ------------------------------------------------------------------
    # マイクデバイス読み込み
    # ------------------------------------------------------------------

    def _load_mic_devices(self) -> None:
        """マイクデバイス一覧を読み込んでコンボボックスに設定する."""
        try:
            devices = self._audio_capture.list_mic_devices()
        except Exception:
            logger.exception("マイクデバイス一覧の取得に失敗しました。")
            devices = []

        self._mic_devices = devices

        if devices:
            device_names = [d.name for d in devices]
            self._mic_combo["values"] = device_names
            self._mic_combo.current(0)
        else:
            self._mic_combo["values"] = ["(マイクなし)"]
            self._mic_combo.current(0)

    # ------------------------------------------------------------------
    # イベントハンドラ
    # ------------------------------------------------------------------

    def _on_mode_changed(self, *args) -> None:
        """モード変更時にオーバーレイの表示/非表示とボタンテキストを切り替える."""
        mode = RecordingMode(self._mode_var.get())
        if mode == RecordingMode.SCREEN_AND_AUDIO:
            self._region_overlay.show()
            self._start_btn.config(text="録画開始")
            self._stop_btn.config(text="録画停止")
        else:
            self._region_overlay.hide()
            self._start_btn.config(text="録音開始")
            self._stop_btn.config(text="録音停止")

    def _on_start(self) -> None:
        """録画開始ボタンのイベントハンドラ."""
        if not self._ready:
            return
        if self._recorder_controller.is_recording:
            return

        mode = RecordingMode(self._mode_var.get())

        # マイクデバイスインデックスを取得
        mic_index: int | None = None
        selected_idx = self._mic_combo.current()
        if self._mic_devices and selected_idx >= 0:
            mic_index = self._mic_devices[selected_idx].index

        # 録画領域を取得（画面+音声モードの場合はオーバーレイから）
        if mode == RecordingMode.SCREEN_AND_AUDIO:
            region = self._region_overlay.region
            # 録画中はオーバーレイを非表示にする（画面が黒くなる問題を防ぐ）
            self._region_overlay.hide()
        else:
            region = _DEFAULT_REGION

        try:
            self._recorder_controller.start_recording(
                mode=mode,
                region=region,
                mic_device_index=mic_index,
            )
        except Exception as exc:
            logger.exception("録画開始に失敗しました。")
            messagebox.showerror("録画エラー", f"録画を開始できませんでした:\n{exc}")
            # エラー時はオーバーレイを再表示
            if mode == RecordingMode.SCREEN_AND_AUDIO:
                self._region_overlay.show()
            return

        self._start_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.NORMAL)
        self._status_var.set("録画中...")
        logger.info("録画を開始しました。モード: %s", mode)

    def _on_stop(self) -> None:
        """録画停止ボタンのイベントハンドラ."""
        if not self._recorder_controller.is_recording:
            return

        try:
            self._recorder_controller.stop_recording()
        except Exception as exc:
            logger.exception("録画停止に失敗しました。")
            messagebox.showerror("録画エラー", f"録画を停止できませんでした:\n{exc}")
            return

        self._start_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)
        self._status_var.set("処理中...")

        # 画面+音声モードの場合はオーバーレイを再表示
        mode = RecordingMode(self._mode_var.get())
        if mode == RecordingMode.SCREEN_AND_AUDIO:
            self._region_overlay.show()

        logger.info("録画を停止しました。文字起こし処理中...")

    def set_ready(self) -> None:
        """初期化完了を通知し、録画ボタンを有効化する."""
        self._ready = True
        self._start_btn.config(state=tk.NORMAL)
        self._status_var.set("停止中")
        logger.info("アプリケーション準備完了。録画可能です。")

    def _on_memo_saved(self) -> None:
        """メモ保存完了時のコールバック（GUI スレッドから呼ばれる）."""
        self._memo_list_view.refresh()
        self._status_var.set("停止中")
        logger.info("メモ一覧を更新しました。")
