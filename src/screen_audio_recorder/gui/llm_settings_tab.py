"""LlmSettingsTab: LLM・文字起こし・AWS 設定用の GUI タブ.

推論バックエンド選択、モデルパス/API エンドポイント設定、
文字起こしバックエンド（ローカル/vLLM/Amazon Transcribe）選択、
AWS 接続設定、各タスクのプロンプトテンプレート編集、モデルダウンロード機能を提供する。

**Validates: Requirements 11.1〜11.7**
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Callable

from screen_audio_recorder.llm_settings_store import (
    load_all_settings,
    save_all_settings,
)
from screen_audio_recorder.models import (
    DEFAULT_PROMPT_FIX_TEXT,
    DEFAULT_PROMPT_SUMMARIZE,
    DEFAULT_PROMPT_THEME,
    AwsAuthMethod,
    AwsSettings,
    LlmBackend,
    LlmSettings,
    TranscriberBackend,
    TranscriberSettings,
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

# Bedrock で利用可能なモデル一覧
_BEDROCK_MODELS = [
    "anthropic.claude-3-haiku-20240307-v1:0",
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "anthropic.claude-3-5-haiku-20241022-v1:0",
    "amazon.titan-text-express-v1",
    "amazon.titan-text-lite-v1",
]

# AWS リージョン一覧（Bedrock 対応リージョン）
_AWS_REGIONS = [
    "us-east-1",
    "us-west-2",
    "ap-northeast-1",
    "ap-southeast-1",
    "eu-west-1",
    "eu-central-1",
]


class LlmSettingsTab:
    """LLM・文字起こし・AWS 設定用の GUI タブコンポーネント.

    Attributes:
        frame: 外部から参照可能なルートフレーム
        _on_settings_changed: 設定変更時のコールバック
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_settings_changed: Callable[[LlmSettings, AwsSettings], None] | None = None,
    ) -> None:
        """LlmSettingsTab を初期化する.

        Args:
            parent: 親ウィジェット
            on_settings_changed: 設定保存時に呼ばれるコールバック
        """
        self._on_settings_changed = on_settings_changed

        self.frame = ttk.Frame(parent, padding=8)

        # 現在の設定を読み込み
        self._settings, self._transcriber_settings, self._aws_settings = (
            load_all_settings()
        )

        # tkinter 変数 — LLM バックエンド
        self._backend_var = tk.StringVar(value=self._settings.backend.value)
        self._model_path_var = tk.StringVar(value=self._settings.local_model_path)
        self._api_endpoint_var = tk.StringVar(value=self._settings.api_endpoint)
        self._api_key_var = tk.StringVar(value=self._settings.api_key)
        self._max_tokens_var = tk.IntVar(value=self._settings.max_tokens)
        self._temperature_var = tk.DoubleVar(value=self._settings.temperature)
        self._ctx_size_var = tk.IntVar(value=self._settings.ctx_size)
        self._timeout_var = tk.IntVar(value=self._settings.timeout_seconds)
        self._bedrock_model_var = tk.StringVar(
            value=self._settings.bedrock_model_id
        )

        # tkinter 変数 — 文字起こしバックエンド
        self._transcriber_backend_var = tk.StringVar(
            value=self._transcriber_settings.backend.value
        )
        self._whisper_model_size_var = tk.StringVar(
            value=self._transcriber_settings.whisper_model_size
        )
        self._vllm_endpoint_var = tk.StringVar(
            value=self._transcriber_settings.vllm_endpoint
        )
        self._vllm_model_name_var = tk.StringVar(
            value=self._transcriber_settings.vllm_model_name
        )
        self._aws_transcribe_lang_var = tk.StringVar(
            value=self._transcriber_settings.aws_transcribe_language
        )
        self._aws_s3_bucket_var = tk.StringVar(
            value=self._transcriber_settings.aws_s3_bucket
        )

        # tkinter 変数 — AWS 設定
        self._aws_auth_method_var = tk.StringVar(
            value=self._aws_settings.auth_method.value
        )
        self._aws_region_var = tk.StringVar(value=self._aws_settings.region)
        self._aws_profile_var = tk.StringVar(value=self._aws_settings.profile_name)
        self._aws_access_key_var = tk.StringVar(
            value=self._aws_settings.access_key_id
        )
        self._aws_secret_key_var = tk.StringVar(
            value=self._aws_settings.secret_access_key
        )
        self._aws_session_token_var = tk.StringVar(
            value=self._aws_settings.session_token
        )

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """UI コンポーネントを構築・配置する."""
        # スクロール可能なキャンバス
        canvas = tk.Canvas(self.frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            self.frame, orient=tk.VERTICAL, command=canvas.yview
        )
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

        self._build_transcriber_section(parent)
        self._build_llm_backend_section(parent)
        self._build_aws_section(parent)
        self._build_params_section(parent)
        self._build_prompt_section(parent)
        self._build_buttons(parent)

        # 初期表示の切り替え
        self._on_backend_changed()
        self._on_transcriber_backend_changed()
        self._on_aws_auth_changed()

    def _build_transcriber_section(self, parent: ttk.Frame) -> None:
        """文字起こしバックエンド設定セクションを構築する."""
        frame = ttk.LabelFrame(parent, text="文字起こしバックエンド", padding=6)
        frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Radiobutton(
            frame,
            text="ローカル（faster-whisper）",
            variable=self._transcriber_backend_var,
            value=TranscriberBackend.LOCAL.value,
            command=self._on_transcriber_backend_changed,
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            frame,
            text="vLLM（OpenAI 互換 API）",
            variable=self._transcriber_backend_var,
            value=TranscriberBackend.VLLM.value,
            command=self._on_transcriber_backend_changed,
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            frame,
            text="Amazon Transcribe",
            variable=self._transcriber_backend_var,
            value=TranscriberBackend.AWS_TRANSCRIBE.value,
            command=self._on_transcriber_backend_changed,
        ).pack(anchor=tk.W)

        # --- ローカル Whisper 設定 ---
        self._whisper_frame = ttk.LabelFrame(
            parent, text="ローカル Whisper 設定", padding=6
        )
        self._whisper_frame.pack(fill=tk.X, pady=(0, 8))

        whisper_row = ttk.Frame(self._whisper_frame)
        whisper_row.pack(fill=tk.X)
        ttk.Label(whisper_row, text="モデルサイズ:").pack(
            side=tk.LEFT, padx=(0, 6)
        )
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
            self._whisper_frame,
            text="※ large: 高精度（約3GB）、small: 軽量（約500MB）\n"
            "※ 変更は次回の文字起こし時に反映されます",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(4, 0))

        # --- vLLM 設定 ---
        self._vllm_frame = ttk.LabelFrame(
            parent, text="vLLM 設定", padding=6
        )
        self._vllm_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(self._vllm_frame, text="エンドポイント URL:").pack(anchor=tk.W)
        ttk.Entry(
            self._vllm_frame, textvariable=self._vllm_endpoint_var, width=60
        ).pack(fill=tk.X, pady=(0, 4))
        ttk.Label(
            self._vllm_frame,
            text="例: http://your-server:8000/v1/audio/transcriptions",
            foreground="gray",
        ).pack(anchor=tk.W)

        vllm_model_row = ttk.Frame(self._vllm_frame)
        vllm_model_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(vllm_model_row, text="モデル名:").pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Entry(
            vllm_model_row, textvariable=self._vllm_model_name_var, width=30
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # --- Amazon Transcribe 設定 ---
        self._aws_transcribe_frame = ttk.LabelFrame(
            parent, text="Amazon Transcribe 設定", padding=6
        )
        self._aws_transcribe_frame.pack(fill=tk.X, pady=(0, 8))

        lang_row = ttk.Frame(self._aws_transcribe_frame)
        lang_row.pack(fill=tk.X)
        ttk.Label(lang_row, text="言語コード:").pack(side=tk.LEFT, padx=(0, 6))
        _TRANSCRIBE_LANGUAGES = ["ja-JP", "en-US", "zh-CN", "ko-KR"]
        ttk.Combobox(
            lang_row,
            textvariable=self._aws_transcribe_lang_var,
            values=_TRANSCRIBE_LANGUAGES,
            width=10,
        ).pack(side=tk.LEFT)
        ttk.Label(
            self._aws_transcribe_frame,
            text="※ AWS 設定セクションで認証情報を設定してください",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(4, 0))

        # S3 バケット名
        s3_row = ttk.Frame(self._aws_transcribe_frame)
        s3_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(s3_row, text="S3 バケット名:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Entry(
            s3_row, textvariable=self._aws_s3_bucket_var, width=40
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(
            self._aws_transcribe_frame,
            text="※ 音声ファイルのアップロード先。CloudFormation Output の TranscribeBucketName を入力",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(2, 0))

    def _build_llm_backend_section(self, parent: ttk.Frame) -> None:
        """LLM 推論バックエンド設定セクションを構築する."""
        # --- バックエンド選択 ---
        backend_frame = ttk.LabelFrame(
            parent, text="LLM 推論バックエンド", padding=6
        )
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
        ttk.Radiobutton(
            backend_frame,
            text="Amazon Bedrock",
            variable=self._backend_var,
            value=LlmBackend.AWS_BEDROCK.value,
            command=self._on_backend_changed,
        ).pack(anchor=tk.W)

        # --- ローカルモデル設定 ---
        self._local_frame = ttk.LabelFrame(
            parent, text="ローカルモデル設定", padding=6
        )
        self._local_frame.pack(fill=tk.X, pady=(0, 8))

        path_row = ttk.Frame(self._local_frame)
        path_row.pack(fill=tk.X)
        ttk.Label(path_row, text="モデルファイル（GGUF）:").pack(anchor=tk.W)
        entry_row = ttk.Frame(path_row)
        entry_row.pack(fill=tk.X)
        self._model_path_entry = ttk.Entry(
            entry_row, textvariable=self._model_path_var, width=50
        )
        self._model_path_entry.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4)
        )
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
        self._model_combo.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4)
        )
        self._download_btn = ttk.Button(
            dl_row, text="ダウンロード", command=self._on_download_model, width=14
        )
        self._download_btn.pack(side=tk.LEFT)

        self._dl_progress_var = tk.StringVar(value="")
        self._dl_progress_label = ttk.Label(
            dl_frame, textvariable=self._dl_progress_var, foreground="blue"
        )
        self._dl_progress_label.pack(anchor=tk.W, pady=(2, 0))

        # llama-server ダウンロードセクション
        server_frame = ttk.Frame(self._local_frame)
        server_frame.pack(fill=tk.X, pady=(8, 0))

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
            server_frame,
            textvariable=self._server_status_var,
            foreground=server_color,
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
            server_frame,
            textvariable=self._server_dl_progress_var,
            foreground="blue",
        )
        self._server_dl_progress_label.pack(anchor=tk.W, pady=(2, 0))

        # --- API 設定 ---
        self._api_frame = ttk.LabelFrame(
            parent, text="オンプレ API 設定", padding=6
        )
        self._api_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(self._api_frame, text="エンドポイント URL:").pack(anchor=tk.W)
        ttk.Entry(
            self._api_frame, textvariable=self._api_endpoint_var, width=60
        ).pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self._api_frame, text="API キー（オプション）:").pack(
            anchor=tk.W
        )
        ttk.Entry(
            self._api_frame, textvariable=self._api_key_var, show="*", width=60
        ).pack(fill=tk.X)

        # --- Bedrock 設定 ---
        self._bedrock_frame = ttk.LabelFrame(
            parent, text="Amazon Bedrock 設定", padding=6
        )
        self._bedrock_frame.pack(fill=tk.X, pady=(0, 8))

        bedrock_row = ttk.Frame(self._bedrock_frame)
        bedrock_row.pack(fill=tk.X)
        ttk.Label(bedrock_row, text="モデル ID:").pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self._bedrock_model_combo = ttk.Combobox(
            bedrock_row,
            textvariable=self._bedrock_model_var,
            values=_BEDROCK_MODELS,
            width=45,
        )
        self._bedrock_model_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(
            self._bedrock_frame,
            text="※ AWS 設定セクションで認証情報を設定してください\n"
            "※ モデル ID は手入力も可能です（カスタムモデル等）",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(4, 0))

    def _build_aws_section(self, parent: ttk.Frame) -> None:
        """AWS 接続設定セクションを構築する."""
        aws_frame = ttk.LabelFrame(parent, text="AWS 接続設定", padding=6)
        aws_frame.pack(fill=tk.X, pady=(0, 8))

        # 認証方式選択
        auth_row = ttk.Frame(aws_frame)
        auth_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(auth_row, text="認証方式:").pack(anchor=tk.W)
        ttk.Radiobutton(
            auth_row,
            text="プロファイル / 環境変数 / IAM ロール（boto3 デフォルト）",
            variable=self._aws_auth_method_var,
            value=AwsAuthMethod.PROFILE.value,
            command=self._on_aws_auth_changed,
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            auth_row,
            text="アクセスキー直接入力",
            variable=self._aws_auth_method_var,
            value=AwsAuthMethod.ACCESS_KEY.value,
            command=self._on_aws_auth_changed,
        ).pack(anchor=tk.W)

        # リージョン
        region_row = ttk.Frame(aws_frame)
        region_row.pack(fill=tk.X, pady=(4, 4))
        ttk.Label(region_row, text="リージョン:").pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Combobox(
            region_row,
            textvariable=self._aws_region_var,
            values=_AWS_REGIONS,
            width=18,
        ).pack(side=tk.LEFT)

        # プロファイル名
        self._aws_profile_frame = ttk.Frame(aws_frame)
        self._aws_profile_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self._aws_profile_frame, text="プロファイル名（空欄=default）:").pack(
            anchor=tk.W
        )
        ttk.Entry(
            self._aws_profile_frame, textvariable=self._aws_profile_var, width=30
        ).pack(fill=tk.X)

        # アクセスキー入力
        self._aws_key_frame = ttk.Frame(aws_frame)
        self._aws_key_frame.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(self._aws_key_frame, text="アクセスキー ID:").pack(
            anchor=tk.W
        )
        ttk.Entry(
            self._aws_key_frame, textvariable=self._aws_access_key_var, width=40
        ).pack(fill=tk.X, pady=(0, 4))

        ttk.Label(self._aws_key_frame, text="シークレットアクセスキー:").pack(
            anchor=tk.W
        )
        ttk.Entry(
            self._aws_key_frame,
            textvariable=self._aws_secret_key_var,
            show="*",
            width=40,
        ).pack(fill=tk.X, pady=(0, 4))

        ttk.Label(
            self._aws_key_frame, text="セッショントークン（オプション）:"
        ).pack(anchor=tk.W)
        ttk.Entry(
            self._aws_key_frame,
            textvariable=self._aws_session_token_var,
            show="*",
            width=40,
        ).pack(fill=tk.X)

        ttk.Label(
            aws_frame,
            text="※ Bedrock / Transcribe の両方でこの設定が使用されます",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(4, 0))

    def _build_params_section(self, parent: ttk.Frame) -> None:
        """生成パラメータセクションを構築する."""
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
        ttk.Label(row3, text="コンテキストサイズ:").pack(
            side=tk.LEFT, padx=(0, 6)
        )
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
            text="（ローカルモード用。大きいほどメモリ使用量増）",
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
            row4, text="秒", foreground="gray"
        ).pack(side=tk.LEFT, padx=(6, 0))

    def _build_prompt_section(self, parent: ttk.Frame) -> None:
        """プロンプトテンプレートセクションを構築する."""
        prompt_frame = ttk.LabelFrame(
            parent, text="プロンプトテンプレート", padding=6
        )
        prompt_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        ttk.Label(
            prompt_frame,
            text="※ {text} がテキストに置換されます",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(0, 4))

        ttk.Label(prompt_frame, text="テキスト修正:").pack(anchor=tk.W)
        self._prompt_fix = tk.Text(prompt_frame, height=4, wrap=tk.WORD)
        self._prompt_fix.pack(fill=tk.X, pady=(0, 6))
        self._prompt_fix.insert("1.0", self._settings.prompt_fix_text)

        ttk.Label(prompt_frame, text="要約生成:").pack(anchor=tk.W)
        self._prompt_summarize = tk.Text(prompt_frame, height=4, wrap=tk.WORD)
        self._prompt_summarize.pack(fill=tk.X, pady=(0, 6))
        self._prompt_summarize.insert("1.0", self._settings.prompt_summarize)

        ttk.Label(prompt_frame, text="テーマ生成:").pack(anchor=tk.W)
        self._prompt_theme = tk.Text(prompt_frame, height=4, wrap=tk.WORD)
        self._prompt_theme.pack(fill=tk.X, pady=(0, 6))
        self._prompt_theme.insert("1.0", self._settings.prompt_theme)

    def _build_buttons(self, parent: ttk.Frame) -> None:
        """ボタンセクションを構築する."""
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

        self._test_result_var = tk.StringVar(value="")
        self._test_result_label = ttk.Label(
            parent, textvariable=self._test_result_var
        )
        self._test_result_label.pack(anchor=tk.W, pady=(0, 8))

    # ------------------------------------------------------------------
    # イベントハンドラ
    # ------------------------------------------------------------------

    def _on_transcriber_backend_changed(self) -> None:
        """文字起こしバックエンド選択変更時に表示を切り替える."""
        backend = self._transcriber_backend_var.get()
        if backend == TranscriberBackend.LOCAL.value:
            self._set_frame_state(self._whisper_frame, tk.NORMAL)
            self._set_frame_state(self._vllm_frame, tk.DISABLED)
            self._set_frame_state(self._aws_transcribe_frame, tk.DISABLED)
        elif backend == TranscriberBackend.VLLM.value:
            self._set_frame_state(self._whisper_frame, tk.DISABLED)
            self._set_frame_state(self._vllm_frame, tk.NORMAL)
            self._set_frame_state(self._aws_transcribe_frame, tk.DISABLED)
        elif backend == TranscriberBackend.AWS_TRANSCRIBE.value:
            self._set_frame_state(self._whisper_frame, tk.DISABLED)
            self._set_frame_state(self._vllm_frame, tk.DISABLED)
            self._set_frame_state(self._aws_transcribe_frame, tk.NORMAL)

    def _on_backend_changed(self) -> None:
        """LLM バックエンド選択変更時に表示を切り替える."""
        backend = self._backend_var.get()
        if backend == LlmBackend.LOCAL.value:
            self._set_frame_state(self._local_frame, tk.NORMAL)
            self._set_frame_state(self._api_frame, tk.DISABLED)
            self._set_frame_state(self._bedrock_frame, tk.DISABLED)
        elif backend == LlmBackend.API.value:
            self._set_frame_state(self._local_frame, tk.DISABLED)
            self._set_frame_state(self._api_frame, tk.NORMAL)
            self._set_frame_state(self._bedrock_frame, tk.DISABLED)
        elif backend == LlmBackend.AWS_BEDROCK.value:
            self._set_frame_state(self._local_frame, tk.DISABLED)
            self._set_frame_state(self._api_frame, tk.DISABLED)
            self._set_frame_state(self._bedrock_frame, tk.NORMAL)

    def _on_aws_auth_changed(self) -> None:
        """AWS 認証方式変更時に表示を切り替える."""
        auth = self._aws_auth_method_var.get()
        if auth == AwsAuthMethod.PROFILE.value:
            self._set_frame_state(self._aws_profile_frame, tk.NORMAL)
            self._set_frame_state(self._aws_key_frame, tk.DISABLED)
        else:
            self._set_frame_state(self._aws_profile_frame, tk.DISABLED)
            self._set_frame_state(self._aws_key_frame, tk.NORMAL)

    def _browse_model(self) -> None:
        """モデルファイル選択ダイアログを表示する."""
        path = filedialog.askopenfilename(
            title="GGUF モデルファイルを選択",
            filetypes=[("GGUF files", "*.gguf"), ("All files", "*.*")],
        )
        if path:
            self._model_path_var.set(path)

    def _on_save(self) -> None:
        """全設定を保存する."""
        llm_settings = self._collect_llm_settings()
        transcriber_settings = self._collect_transcriber_settings()
        aws_settings = self._collect_aws_settings()
        try:
            save_all_settings(llm_settings, transcriber_settings, aws_settings)
            self._settings = llm_settings
            self._transcriber_settings = transcriber_settings
            self._aws_settings = aws_settings
            messagebox.showinfo("設定保存", "設定を保存しました。")
            if self._on_settings_changed is not None:
                self._on_settings_changed(llm_settings, aws_settings)
        except Exception as exc:
            logger.exception("設定の保存に失敗しました。")
            messagebox.showerror("保存エラー", f"設定の保存に失敗しました:\n{exc}")

    def _on_test_connection(self) -> None:
        """現在の設定で LLM 接続テストを実行する."""
        self._test_result_var.set("テスト中...")
        self._test_result_label.configure(foreground="blue")

        llm_settings = self._collect_llm_settings()
        aws_settings = self._collect_aws_settings()

        def _worker():
            try:
                from screen_audio_recorder.llm_client import LlmClient

                client = LlmClient(llm_settings, aws_settings)
                if not client.available:
                    _show_result(
                        "✗ LLM が利用不可です。設定を確認してください。", "red"
                    )
                    return

                result = client.generate("「テスト」と一言だけ返してください。")
                if result:
                    _show_result(
                        f"✓ 接続成功！応答: {result[:50]}", "green"
                    )
                else:
                    _show_result(
                        "✗ 応答が空です。モデルまたはAPIを確認してください。",
                        "red",
                    )
            except Exception as exc:
                _show_result(f"✗ エラー: {exc}", "red")

        def _show_result(text: str, color: str):
            self.frame.after(
                0,
                lambda: (
                    self._test_result_var.set(text),
                    self._test_result_label.configure(foreground=color),
                ),
            )

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

                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=300) as resp:
                    total = int(resp.headers.get("Content-Length", 0))
                    downloaded = 0
                    chunk_size = 1024 * 1024

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

                tmp_path.rename(dest_path)
                self.frame.after(
                    0, lambda: self._model_path_var.set(str(dest_path))
                )
                _update_progress(f"✓ ダウンロード完了: {filename}")
                self.frame.after(
                    0,
                    lambda: self._dl_progress_label.configure(foreground="green"),
                )
            except Exception as exc:
                logger.exception("モデルのダウンロードに失敗しました。")
                _update_progress(f"✗ ダウンロード失敗: {exc}")
                self.frame.after(
                    0,
                    lambda: self._dl_progress_label.configure(foreground="red"),
                )
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
            self._server_dl_progress_var.set(
                "✓ llama-server は既にインストール済みです。"
            )
            self._server_dl_progress_label.configure(foreground="green")
            return

        self._dl_server_btn.configure(state=tk.DISABLED)
        self._server_dl_progress_var.set("ダウンロード中...")
        self._server_dl_progress_label.configure(foreground="blue")

        def _worker():
            try:
                from scripts.download_llama_server import download_to_app_dir

                path = download_to_app_dir()
                self.frame.after(
                    0,
                    lambda: (
                        self._server_dl_progress_var.set(
                            f"✓ ダウンロード完了: {path}"
                        ),
                        self._server_dl_progress_label.configure(
                            foreground="green"
                        ),
                        self._server_status_var.set(
                            f"✓ llama-server 検出済み: {path}"
                        ),
                        self._server_status_label.configure(foreground="green"),
                    ),
                )
            except ImportError:
                try:
                    self._download_server_direct()
                except Exception as exc:
                    self.frame.after(
                        0,
                        lambda: (
                            self._server_dl_progress_var.set(
                                f"✗ ダウンロード失敗: {exc}"
                            ),
                            self._server_dl_progress_label.configure(
                                foreground="red"
                            ),
                        ),
                    )
            except Exception as exc:
                logger.exception("llama-server のダウンロードに失敗しました。")
                self.frame.after(
                    0,
                    lambda: (
                        self._server_dl_progress_var.set(
                            f"✗ ダウンロード失敗: {exc}"
                        ),
                        self._server_dl_progress_label.configure(
                            foreground="red"
                        ),
                    ),
                )
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

        releases_api = (
            "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"
        )
        bin_dir = Path.home() / "Documents" / "screen-audio-recorder" / "bin"
        output_path = bin_dir / "llama-server.exe"

        self.frame.after(
            0,
            lambda: self._server_dl_progress_var.set("リリース情報を取得中..."),
        )
        req = urllib.request.Request(
            releases_api, headers={"User-Agent": "screen-audio-recorder"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        url = None
        for asset in data.get("assets", []):
            name = asset["name"].lower()
            if (
                "win" in name
                and "x64" in name
                and "vulkan" not in name
                and "cuda" not in name
                and name.endswith(".zip")
            ):
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

        self.frame.after(
            0, lambda: self._server_dl_progress_var.set("ダウンロード中...")
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "screen-audio-recorder"}
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            zip_data = resp.read()

        self.frame.after(
            0, lambda: self._server_dl_progress_var.set("展開中...")
        )
        bin_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            server_entry = None
            for name in zf.namelist():
                basename = name.rsplit("/", 1)[-1] if "/" in name else name
                if basename == "llama-server.exe":
                    server_entry = name
                    break
            if server_entry is None:
                raise FileNotFoundError(
                    "zip 内に llama-server.exe が見つかりません"
                )

            server_dir = (
                server_entry.rsplit("/", 1)[0] + "/"
                if "/" in server_entry
                else ""
            )
            for name in zf.namelist():
                if not name.startswith(server_dir):
                    continue
                basename = name[len(server_dir):]
                if not basename or "/" in basename:
                    continue
                target = bin_dir / basename
                with zf.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        self.frame.after(
            0,
            lambda: (
                self._server_dl_progress_var.set(
                    f"✓ ダウンロード完了: {output_path}"
                ),
                self._server_dl_progress_label.configure(foreground="green"),
                self._server_status_var.set(
                    f"✓ llama-server 検出済み: {output_path}"
                ),
                self._server_status_label.configure(foreground="green"),
            ),
        )

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

    def _collect_llm_settings(self) -> LlmSettings:
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
            bedrock_model_id=self._bedrock_model_var.get().strip(),
        )

    def _collect_transcriber_settings(self) -> TranscriberSettings:
        """UI の値から TranscriberSettings を構築する."""
        try:
            backend = TranscriberBackend(self._transcriber_backend_var.get())
        except ValueError:
            backend = TranscriberBackend.LOCAL

        return TranscriberSettings(
            backend=backend,
            whisper_model_size=self._whisper_model_size_var.get(),
            vllm_endpoint=self._vllm_endpoint_var.get().strip(),
            vllm_model_name=self._vllm_model_name_var.get().strip(),
            aws_transcribe_language=self._aws_transcribe_lang_var.get().strip(),
            aws_s3_bucket=self._aws_s3_bucket_var.get().strip(),
        )

    def _collect_aws_settings(self) -> AwsSettings:
        """UI の値から AwsSettings を構築する."""
        try:
            auth_method = AwsAuthMethod(self._aws_auth_method_var.get())
        except ValueError:
            auth_method = AwsAuthMethod.PROFILE

        return AwsSettings(
            auth_method=auth_method,
            region=self._aws_region_var.get().strip(),
            profile_name=self._aws_profile_var.get().strip(),
            access_key_id=self._aws_access_key_var.get().strip(),
            secret_access_key=self._aws_secret_key_var.get().strip(),
            session_token=self._aws_session_token_var.get().strip(),
        )

    @staticmethod
    def _set_frame_state(frame: tk.Widget, state: str) -> None:
        """フレーム内の全ウィジェットの状態を変更する."""
        for child in frame.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass
            if hasattr(child, "winfo_children"):
                for grandchild in child.winfo_children():
                    try:
                        grandchild.configure(state=state)
                    except tk.TclError:
                        pass
