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
        """Amazon Transcribe で文字起こしする.

        Transcribe Streaming API を使用してリアルタイム文字起こしを行う。
        ストリーミングが利用できない場合は、バッチジョブにフォールバックする。

        注意: Amazon Transcribe Streaming は boto3 の
        transcribe-streaming クライアント (start_stream_transcription) を使用する。
        ここでは簡易版としてバッチ API（start_transcription_job）を使用する。
        音声ファイルをローカルから直接送信するため、一時的に S3 は不要な
        Medical Transcribe の直接入力、または Streaming API を利用する。

        実装方針: Transcribe Streaming API（start_medical_stream_transcription ではなく
        start_stream_transcription）を使用して、ファイルをチャンクで送る。
        """
        try:
            logger.info("文字起こし開始（Amazon Transcribe）: %s", audio_path)

            client = self._get_aws_transcribe_client()
            language_code = self._transcriber_settings.aws_transcribe_language

            # ファイルを読み込み
            audio_data = audio_path.read_bytes()

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

            # Transcribe Streaming API を使用
            text = self._transcribe_aws_streaming(client, audio_data, language_code, media_format)

            logger.info("文字起こし完了（Amazon Transcribe）: %d 文字", len(text))
            return TranscribeResult(
                text=text,
                language=_LANGUAGE,
                duration_seconds=0.0,  # Transcribe はデュレーション情報を別途返さない
                error=None,
            )
        except Exception as exc:
            return self._handle_transcribe_error(exc, audio_path)

    def _get_aws_transcribe_client(self):
        """AWS Transcribe クライアントを取得する."""
        from screen_audio_recorder.aws_utils import create_boto3_client

        return create_boto3_client("transcribe", self._aws_settings)

    def _transcribe_aws_streaming(
        self, client, audio_data: bytes, language_code: str, media_format: str
    ) -> str:
        """Transcribe Streaming API で文字起こしする.

        boto3 の start_stream_transcription を使用する。
        """
        import asyncio

        # Streaming API 用のイベントストリーム
        # boto3 の Transcribe Streaming は特殊な形式のため、
        # ここではバッチ処理のフォールバックとして直接 API を使用する
        # 注: 本番では amazon-transcribe-streaming-sdk の使用を推奨

        # 簡易実装: ファイルを一時的に S3 にアップロードせず、
        # start_transcription_job + S3 を避けて直接 HTTP/2 ストリーミングを使う
        # のは複雑なため、ここでは boto3 の標準的なバッチ処理を使用する
        # ただし S3 バケットが必要になるため、代替として Transcribe Medical
        # や直接入力をサポートする方法を検討

        # 現実的な実装: 一時ファイルとして送信する非ストリーミング方式
        # Amazon Transcribe のバッチ処理には S3 が必要なため、
        # Transcribe Streaming SDK を使用する
        try:
            # amazon-transcribe-streaming-sdk が利用可能か確認
            from amazon_transcribe.client import TranscribeStreamingClient
            from amazon_transcribe.handlers import TranscriptResultStreamHandler
            from amazon_transcribe.model import TranscriptEvent

            return self._transcribe_with_streaming_sdk(
                audio_data, language_code, media_format
            )
        except ImportError:
            # SDK が無い場合は boto3 の start_stream_transcription を使用
            return self._transcribe_with_boto3_streaming(
                client, audio_data, language_code, media_format
            )

    def _transcribe_with_streaming_sdk(
        self, audio_data: bytes, language_code: str, media_format: str
    ) -> str:
        """amazon-transcribe-streaming-sdk を使用した文字起こし."""
        import asyncio
        from amazon_transcribe.client import TranscribeStreamingClient
        from amazon_transcribe.handlers import TranscriptResultStreamHandler
        from amazon_transcribe.model import TranscriptEvent

        results: list[str] = []

        class MyEventHandler(TranscriptResultStreamHandler):
            async def handle_transcript_event(self, transcript_event: TranscriptEvent):
                results_stream = transcript_event.transcript.results
                for result in results_stream:
                    if not result.is_partial:
                        for alt in result.alternatives:
                            results.append(alt.transcript)

        async def _run():
            client = TranscribeStreamingClient(region=self._aws_settings.region)

            media_encoding_map = {
                "wav": "pcm",
                "flac": "flac",
                "ogg": "ogg-opus",
            }
            media_encoding = media_encoding_map.get(media_format, "pcm")

            stream = await client.start_stream_transcription(
                language_code=language_code,
                media_sample_rate_hz=16000,
                media_encoding=media_encoding,
            )

            # 音声データをチャンクで送信
            chunk_size = 1024 * 16  # 16KB chunks
            async def _send_chunks():
                for i in range(0, len(audio_data), chunk_size):
                    chunk = audio_data[i : i + chunk_size]
                    await stream.input_stream.send_audio_event(audio_chunk=chunk)
                await stream.input_stream.end_stream()

            handler = MyEventHandler(stream.output_stream)
            await asyncio.gather(_send_chunks(), handler.handle_events())

        # asyncio イベントループで実行
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 既存ループ内の場合は新しいループを作成
                loop = asyncio.new_event_loop()
                loop.run_until_complete(_run())
                loop.close()
            else:
                loop.run_until_complete(_run())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
            loop.close()

        return "".join(results)

    def _transcribe_with_boto3_streaming(
        self, client, audio_data: bytes, language_code: str, media_format: str
    ) -> str:
        """boto3 の TranscribeStreaming で文字起こしする.

        boto3 には transcribestreaming クライアントがないため、
        transcribe のバッチジョブを使用する（S3 経由）。
        S3 が不要な方法として、ローカルで HTTP/2 を使う方法は複雑なため、
        ここではファイルの内容を直接処理する代替策を使う。

        実際の運用では以下のいずれかを推奨:
        1. amazon-transcribe-streaming-sdk を pip install する
        2. S3 バケットを用意して Transcribe バッチジョブを使用する

        この実装では S3 + バッチジョブ方式にフォールバックする。
        """
        import uuid

        # S3 バケット名を設定から取得（なければエラー）
        # 注: 将来的に TranscriberSettings に s3_bucket を追加する可能性あり
        # 現在は環境変数から取得
        import os
        s3_bucket = os.environ.get("SCREEN_RECORDER_S3_BUCKET", "")
        if not s3_bucket:
            raise RuntimeError(
                "Amazon Transcribe のバッチ処理には S3 バケットが必要です。\n"
                "環境変数 SCREEN_RECORDER_S3_BUCKET を設定するか、\n"
                "pip install amazon-transcribe-streaming-sdk を実行して "
                "ストリーミング API を使用してください。"
            )

        from screen_audio_recorder.aws_utils import create_boto3_client
        s3_client = create_boto3_client("s3", self._aws_settings)

        # 一時ファイルを S3 にアップロード
        job_name = f"screen-recorder-{uuid.uuid4().hex[:8]}-{int(time.time())}"
        s3_key = f"screen-audio-recorder/tmp/{job_name}.{media_format}"
        s3_uri = f"s3://{s3_bucket}/{s3_key}"

        try:
            s3_client.put_object(Bucket=s3_bucket, Key=s3_key, Body=audio_data)

            # Transcribe ジョブ開始
            client.start_transcription_job(
                TranscriptionJobName=job_name,
                LanguageCode=language_code,
                MediaFormat=media_format,
                Media={"MediaFileUri": s3_uri},
            )

            # ジョブ完了を待つ
            while True:
                status = client.get_transcription_job(TranscriptionJobName=job_name)
                job_status = status["TranscriptionJob"]["TranscriptionJobStatus"]
                if job_status == "COMPLETED":
                    break
                elif job_status == "FAILED":
                    reason = status["TranscriptionJob"].get("FailureReason", "不明")
                    raise RuntimeError(f"Transcribe ジョブが失敗しました: {reason}")
                time.sleep(2)

            # 結果を取得
            transcript_uri = status["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
            req = urllib.request.Request(transcript_uri, method="GET")
            with urllib.request.urlopen(req, timeout=30) as resp:
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
                client.delete_transcription_job(TranscriptionJobName=job_name)
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
