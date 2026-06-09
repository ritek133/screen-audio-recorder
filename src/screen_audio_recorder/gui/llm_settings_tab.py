"""LlmSettingsTab: LLM 設定用の GUI タブ.

推論バックエンド選択、モデルパス/API エンドポイント設定、
各タスクのプロンプトテンプレート編集、モデルダウンロード機能を提供する。

**Validates: Requirements 11.1〜11.7**
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Callable

from screen_audio_recorder.llm_settings_store import load_settings, save_settings
from screen_audio_recorder.models import (
    DEFAULT_PROMPT_FIX_TEXT,
    DEFAULT_PROMPT_SUMMARIZE,
    DEFAULT_PROMPT_THEME,
    LlmBackend,
    LlmSettings,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ダウンロード可能なモデル一覧
_DOWNLOADABLE_MODELS = [
    {
        "name": "Qwen2.5 1.5B (Q4_K_M) — 最軽量・日本語◎ [約1.0GB]",
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    },
    {
        "name": "Gemma 2 2B (Q4_K_M) — バランス型・日本語◎ [約1.5GB]",
        "url": "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf",
        "filename": "gemma-2-2b-it-Q4_K_M.gguf",
    },
]

# モデル保存先ディレクトリ
_MODEL_DIR = Path.home() / "Documents" / "screen-audio-recorder" / "models"


class LlmSettingsTab:
    """LLM 設定用の GUI タブコンポーネント.

    Attributes:
        frame: 外部から参照可能なルートフレーム
        _on_settings_changed: 設定変更時のコールバック
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_settings_changed: Callable[[LlmSettings], None] | None = None,
    ) -> None:
        """LlmSettingsTab を初期化する.

        Args:
            parent: 親ウィジェット
            on_settings_changed: 設定保存時に呼ばれるコールバック
        """
        self._on_settings_changed = on_settings_changed

        self.frame = ttk.Frame(parent, padding=8)

        # 現在の設定を読み込み
        self._settings = load_settings()

        # tkinter 変数
        self._backend_var = tk.StringVar(value=self._settings.backend.value)
        self._model_path_var = tk.StringVar(value=self._settings.local_model_path)
        self._api_endpoint_var = tk.StringVar(value=self._settings.api_endpoint)
        self._api_key_var = tk.StringVar(value=self._settings.api_key)
        self._max_tokens_var = tk.IntVar(value=self._settings.max_tokens)
        self._temperature_var = tk.DoubleVar(value=self._settings.temperature)
        self._ctx_size_var = tk.IntVar(value=self._settings.ctx_size)
        self._timeout_var = tk.IntVar(value=self._settings.timeout_seconds)
        self._whisper_model_size_var = tk.StringVar(value=self._settings.whisper_model_size)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """UI コンポーネントを構築・配置する."""
        # スクロール可能なキャンバス
        canvas = tk.Canvas(self.frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.frame, orient=tk.VERTICAL, command=canvas.yview)
        self._scroll_frame = ttk.Frame(canvas)

        self._scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # マウスホイールスクロール
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        parent = self._scroll_frame

        # --- バックエンド選択 ---
        backend_frame = ttk.LabelFrame(parent, text="推論バックエンド", padding=6)
        backend_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Radiobutton(
            backend_frame,
            text="ローカル（llama-server）",
            variable=self._backend_var,
            value=LlmBackend.LOCAL.value,
            command=self._on_backend_changed,
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            backend_frame,
            text="オンプレ API（OpenAI 互換）",
            variable=self._backend_var,
            value=LlmBackend.API.value,
            command=self._on_backend_changed,
        ).pack(anchor=tk.W)

        # --- ローカルモデル設定 ---
        self._local_frame = ttk.LabelFrame(parent, text="ローカルモデル設定", padding=6)
        self._local_frame.pack(fill=tk.X, pady=(0, 8))

        path_row = ttk.Frame(self._local_frame)
        path_row.pack(fill=tk.X)

        ttk.Label(path_row, text="モデルファイル（GGUF）:").pack(anchor=tk.W)
        entry_row = ttk.Frame(path_row)
        entry_row.pack(fill=tk.X)

        self._model_path_entry = ttk.Entry(
            entry_row, textvariable=self._model_path_var, width=50
        )
        self._model_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        ttk.Button(
            entry_row, text="参照...", command=self._browse_model, width=8
        ).pack(side=tk.LEFT)

        # モデルダウンロードセクション
        dl_frame = ttk.Frame(self._local_frame)
        dl_frame.pack(fill=tk.X, pady=(6, 0))

        ttk.Label(
            dl_frame,
            text="モデルが無い場合はここからダウンロードできます:",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(0, 2))

        dl_row = ttk.Frame(dl_frame)
        dl_row.pack(fill=tk.X)

        self._model_combo_var = tk.StringVar()
        model_names = [m["name"] for m in _DOWNLOADABLE_MODELS]
        self._model_combo = ttk.Combobox(
            dl_row,
            textvariable=self._model_combo_var,
            values=model_names,
            state="readonly",
            width=50,
        )
        if model_names:
            self._model_combo.current(0)
        self._model_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self._download_btn = ttk.Button(
            dl_row, text="ダウンロード", command=self._on_download_model, width=14
        )
        self._download_btn.pack(side=tk.LEFT)

        # ダウンロード進捗
        self._dl_progress_var = tk.StringVar(value="")
        self._dl_progress_label = ttk.Label(
            dl_frame, textvariable=self._dl_progress_var, foreground="blue"
        )
        self._dl_progress_label.pack(anchor=tk.W, pady=(2, 0))

        # llama-server ダウンロードセクション
        server_frame = ttk.Frame(self._local_frame)
        server_frame.pack(fill=tk.X, pady=(8, 0))

        # llama-server の状態表示
        from screen_audio_recorder.llm_client import _find_llama_server
        server_path = _find_llama_server()
        if server_path:
            server_status = f"✓ llama-server 検出済み: {server_path}"
            server_color = "green"
        else:
            server_status = "✗ llama-server が見つかりません（ローカルモードに必要）"
            server_color = "red"

        self._server_status_var = tk.StringVar(value=server_status)
        self._server_status_label = ttk.Label(
            server_frame, textvariable=self._server_status_var, foreground=server_color
        )
        self._server_status_label.pack(anchor=tk.W, pady=(0, 2))

        self._dl_server_btn = ttk.Button(
            server_frame,
            text="llama-server をダウンロード",
            command=self._on_download_server,
            width=30,
        )
        self._dl_server_btn.pack(anchor=tk.W)

        self._server_dl_progress_var = tk.StringVar(value="")
        self._server_dl_progress_label = ttk.Label(
            server_frame, textvariable=self._server_dl_progress_var, foreground="blue"
        )
        self._server_dl_progress_label.pack(anchor=tk.W, pady=(2, 0))

        # --- API 設定 ---
        self._api_frame = ttk.LabelFrame(parent, text="オンプレ API 設定", padding=6)
        self._api_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(self._api_frame, text="エンドポイント URL:").pack(anchor=tk.W)
        ttk.Entry(
            self._api_frame, textvariable=self._api_endpoint_var, width=60
        ).pack(fill=tk.X, pady=(0, 4))

        ttk.Label(self._api_frame, text="API キー（オプション）:").pack(anchor=tk.W)
        ttk.Entry(
            self._api_frame, textvariable=self._api_key_var, show="*", width=60
        ).pack(fill=tk.X)

        # --- 文字起こし設定（Whisper） ---
        whisper_frame = ttk.LabelFrame(parent, text="文字起こし設定（Whisper）", padding=6)
        whisper_frame.pack(fill=tk.X, pady=(0, 8))

        whisper_row = ttk.Frame(whisper_frame)
        whisper_row.pack(fill=tk.X)

        ttk.Label(whisper_row, text="モデルサイズ:").pack(side=tk.LEFT, padx=(0, 6))
        _WHISPER_MODEL_SIZES = ["tiny", "base", "small", "medium", "large"]
        self._whisper_model_combo = ttk.Combobox(
            whisper_row,
            textvariable=self._whisper_model_size_var,
            values=_WHISPER_MODEL_SIZES,
            state="readonly",
            width=12,
        )
        self._whisper_model_combo.pack(side=tk.LEFT)

        ttk.Label(
            whisper_frame,
            text="※ large: 高精度（約3GB）、medium: バランス（約1.5GB）、small: 軽量（約500MB）\n"
                 "※ 変更は次回の文字起こし時に反映されます（モデル再ロード）",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(4, 0))

        # --- 生成パラメータ ---
        param_frame = ttk.LabelFrame(parent, text="生成パラメータ", padding=6)
        param_frame.pack(fill=tk.X, pady=(0, 8))

        row1 = ttk.Frame(param_frame)
        row1.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row1, text="最大トークン数:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Spinbox(
            row1,
            textvariable=self._max_tokens_var,
            from_=128,
            to=4096,
            increment=128,
            width=8,
        ).pack(side=tk.LEFT)

        row2 = ttk.Frame(param_frame)
        row2.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row2, text="Temperature:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Spinbox(
            row2,
            textvariable=self._temperature_var,
            from_=0.0,
            to=2.0,
            increment=0.1,
            width=8,
            format="%.1f",
        ).pack(side=tk.LEFT)

        row3 = ttk.Frame(param_frame)
        row3.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row3, text="コンテキストサイズ:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Spinbox(
            row3,
            textvariable=self._ctx_size_var,
            from_=2048,
            to=131072,
            increment=1024,
            width=10,
        ).pack(side=tk.LEFT)
        ttk.Label(
            row3,
            text="（トークン数。大きいほどメモリ使用量増）",
            foreground="gray",
        ).pack(side=tk.LEFT, padx=(6, 0))

        row4 = ttk.Frame(param_frame)
        row4.pack(fill=tk.X)
        ttk.Label(row4, text="タイムアウト:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Spinbox(
            row4,
            textvariable=self._timeout_var,
            from_=60,
            to=3600,
            increment=60,
            width=8,
        ).pack(side=tk.LEFT)
        ttk.Label(
            row4,
            text="秒（CPU 推論は長時間かかる場合あり）",
            foreground="gray",
        ).pack(side=tk.LEFT, padx=(6, 0))

        # --- プロンプトテンプレート ---
        prompt_frame = ttk.LabelFrame(parent, text="プロンプトテンプレート", padding=6)
        prompt_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        ttk.Label(
            prompt_frame,
            text="※ {text} がテキストに置換されます",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(0, 4))

        # テキスト修正プロンプト
        ttk.Label(prompt_frame, text="テキスト修正:").pack(anchor=tk.W)
        self._prompt_fix = tk.Text(prompt_frame, height=4, wrap=tk.WORD)
        self._prompt_fix.pack(fill=tk.X, pady=(0, 6))
        self._prompt_fix.insert("1.0", self._settings.prompt_fix_text)

        # 要約生成プロンプト
        ttk.Label(prompt_frame, text="要約生成:").pack(anchor=tk.W)
        self._prompt_summarize = tk.Text(prompt_frame, height=4, wrap=tk.WORD)
        self._prompt_summarize.pack(fill=tk.X, pady=(0, 6))
        self._prompt_summarize.insert("1.0", self._settings.prompt_summarize)

        # テーマ生成プロンプト
        ttk.Label(prompt_frame, text="テーマ生成:").pack(anchor=tk.W)
        self._prompt_theme = tk.Text(prompt_frame, height=4, wrap=tk.WORD)
        self._prompt_theme.pack(fill=tk.X, pady=(0, 6))
        self._prompt_theme.insert("1.0", self._settings.prompt_theme)

        # --- ボタン ---
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(
            btn_frame, text="設定を保存", command=self._on_save
        ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(
            btn_frame, text="接続テスト", command=self._on_test_connection
        ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(
            btn_frame, text="デフォルトに戻す", command=self._on_reset
        ).pack(side=tk.LEFT)

        # テスト結果表示
        self._test_result_var = tk.StringVar(value="")
        self._test_result_label = ttk.Label(
            parent, textvariable=self._test_result_var
        )
        self._test_result_label.pack(anchor=tk.W, pady=(0, 8))

        # 初期表示の切り替え
        self._on_backend_changed()

    # ------------------------------------------------------------------
    # イベントハンドラ
    # ------------------------------------------------------------------

    def _on_backend_changed(self) -> None:
        """バックエンド選択変更時に表示を切り替える."""
        backend = self._backend_var.get()
        if backend == LlmBackend.LOCAL.value:
            self._set_frame_state(self._local_frame, tk.NORMAL)
            self._set_frame_state(self._api_frame, tk.DISABLED)
        else:
            self._set_frame_state(self._local_frame, tk.DISABLED)
            self._set_frame_state(self._api_frame, tk.NORMAL)

    def _browse_model(self) -> None:
        """モデルファイル選択ダイアログを表示する."""
        path = filedialog.askopenfilename(
            title="GGUF モデルファイルを選択",
            filetypes=[("GGUF files", "*.gguf"), ("All files", "*.*")],
        )
        if path:
            self._model_path_var.set(path)

    def _on_save(self) -> None:
        """設定を保存する."""
        settings = self._collect_settings()
        try:
            save_settings(settings)
            self._settings = settings
            messagebox.showinfo("設定保存", "LLM 設定を保存しました。")
            if self._on_settings_changed is not None:
                self._on_settings_changed(settings)
        except Exception as exc:
            logger.exception("設定の保存に失敗しました。")
            messagebox.showerror("保存エラー", f"設定の保存に失敗しました:\n{exc}")

    def _on_test_connection(self) -> None:
        """現在の設定で LLM 接続テストを実行する."""
        self._test_result_var.set("テスト中...")
        self._test_result_label.configure(foreground="blue")

        settings = self._collect_settings()

        def _worker():
            try:
                from screen_audio_recorder.llm_client import LlmClient

                client = LlmClient(settings)
                if not client.available:
                    _show_result("✗ LLM が利用不可です。設定を確認してください。", "red")
                    return

                result = client.generate("「テスト」と一言だけ返してください。")
                if result:
                    _show_result(
                        f"✓ 接続成功！応答: {result[:50]}",
                        "green",
                    )
                else:
                    _show_result("✗ 応答が空です。モデルまたはAPIを確認してください。", "red")
            except Exception as exc:
                _show_result(f"✗ エラー: {exc}", "red")

        def _show_result(text: str, color: str):
            self.frame.after(0, lambda: (
                self._test_result_var.set(text),
                self._test_result_label.configure(foreground=color),
            ))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_download_model(self) -> None:
        """選択されたモデルをダウンロードする."""
        idx = self._model_combo.current()
        if idx < 0:
            return

        model_info = _DOWNLOADABLE_MODELS[idx]
        url = model_info["url"]
        filename = model_info["filename"]
        dest_path = _MODEL_DIR / filename

        if dest_path.exists():
            # 既にダウンロード済み
            self._model_path_var.set(str(dest_path))
            self._dl_progress_var.set(f"✓ 既にダウンロード済み: {filename}")
            self._dl_progress_label.configure(foreground="green")
            return

        self._download_btn.configure(state=tk.DISABLED)
        self._dl_progress_var.set(f"ダウンロード中: {filename} ...")
        self._dl_progress_label.configure(foreground="blue")

        def _worker():
            try:
                import urllib.request

                _MODEL_DIR.mkdir(parents=True, exist_ok=True)
                tmp_path = dest_path.with_suffix(".gguf.tmp")

                # ダウンロード（進捗表示付き）
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=300) as resp:
                    total = int(resp.headers.get("Content-Length", 0))
                    downloaded = 0
                    chunk_size = 1024 * 1024  # 1MB

                    with open(tmp_path, "wb") as f:
                        while True:
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                pct = downloaded * 100 // total
                                mb_done = downloaded / (1024 * 1024)
                                mb_total = total / (1024 * 1024)
                                _update_progress(
                                    f"ダウンロード中: {mb_done:.0f}/{mb_total:.0f} MB ({pct}%)"
                                )

                # ダウンロード完了 → リネーム
                tmp_path.rename(dest_path)

                # モデルパスを自動設定
                self.frame.after(0, lambda: self._model_path_var.set(str(dest_path)))
                _update_progress(f"✓ ダウンロード完了: {filename}")
                self.frame.after(
                    0, lambda: self._dl_progress_label.configure(foreground="green")
                )

            except Exception as exc:
                logger.exception("モデルのダウンロードに失敗しました。")
                _update_progress(f"✗ ダウンロード失敗: {exc}")
                self.frame.after(
                    0, lambda: self._dl_progress_label.configure(foreground="red")
                )
                # 一時ファイルを削除
                tmp_path = dest_path.with_suffix(".gguf.tmp")
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
            finally:
                self.frame.after(
                    0, lambda: self._download_btn.configure(state=tk.NORMAL)
                )

        def _update_progress(text: str):
            self.frame.after(0, lambda: self._dl_progress_var.set(text))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_download_server(self) -> None:
        """llama-server をダウンロードする."""
        from screen_audio_recorder.llm_client import _find_llama_server

        if _find_llama_server():
            self._server_dl_progress_var.set("✓ llama-server は既にインストール済みです。")
            self._server_dl_progress_label.configure(foreground="green")
            return

        self._dl_server_btn.configure(state=tk.DISABLED)
        self._server_dl_progress_var.set("ダウンロード中...")
        self._server_dl_progress_label.configure(foreground="blue")

        def _worker():
            try:
                from scripts.download_llama_server import download_to_app_dir

                path = download_to_app_dir()
                self.frame.after(0, lambda: (
                    self._server_dl_progress_var.set(f"✓ ダウンロード完了: {path}"),
                    self._server_dl_progress_label.configure(foreground="green"),
                    self._server_status_var.set(f"✓ llama-server 検出済み: {path}"),
                    self._server_status_label.configure(foreground="green"),
                ))
            except ImportError:
                # scripts モジュールが見つからない場合は直接ダウンロード
                try:
                    self._download_server_direct()
                except Exception as exc:
                    self.frame.after(0, lambda: (
                        self._server_dl_progress_var.set(f"✗ ダウンロード失敗: {exc}"),
                        self._server_dl_progress_label.configure(foreground="red"),
                    ))
            except Exception as exc:
                logger.exception("llama-server のダウンロードに失敗しました。")
                self.frame.after(0, lambda: (
                    self._server_dl_progress_var.set(f"✗ ダウンロード失敗: {exc}"),
                    self._server_dl_progress_label.configure(foreground="red"),
                ))
            finally:
                self.frame.after(
                    0, lambda: self._dl_server_btn.configure(state=tk.NORMAL)
                )

        threading.Thread(target=_worker, daemon=True).start()

    def _download_server_direct(self) -> None:
        """llama-server を直接ダウンロードする（scripts モジュール不要版）."""
        import io
        import json
        import shutil
        import urllib.request
        import zipfile

        releases_api = "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"
        bin_dir = Path.home() / "Documents" / "screen-audio-recorder" / "bin"
        output_path = bin_dir / "llama-server.exe"

        # 最新リリース URL を取得
        self.frame.after(0, lambda: self._server_dl_progress_var.set("リリース情報を取得中..."))
        req = urllib.request.Request(releases_api, headers={"User-Agent": "screen-audio-recorder"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        url = None
        for asset in data.get("assets", []):
            name = asset["name"].lower()
            if "win" in name and "x64" in name and "vulkan" not in name and "cuda" not in name and name.endswith(".zip"):
                url = asset["browser_download_url"]
                break
        if url is None:
            for asset in data.get("assets", []):
                name = asset["name"].lower()
                if "win" in name and name.endswith(".zip"):
                    url = asset["browser_download_url"]
                    break
        if url is None:
            raise RuntimeError("Windows 用の llama.cpp リリースが見つかりません")

        # ダウンロード
        self.frame.after(0, lambda: self._server_dl_progress_var.set("ダウンロード中..."))
        req = urllib.request.Request(url, headers={"User-Agent": "screen-audio-recorder"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            zip_data = resp.read()

        # 展開
        self.frame.after(0, lambda: self._server_dl_progress_var.set("展開中..."))
        bin_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            server_entry = None
            for name in zf.namelist():
                basename = name.rsplit("/", 1)[-1] if "/" in name else name
                if basename == "llama-server.exe":
                    server_entry = name
                    break
            if server_entry is None:
                raise FileNotFoundError("zip 内に llama-server.exe が見つかりません")

            # llama-server.exe と同じディレクトリの全ファイルを展開（DLL が必要）
            server_dir = server_entry.rsplit("/", 1)[0] + "/" if "/" in server_entry else ""
            for name in zf.namelist():
                if not name.startswith(server_dir):
                    continue
                basename = name[len(server_dir):]
                if not basename or "/" in basename:
                    continue
                target = bin_dir / basename
                with zf.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        self.frame.after(0, lambda: (
            self._server_dl_progress_var.set(f"✓ ダウンロード完了: {output_path}"),
            self._server_dl_progress_label.configure(foreground="green"),
            self._server_status_var.set(f"✓ llama-server 検出済み: {output_path}"),
            self._server_status_label.configure(foreground="green"),
        ))

    def _on_reset(self) -> None:
        """プロンプトをデフォルトに戻す."""
        self._prompt_fix.delete("1.0", tk.END)
        self._prompt_fix.insert("1.0", DEFAULT_PROMPT_FIX_TEXT)

        self._prompt_summarize.delete("1.0", tk.END)
        self._prompt_summarize.insert("1.0", DEFAULT_PROMPT_SUMMARIZE)

        self._prompt_theme.delete("1.0", tk.END)
        self._prompt_theme.insert("1.0", DEFAULT_PROMPT_THEME)

        self._max_tokens_var.set(1024)
        self._temperature_var.set(0.3)
        self._ctx_size_var.set(8192)
        self._timeout_var.set(600)

    # ------------------------------------------------------------------
    # ヘルパー
    # ------------------------------------------------------------------

    def _collect_settings(self) -> LlmSettings:
        """UI の値から LlmSettings を構築する."""
        try:
            backend = LlmBackend(self._backend_var.get())
        except ValueError:
            backend = LlmBackend.LOCAL

        return LlmSettings(
            backend=backend,
            local_model_path=self._model_path_var.get().strip(),
            api_endpoint=self._api_endpoint_var.get().strip(),
            api_key=self._api_key_var.get().strip(),
            prompt_fix_text=self._prompt_fix.get("1.0", tk.END).strip(),
            prompt_summarize=self._prompt_summarize.get("1.0", tk.END).strip(),
            prompt_theme=self._prompt_theme.get("1.0", tk.END).strip(),
            max_tokens=self._max_tokens_var.get(),
            temperature=self._temperature_var.get(),
            ctx_size=self._ctx_size_var.get(),
            timeout_seconds=self._timeout_var.get(),
            whisper_model_size=self._whisper_model_size_var.get(),
        )

    @staticmethod
    def _set_frame_state(frame: ttk.LabelFrame, state: str) -> None:
        """フレーム内の全ウィジェットの状態を変更する."""
        for child in frame.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass
            # 再帰的に子ウィジェットも処理
            if hasattr(child, "winfo_children"):
                for grandchild in child.winfo_children():
                    try:
                        grandchild.configure(state=state)
                    except tk.TclError:
                        pass
