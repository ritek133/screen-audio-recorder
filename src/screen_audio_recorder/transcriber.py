"""Transcriber: 音声ファイルの文字起こしを担当するクラス.

``faster-whisper`` の ``WhisperModel`` を使用して日本語音声をテキストに変換する。
また、vLLM (OpenAI 互換 API) や Amazon Transcribe による外部文字起こしにも対応する。
モデルファイルは ``~/.screen-audio-recorder/models/`` にキャッシュする。
推論は別スレッドで実行し、完了後に ``root.after_idle()`` で GUI スレッドに通知する。

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from screen_audio_recorder.models import (
    AwsSettings,
    TranscriberBackend,
    TranscriberSettings,
    TranscribeResult,
)

if TYPE_CHECKING:
    pass

# faster-whisper は try/except でインポートし、利用不可の場合は None にフォールバック
try:
    from faster_whisper import WhisperModel as _WhisperModel

    _FASTER_WHISPER_AVAILABLE = True
except ImportError:
    _WhisperModel = None  # type: ignore[assignment,misc]
    _FASTER_WHISPER_AVAILABLE = False

# boto3 は try/except でインポート（AWS 利用時のみ必要）
try:
    import boto3

    _BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None  # type: ignore[assignment]
    _BOTO3_AVAILABLE = False

logger = logging.getLogger("screen_audio_recorder")

# モデルキャッシュディレクトリ（ホームディレクトリ相対）
_MODEL_CACHE_DIR = Path.home() / "Documents" / "screen-audio-recorder" / "models"

# 文字起こし対象言語
_LANGUAGE = "ja"


class Transcriber:
    """音声ファイルの文字起こしを担当するクラス.

    ``faster-whisper`` の ``WhisperModel`` を使用して日本語音声をテキストに変換する。
    モデルファイルは初回起動時に ``~/.screen-audio-recorder/models/`` にダウンロード・キャッシュする。
    推論は別スレッドで実行し、完了後に ``root.after_idle()`` で GUI スレッドに通知する。

    モデルダウンロード失敗時は ``ErrorNotifier.show_error()`` を呼び出し、
    文字起こし機能を無効化する（``_enabled`` フラグを ``False`` に設定）。

    文字起こし失敗時は ``ErrorNotifier.show_error()`` を呼び出し、
    空テキストで ``MemoStore.create()`` を呼ぶ。

    Attributes:
        _model: ロード済みの WhisperModel インスタンス。利用不可の場合は None。
        _enabled: 文字起こし機能が有効かどうか。
        _error_notifier: エラー通知オブジェクト。
        _memo_store: メモ保存オブジェクト。
        _root: tkinter ルートウィンドウ。None の場合は直接 callback を呼ぶ。
    """

    def __init__(
        self,
        model_size: str = "large",
        error_notifier=None,
        memo_store=None,
        lazy_load: bool = False,
        transcriber_settings: TranscriberSettings | None = None,
        aws_settings: AwsSettings | None = None,
    ) -> None:
        """Transcriber を初期化し、設定に応じたバックエンドを準備する.

        Args:
            model_size: Whisper モデルサイズ（デフォルト: "large"）。
                TranscriberSettings が指定された場合はそちらが優先される。
            error_notifier: エラー通知オブジェクト（``ErrorNotifier`` インスタンス）。
            memo_store: メモ保存オブジェクト（``MemoStore`` インスタンス）。
            lazy_load: True の場合、ローカルモデルのロードを遅延させる。
            transcriber_settings: 文字起こし設定。None の場合はローカル（faster-whisper）。
            aws_settings: AWS 接続設定。Amazon Transcribe バックエンド使用時に必要。
        """
        self._transcriber_settings = transcriber_settings or TranscriberSettings()
        self._aws_settings = aws_settings or AwsSettings()
        self._model_size = self._transcriber_settings.whisper_model_size or model_size
        self._error_notifier = error_notifier
        self._memo_store = memo_store
        self._model = None
        self._enabled = False

        backend = self._transcriber_settings.backend

        if backend == TranscriberBackend.LOCAL:
            self._init_local(lazy_load)
        elif backend == TranscriberBackend.VLLM:
            self._init_vllm()
        elif backend == TranscriberBackend.AWS_TRANSCRIBE:
            self._init_aws_transcribe()

    def _init_local(self, lazy_load: bool) -> None:
        """ローカル faster-whisper バックエンドを初期化する."""
        if not _FASTER_WHISPER_AVAILABLE:
            logger.warning("faster-whisper が利用不可のため、文字起こし機能を無効化します。")
            if self._error_notifier is not None:
                self._error_notifier.show_error(
                    "文字起こし機能エラー",
                    "faster-whisper がインストールされていないため、文字起こし機能を利用できません。",
                )
            return

        # モデルキャッシュディレクトリを作成
        _MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        if lazy_load:
            return

        self._load_model()

    def _init_vllm(self) -> None:
        """vLLM バックエンドを初期化する."""
        endpoint = self._transcriber_settings.vllm_endpoint
        if not endpoint:
            logger.warning("vLLM エンドポイントが設定されていません。文字起こし機能を無効化します。")
            if self._error_notifier is not None:
                self._error_notifier.show_error(
                    "文字起こし設定エラー",
                    "vLLM エンドポイント URL が設定されていません。",
                )
            return

        self._enabled = True
        logger.info("vLLM バックエンドで初期化しました。エンドポイント: %s", endpoint)

    def _init_aws_transcribe(self) -> None:
        """Amazon Transcribe バックエンドを初期化する."""
        if not _BOTO3_AVAILABLE:
            logger.warning("boto3 が利用不可のため、Amazon Transcribe を使用できません。")
            if self._error_notifier is not None:
                self._error_notifier.show_error(
                    "文字起こし設定エラー",
                    "boto3 がインストールされていないため、Amazon Transcribe を利用できません。\n"
                    "pip install boto3 を実行してください。",
                )
            return

        self._enabled = True
        logger.info(
            "Amazon Transcribe バックエンドで初期化しました。リージョン: %s",
            self._aws_settings.region,
        )

    @property
    def enabled(self) -> bool:
        """文字起こし機能が有効かどうかを返す."""
        return self._enabled

    def _load_model(self) -> None:
        """Whisper モデルを同期的にロードする."""
        try:
            logger.info(
                "Whisper モデル '%s' をロード中（キャッシュ: %s）...",
                self._model_size,
                _MODEL_CACHE_DIR,
            )
            self._model = _WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",
                download_root=str(_MODEL_CACHE_DIR),
            )
            self._enabled = True
            logger.info("Whisper モデル '%s' のロードが完了しました。", self._model_size)
        except Exception as exc:
            logger.error("Whisper モデルのロードに失敗しました: %s", exc)
            if self._error_notifier is not None:
                self._error_notifier.show_error(
                    "モデルロードエラー",
                    f"Whisper モデルのダウンロード・ロードに失敗しました。\n"
                    f"文字起こし機能を無効化します。\n詳細: {exc}",
                )

    def load_model_async(self, callback=None, root=None) -> None:
        """バックグラウンドスレッドで Whisper モデルをロードする.

        Args:
            callback: ロード完了時に呼ばれるコールバック（引数なし）。
            root: tkinter ルートウィンドウ。指定時は after_idle で callback を呼ぶ。
        """
        if self._enabled:
            # 既にロード済み
            if callback:
                if root:
                    root.after_idle(callback)
                else:
                    callback()
            return

        def _worker():
            self._load_model()
            if callback:
                if root:
                    root.after_idle(callback)
                else:
                    callback()

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def transcribe(self, audio_path: Path) -> TranscribeResult:
        """音声ファイルを文字起こしする（同期）.

        設定されたバックエンドに応じて適切な方法で文字起こしを実行する。

        Args:
            audio_path: 文字起こし対象の音声ファイルパス。

        Returns:
            文字起こし結果を含む ``TranscribeResult`` オブジェクト。
            失敗時は ``text=""``、``error`` にエラーメッセージが設定される。
        """
        if not self._enabled:
            error_msg = "文字起こし機能が無効化されています。"
            logger.warning(error_msg)
            return TranscribeResult(
                text="",
                language=_LANGUAGE,
                duration_seconds=0.0,
                error=error_msg,
            )

        backend = self._transcriber_settings.backend

        if backend == TranscriberBackend.LOCAL:
            return self._transcribe_local(audio_path)
        elif backend == TranscriberBackend.VLLM:
            return self._transcribe_vllm(audio_path)
        elif backend == TranscriberBackend.AWS_TRANSCRIBE:
            return self._transcribe_aws(audio_path)
        else:
            error_msg = f"未知の文字起こしバックエンド: {backend}"
            logger.error(error_msg)
            return TranscribeResult(
                text="",
                language=_LANGUAGE,
                duration_seconds=0.0,
                error=error_msg,
            )

    def _transcribe_local(self, audio_path: Path) -> TranscribeResult:
        """ローカル faster-whisper で文字起こしする."""
        if self._model is None:
            error_msg = "Whisper モデルがロードされていません。"
            logger.warning(error_msg)
            return TranscribeResult(
                text="",
                language=_LANGUAGE,
                duration_seconds=0.0,
                error=error_msg,
            )

        try:
            logger.info("文字起こし開始（ローカル）: %s", audio_path)
            segments, info = self._model.transcribe(
                str(audio_path),
                language=_LANGUAGE,
            )
            text = "".join(segment.text for segment in segments)
            duration = info.duration if hasattr(info, "duration") else 0.0
            logger.info("文字起こし完了: %d 文字", len(text))
            return TranscribeResult(
                text=text,
                language=_LANGUAGE,
                duration_seconds=duration,
                error=None,
            )
        except Exception as exc:
            return self._handle_transcribe_error(exc, audio_path)

    def _transcribe_vllm(self, audio_path: Path) -> TranscribeResult:
        """vLLM OpenAI 互換 API で文字起こしする.

        /v1/audio/transcriptions エンドポイントに multipart/form-data で
        音声ファイルを送信する。
        """
        endpoint = self._transcriber_settings.vllm_endpoint
        model_name = self._transcriber_settings.vllm_model_name

        try:
            logger.info("文字起こし開始（vLLM）: %s → %s", audio_path, endpoint)

            # multipart/form-data の構築
            import mimetypes
            import uuid

            boundary = uuid.uuid4().hex
            content_type = f"multipart/form-data; boundary={boundary}"

            # 音声ファイル読み込み
            audio_data = audio_path.read_bytes()
            mime_type = mimetypes.guess_type(str(audio_path))[0] or "audio/wav"

            # フォームデータの構築
            parts = []
            # file フィールド
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            )
            parts.append(audio_data)
            parts.append(b"\r\n")
            # model フィールド
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="model"\r\n\r\n'
                f"{model_name}\r\n"
            )
            # language フィールド
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="language"\r\n\r\n'
                f"{_LANGUAGE}\r\n"
            )
            parts.append(f"--{boundary}--\r\n")

            # バイト列に変換
            body = b""
            for part in parts:
                if isinstance(part, str):
                    body += part.encode("utf-8")
                else:
                    body += part

            req = urllib.request.Request(
                endpoint,
                data=body,
                headers={"Content-Type": content_type},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=600) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            text = result.get("text", "")
            duration = result.get("duration", 0.0)
            logger.info("文字起こし完了（vLLM）: %d 文字", len(text))
            return TranscribeResult(
                text=text,
                language=_LANGUAGE,
                duration_seconds=duration,
                error=None,
            )
        except Exception as exc:
            return self._handle_transcribe_error(exc, audio_path)

    def _transcribe_aws(self, audio_path: Path) -> TranscribeResult:
        """Amazon Transcribe バッチジョブで文字起こしする.

        音声ファイルを S3 にアップロードし、StartTranscriptionJob で処理する。
        ジョブ完了後に結果を取得し、S3 の一時ファイルを削除する。
        """
        try:
            logger.info("文字起こし開始（Amazon Transcribe バッチ）: %s", audio_path)

            # ファイル形式の判定
            suffix = audio_path.suffix.lower()
            media_format_map = {
                ".wav": "wav",
                ".mp3": "mp3",
                ".flac": "flac",
                ".ogg": "ogg",
                ".m4a": "mp4",
                ".mp4": "mp4",
            }
            media_format = media_format_map.get(suffix, "wav")
            language_code = self._transcriber_settings.aws_transcribe_language

            text = self._transcribe_batch(audio_path, language_code, media_format)

            logger.info("文字起こし完了（Amazon Transcribe）: %d 文字", len(text))
            return TranscribeResult(
                text=text,
                language=_LANGUAGE,
                duration_seconds=0.0,
                error=None,
            )
        except Exception as exc:
            return self._handle_transcribe_error(exc, audio_path)

    def _transcribe_batch(
        self, audio_path: Path, language_code: str, media_format: str
    ) -> str:
        """S3 経由の Transcribe バッチジョブで文字起こしする."""
        import os
        import uuid

        from screen_audio_recorder.aws_utils import create_boto3_client

        # S3 バケット名を取得
        s3_bucket = self._transcriber_settings.aws_s3_bucket or os.environ.get(
            "SCREEN_RECORDER_S3_BUCKET", ""
        )
        if not s3_bucket:
            raise RuntimeError(
                "Amazon Transcribe のバッチ処理には S3 バケットが必要です。\n"
                "設定画面で S3 バケット名を入力するか、\n"
                "環境変数 SCREEN_RECORDER_S3_BUCKET を設定してください。"
            )

        transcribe_client = create_boto3_client("transcribe", self._aws_settings)
        s3_client = create_boto3_client("s3", self._aws_settings)

        # 一時ファイルを S3 にアップロード
        job_name = f"screen-recorder-{uuid.uuid4().hex[:8]}-{int(time.time())}"
        s3_key = f"screen-audio-recorder/tmp/{job_name}.{media_format}"
        s3_uri = f"s3://{s3_bucket}/{s3_key}"

        try:
            audio_data = audio_path.read_bytes()
            s3_client.put_object(Bucket=s3_bucket, Key=s3_key, Body=audio_data)

            # Transcribe ジョブ開始
            transcribe_client.start_transcription_job(
                TranscriptionJobName=job_name,
                LanguageCode=language_code,
                MediaFormat=media_format,
                Media={"MediaFileUri": s3_uri},
            )

            # ジョブ完了を待つ（ポーリング）
            while True:
                status = transcribe_client.get_transcription_job(
                    TranscriptionJobName=job_name
                )
                job_status = status["TranscriptionJob"]["TranscriptionJobStatus"]
                if job_status == "COMPLETED":
                    break
                elif job_status == "FAILED":
                    reason = status["TranscriptionJob"].get("FailureReason", "不明")
                    raise RuntimeError(f"Transcribe ジョブが失敗しました: {reason}")
                time.sleep(2)

            # 結果を取得
            transcript_uri = status["TranscriptionJob"]["Transcript"][
                "TranscriptFileUri"
            ]
            req = urllib.request.Request(transcript_uri, method="GET")
            # Transcribe が返す署名付き S3 URL のダウンロード
            # セキュリティソフトによる証明書問題を回避するため SSL 検証をスキップ
            # （URL 自体が AWS 署名付きで改ざん不可）
            import ssl
            ssl_context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            transcripts = result.get("results", {}).get("transcripts", [])
            text = " ".join(t.get("transcript", "") for t in transcripts)
            return text

        finally:
            # S3 の一時ファイルを削除
            try:
                s3_client.delete_object(Bucket=s3_bucket, Key=s3_key)
            except Exception:
                pass
            # Transcribe ジョブを削除
            try:
                transcribe_client.delete_transcription_job(
                    TranscriptionJobName=job_name
                )
            except Exception:
                pass

    def _handle_transcribe_error(self, exc: Exception, audio_path: Path) -> TranscribeResult:
        """文字起こしエラーを共通処理する."""
        error_msg = f"文字起こし処理に失敗しました: {exc}"
        logger.error(error_msg)
        if self._error_notifier is not None:
            self._error_notifier.show_error(
                "文字起こしエラー",
                f"音声の文字起こしに失敗しました。\n詳細: {exc}",
            )
        if self._memo_store is not None:
            self._memo_store.create("", "無題", audio_path)
        return TranscribeResult(
            text="",
            language=_LANGUAGE,
            duration_seconds=0.0,
            error=error_msg,
        )

    def transcribe_async(
        self,
        audio_path: Path,
        callback: Callable[[TranscribeResult], None],
        root=None,
    ) -> None:
        """非同期で文字起こしを実行し、完了時に callback を呼ぶ.

        推論は別スレッドで実行する。完了後、``root`` が指定されている場合は
        ``root.after_idle()`` で GUI スレッドに通知する。
        ``root`` が ``None`` の場合は直接 ``callback`` を呼ぶ。

        Args:
            audio_path: 文字起こし対象の音声ファイルパス。
            callback: 文字起こし完了時に呼ばれるコールバック関数。
                ``TranscribeResult`` を引数として受け取る。
            root: tkinter ルートウィンドウ。None の場合は直接 callback を呼ぶ。

        要件 6.1: OutputFile が生成されたとき、音声をテキストに変換する処理を開始する。
        要件 6.3: 文字起こしが完了したとき、変換結果テキストを MemoStore に渡す。
        """

        def _worker() -> None:
            result = self.transcribe(audio_path)
            if root is not None:
                # GUI スレッドから after_idle() 経由で callback を呼ぶ
                root.after_idle(callback, result)
            else:
                # root が None の場合は直接 callback を呼ぶ
                callback(result)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
