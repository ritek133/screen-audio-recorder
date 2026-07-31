"""コアデータモデル定義."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import numpy as np


@dataclass
class RecordingRegion:
    """録画対象の画面領域を表すデータクラス.

    Attributes:
        x: 左上 X 座標（ピクセル）
        y: 左上 Y 座標（ピクセル）
        width: 幅（ピクセル）、最小 MIN_WIDTH
        height: 高さ（ピクセル）、最小 MIN_HEIGHT
    """

    x: int
    y: int
    width: int
    height: int

    MIN_WIDTH: ClassVar[int] = 320
    MIN_HEIGHT: ClassVar[int] = 240

    def clamp(self, display_width: int, display_height: int) -> "RecordingRegion":
        """最小・最大サイズの範囲内に収める.

        width を [MIN_WIDTH, display_width] の範囲、
        height を [MIN_HEIGHT, display_height] の範囲にクランプする。

        Args:
            display_width: ディスプレイの幅（ピクセル）
            display_height: ディスプレイの高さ（ピクセル）

        Returns:
            クランプ後の新しい RecordingRegion インスタンス
        """
        clamped_width = max(self.MIN_WIDTH, min(self.width, display_width))
        clamped_height = max(self.MIN_HEIGHT, min(self.height, display_height))
        return RecordingRegion(
            x=self.x,
            y=self.y,
            width=clamped_width,
            height=clamped_height,
        )


@dataclass
class AudioChunk:
    """音声データのチャンクを表すデータクラス.

    Attributes:
        data: 音声データ配列 shape: (samples, channels), dtype: float32
        sample_rate: サンプルレート（Hz）、通常 44100
        timestamp: time.perf_counter() 値
    """

    data: np.ndarray
    sample_rate: int
    timestamp: float


@dataclass
class TranscribeResult:
    """文字起こし結果を表すデータクラス.

    Attributes:
        text: 文字起こしテキスト
        language: 言語コード（例: "ja"）
        duration_seconds: 音声の長さ（秒）
        error: 失敗時のエラーメッセージ、成功時は None
    """

    text: str
    language: str
    duration_seconds: float
    error: str | None = None


@dataclass
class Memo:
    """メモを表すデータクラス.

    Attributes:
        id: UUID4 形式のメモ ID
        created_at: 作成日時（UTC）
        theme: メモのテーマ（10 文字以内）
        body: 文字起こし全文（修正済み）
        summary: 内容要約
        output_file: OutputFile への絶対パス
    """

    id: str
    created_at: datetime
    theme: str
    body: str
    summary: str
    output_file: Path


@dataclass
class MemoPage:
    """ページネーション付きメモ一覧を表すデータクラス.

    Attributes:
        memos: 現在ページのメモリスト
        total: 全メモ件数
        page: 現在のページ番号（1 始まり）
        page_size: 1 ページあたりの件数
        total_pages: 総ページ数
    """

    memos: list[Memo]
    total: int
    page: int
    page_size: int
    total_pages: int


class RecordingMode(enum.Enum):
    """録画モードを表す列挙型."""

    SCREEN_AND_AUDIO = "screen_and_audio"
    AUDIO_ONLY = "audio_only"


class TranscriberBackend(enum.Enum):
    """文字起こしバックエンドを表す列挙型."""

    LOCAL = "local"           # faster-whisper（ローカル）
    VLLM = "vllm"            # vLLM OpenAI 互換 API
    AWS_TRANSCRIBE = "aws_transcribe"  # Amazon Transcribe


class LlmBackend(enum.Enum):
    """LLM 推論バックエンドを表す列挙型."""

    LOCAL = "local"
    API = "api"
    AWS_BEDROCK = "aws_bedrock"  # Amazon Bedrock


class AwsAuthMethod(enum.Enum):
    """AWS 認証方式を表す列挙型."""

    PROFILE = "profile"       # boto3 デフォルト（環境変数/プロファイル/IAM ロール）
    ACCESS_KEY = "access_key"  # アクセスキー直接入力


# デフォルトプロンプトテンプレート
DEFAULT_PROMPT_FIX_TEXT = (
    "以下の日本語テキストの句読点を補完し、誤字脱字を修正してください。"
    "意味を変えず、自然な日本語に整えてください。"
    "必ず日本語で出力してください。修正後のテキストのみを出力してください。\n\n{text}"
)

DEFAULT_PROMPT_SUMMARIZE = (
    "以下の日本語テキストの内容を3〜5文で簡潔に要約してください。"
    "必ず日本語で出力してください。英語で出力しないでください。"
    "要約のみを出力してください。\n\n{text}"
)

DEFAULT_PROMPT_THEME = (
    "以下の日本語テキストの内容を表す10文字以内の短いテーマ名を1つ生成してください。"
    "日本語で、テーマ名のみを出力してください。\n\n{text}"
)


@dataclass
class AwsSettings:
    """AWS 接続設定を表すデータクラス.

    Attributes:
        auth_method: 認証方式（プロファイル or アクセスキー）
        region: AWS リージョン
        profile_name: 使用する AWS プロファイル名（auth_method=PROFILE 時）
        access_key_id: アクセスキー ID（auth_method=ACCESS_KEY 時）
        secret_access_key: シークレットアクセスキー（auth_method=ACCESS_KEY 時）
        session_token: セッショントークン（オプション、STS 一時認証用）
    """

    auth_method: AwsAuthMethod = AwsAuthMethod.PROFILE
    region: str = "ap-northeast-1"
    profile_name: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""
    session_token: str = ""


@dataclass
class TranscriberSettings:
    """文字起こし設定を表すデータクラス.

    Attributes:
        backend: 文字起こしバックエンド
        whisper_model_size: ローカル Whisper モデルサイズ（tiny/base/small/medium/large）
        vllm_endpoint: vLLM サーバーの URL（例: http://host:8000/v1/audio/transcriptions）
        vllm_model_name: vLLM サーバーで使用するモデル名
        aws_transcribe_language: Amazon Transcribe の言語コード
    """

    backend: TranscriberBackend = TranscriberBackend.LOCAL
    whisper_model_size: str = "small"
    vllm_endpoint: str = ""
    vllm_model_name: str = "whisper-large-v3"
    aws_transcribe_language: str = "ja-JP"


@dataclass
class LlmSettings:
    """LLM 設定を表すデータクラス.

    Attributes:
        backend: 推論バックエンド（LOCAL / API / AWS_BEDROCK）
        local_model_path: ローカル GGUF モデルのファイルパス
        api_endpoint: OpenAI 互換 API のエンドポイント URL
        api_key: API キー（オプション、空文字列で省略可）
        prompt_fix_text: テキスト修正プロンプトテンプレート（{text} プレースホルダ）
        prompt_summarize: 要約生成プロンプトテンプレート（{text} プレースホルダ）
        prompt_theme: テーマ生成プロンプトテンプレート（{text} プレースホルダ）
        max_tokens: 最大生成トークン数
        temperature: 生成温度
        whisper_model_size: Whisper モデルサイズ（後方互換用、TranscriberSettings に移行予定）
        bedrock_model_id: Bedrock で使用するモデル ID
    """

    backend: LlmBackend = LlmBackend.LOCAL
    local_model_path: str = ""
    api_endpoint: str = "http://localhost:8080/v1/chat/completions"
    api_key: str = ""
    prompt_fix_text: str = DEFAULT_PROMPT_FIX_TEXT
    prompt_summarize: str = DEFAULT_PROMPT_SUMMARIZE
    prompt_theme: str = DEFAULT_PROMPT_THEME
    max_tokens: int = 1024
    temperature: float = 0.3
    ctx_size: int = 8192
    timeout_seconds: int = 600
    whisper_model_size: str = "small"
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"


@dataclass
class PostProcessResult:
    """テキスト後処理結果を表すデータクラス.

    Attributes:
        corrected_text: 句読点・誤字脱字修正済みテキスト
        summary: 内容要約
        theme: 生成されたテーマ（10 文字以内）
        used_llm: LLM を使用したかどうか
    """

    corrected_text: str
    summary: str
    theme: str
    used_llm: bool


@dataclass
class AppSettings:
    """アプリケーション全般の設定を表すデータクラス.

    Attributes:
        verbose_logging: 詳細ログを有効にするかどうか。
            True の場合、ファイル・コンソール共に DEBUG レベルで出力する。
            False の場合、ファイルは INFO、コンソールは WARNING のみ出力する。
    """

    verbose_logging: bool = False
