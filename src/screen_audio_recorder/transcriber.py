"""Transcriber: 音声ファイルの文字起こしを担当するクラス.

``faster-whisper`` の ``WhisperModel`` を使用して日本語音声をテキストに変換する。
モデルファイルは ``~/.screen-audio-recorder/models/`` にキャッシュする。
推論は別スレッドで実行し、完了後に ``root.after_idle()`` で GUI スレッドに通知する。

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from screen_audio_recorder.models import TranscribeResult

if TYPE_CHECKING:
    pass

# faster-whisper は try/except でインポートし、利用不可の場合は None にフォールバック
try:
    from faster_whisper import WhisperModel as _WhisperModel

    _FASTER_WHISPER_AVAILABLE = True
except ImportError:
    _WhisperModel = None  # type: ignore[assignment,misc]
    _FASTER_WHISPER_AVAILABLE = False

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
    ) -> None:
        """Transcriber を初期化し、faster-whisper モデルをロードする.

        モデルファイルは ``~/.screen-audio-recorder/models/`` にキャッシュされる。
        モデルのロードに失敗した場合は ``error_notifier.show_error()`` を呼び出し、
        文字起こし機能を無効化する。

        Args:
            model_size: Whisper モデルサイズ（デフォルト: "large"）。
                "tiny", "base", "small", "medium", "large" などが指定可能。
            error_notifier: エラー通知オブジェクト（``ErrorNotifier`` インスタンス）。
                None の場合はエラー通知を行わない。
            memo_store: メモ保存オブジェクト（``MemoStore`` インスタンス）。
                None の場合はメモ保存を行わない。
            lazy_load: True の場合、モデルのロードを遅延させる。
                load_model_async() で後からロードする。
        """
        self._model_size = model_size
        self._error_notifier = error_notifier
        self._memo_store = memo_store
        self._model = None
        self._enabled = False

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
            # 遅延ロード: load_model_async() で後からロードする
            return

        self._load_model()

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

        ``faster-whisper`` の ``WhisperModel.transcribe()`` を使用して
        日本語音声をテキストに変換する。

        文字起こしに失敗した場合は ``error_notifier.show_error()`` を呼び出し、
        空テキストの ``TranscribeResult`` を返す。

        Args:
            audio_path: 文字起こし対象の音声ファイルパス。

        Returns:
            文字起こし結果を含む ``TranscribeResult`` オブジェクト。
            失敗時は ``text=""``、``error`` にエラーメッセージが設定される。

        要件 6.1: OutputFile が生成されたとき、音声をテキストに変換する処理を開始する。
        要件 6.2: 日本語音声を文字起こしの対象言語としてサポートする。
        """
        if not self._enabled or self._model is None:
            error_msg = "文字起こし機能が無効化されています。"
            logger.warning(error_msg)
            return TranscribeResult(
                text="",
                language=_LANGUAGE,
                duration_seconds=0.0,
                error=error_msg,
            )

        try:
            logger.info("文字起こし開始: %s", audio_path)
            segments, info = self._model.transcribe(
                str(audio_path),
                language=_LANGUAGE,
            )
            # segments はジェネレータなので、リストに展開してテキストを結合する
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
            error_msg = f"文字起こし処理に失敗しました: {exc}"
            logger.error(error_msg)
            if self._error_notifier is not None:
                self._error_notifier.show_error(
                    "文字起こしエラー",
                    f"音声の文字起こしに失敗しました。\n詳細: {exc}",
                )
            # 失敗時は空テキストで MemoStore.create() を呼ぶ（要件 6.4）
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
