"""Transcriber のユニットテスト.

faster-whisper をモックして以下を検証する:
- 文字起こし失敗時に空テキストで MemoStore.create() が呼ばれること（要件 6.4）
- Transcriber が外部ネットワーク接続を行わないこと（要件 6.5）
- transcribe() が TranscribeResult を返すこと
- transcribe_async() が callback を呼ぶこと

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from screen_audio_recorder.models import TranscribeResult


# ---------------------------------------------------------------------------
# テスト用ヘルパー
# ---------------------------------------------------------------------------


def _make_mock_whisper_model(segments=None, duration=1.5):
    """モック WhisperModel を作成するヘルパー.

    Args:
        segments: transcribe() が返すセグメントのリスト。
            各要素は .text 属性を持つオブジェクト。
            None の場合は空リストを使用。
        duration: transcribe() が返す info.duration の値。

    Returns:
        モック WhisperModel インスタンス。
    """
    if segments is None:
        segments = []

    mock_model = MagicMock()
    mock_info = MagicMock()
    mock_info.duration = duration
    mock_model.transcribe.return_value = (iter(segments), mock_info)
    return mock_model


def _make_segment(text: str):
    """テキストを持つモックセグメントを作成する."""
    seg = MagicMock()
    seg.text = text
    return seg


# ---------------------------------------------------------------------------
# Transcriber の初期化テスト
# ---------------------------------------------------------------------------


class TestTranscriberInit:
    """Transcriber の初期化テスト."""

    def test_init_with_mock_model_enabled(self, tmp_path: Path) -> None:
        """モックモデルで初期化すると enabled=True になる."""
        mock_model_instance = _make_mock_whisper_model()

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber(model_size="small")

        assert transcriber.enabled is True

    def test_init_faster_whisper_unavailable_disabled(self) -> None:
        """faster-whisper が利用不可の場合、enabled=False になる."""
        with patch("screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", False):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber()

        assert transcriber.enabled is False

    def test_init_model_load_failure_disabled(self, tmp_path: Path) -> None:
        """モデルロードに失敗した場合、enabled=False になる."""
        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            side_effect=RuntimeError("モデルロード失敗"),
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber()

        assert transcriber.enabled is False

    def test_init_model_load_failure_calls_error_notifier(self, tmp_path: Path) -> None:
        """モデルロードに失敗した場合、error_notifier.show_error() が呼ばれる."""
        mock_notifier = MagicMock()

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            side_effect=RuntimeError("ダウンロード失敗"),
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber(error_notifier=mock_notifier)

        mock_notifier.show_error.assert_called_once()

    def test_init_faster_whisper_unavailable_calls_error_notifier(self) -> None:
        """faster-whisper が利用不可の場合、error_notifier.show_error() が呼ばれる."""
        mock_notifier = MagicMock()

        with patch("screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", False):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber(error_notifier=mock_notifier)

        mock_notifier.show_error.assert_called_once()

    def test_init_creates_model_cache_dir(self, tmp_path: Path) -> None:
        """初期化時にモデルキャッシュディレクトリが作成される."""
        cache_dir = tmp_path / "models"
        mock_model_instance = _make_mock_whisper_model()

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", cache_dir
        ):
            from screen_audio_recorder.transcriber import Transcriber

            Transcriber()

        assert cache_dir.exists()


# ---------------------------------------------------------------------------
# transcribe() のテスト
# ---------------------------------------------------------------------------


class TestTranscriberTranscribe:
    """Transcriber.transcribe() のテスト."""

    def _make_transcriber(self, tmp_path: Path, segments=None, duration=1.5):
        """テスト用 Transcriber を作成するヘルパー."""
        mock_model_instance = _make_mock_whisper_model(segments=segments, duration=duration)

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber()

        return transcriber, mock_model_instance

    def test_transcribe_returns_transcribe_result(self, tmp_path: Path) -> None:
        """transcribe() が TranscribeResult を返す."""
        segments = [_make_segment("こんにちは"), _make_segment("世界")]
        transcriber, _ = self._make_transcriber(tmp_path, segments=segments)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        result = transcriber.transcribe(audio_file)

        assert isinstance(result, TranscribeResult)

    def test_transcribe_returns_correct_text(self, tmp_path: Path) -> None:
        """transcribe() がセグメントを結合したテキストを返す."""
        segments = [_make_segment("こんにちは"), _make_segment("世界")]
        transcriber, _ = self._make_transcriber(tmp_path, segments=segments)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        result = transcriber.transcribe(audio_file)

        assert result.text == "こんにちは世界"

    def test_transcribe_returns_japanese_language(self, tmp_path: Path) -> None:
        """transcribe() が language="ja" を返す."""
        transcriber, _ = self._make_transcriber(tmp_path)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        result = transcriber.transcribe(audio_file)

        assert result.language == "ja"

    def test_transcribe_returns_duration(self, tmp_path: Path) -> None:
        """transcribe() が duration_seconds を返す."""
        transcriber, _ = self._make_transcriber(tmp_path, duration=3.7)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        result = transcriber.transcribe(audio_file)

        assert result.duration_seconds == pytest.approx(3.7)

    def test_transcribe_no_error_on_success(self, tmp_path: Path) -> None:
        """成功時は error=None を返す."""
        transcriber, _ = self._make_transcriber(tmp_path)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        result = transcriber.transcribe(audio_file)

        assert result.error is None

    def test_transcribe_disabled_returns_empty_text(self) -> None:
        """文字起こし機能が無効の場合、空テキストを返す."""
        with patch("screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", False):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber()

        result = transcriber.transcribe(Path("dummy.wav"))

        assert result.text == ""
        assert result.error is not None

    def test_transcribe_calls_model_with_language_ja(self, tmp_path: Path) -> None:
        """transcribe() がモデルに language="ja" を渡す."""
        transcriber, mock_model = self._make_transcriber(tmp_path)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        transcriber.transcribe(audio_file)

        mock_model.transcribe.assert_called_once()
        call_kwargs = mock_model.transcribe.call_args
        assert call_kwargs.kwargs.get("language") == "ja" or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] == "ja"
        )


# ---------------------------------------------------------------------------
# 文字起こし失敗時のテスト（要件 6.4）
# ---------------------------------------------------------------------------


class TestTranscriberFailure:
    """文字起こし失敗時の動作テスト.

    **Validates: Requirements 6.4**
    """

    def test_transcribe_failure_returns_empty_text(self, tmp_path: Path) -> None:
        """文字起こし失敗時に空テキストの TranscribeResult を返す（要件 6.4）."""
        mock_model_instance = MagicMock()
        mock_model_instance.transcribe.side_effect = RuntimeError("文字起こし失敗")

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber()

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        result = transcriber.transcribe(audio_file)

        assert result.text == ""
        assert result.error is not None

    def test_transcribe_failure_calls_memo_store_create_with_empty_text(
        self, tmp_path: Path
    ) -> None:
        """文字起こし失敗時に空テキストで MemoStore.create() が呼ばれる（要件 6.4）."""
        mock_model_instance = MagicMock()
        mock_model_instance.transcribe.side_effect = RuntimeError("文字起こし失敗")
        mock_memo_store = MagicMock()

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber(memo_store=mock_memo_store)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        transcriber.transcribe(audio_file)

        # 空テキストで MemoStore.create() が呼ばれることを検証
        mock_memo_store.create.assert_called_once()
        call_args = mock_memo_store.create.call_args
        # 第1引数（text）が空文字列であることを確認
        assert call_args.args[0] == "" or call_args.kwargs.get("text") == ""

    def test_transcribe_failure_calls_error_notifier(self, tmp_path: Path) -> None:
        """文字起こし失敗時に error_notifier.show_error() が呼ばれる（要件 6.4）."""
        mock_model_instance = MagicMock()
        mock_model_instance.transcribe.side_effect = RuntimeError("文字起こし失敗")
        mock_notifier = MagicMock()

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber(error_notifier=mock_notifier)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        transcriber.transcribe(audio_file)

        mock_notifier.show_error.assert_called()

    def test_transcribe_failure_memo_store_not_called_without_memo_store(
        self, tmp_path: Path
    ) -> None:
        """memo_store が None の場合、失敗時に MemoStore.create() は呼ばれない."""
        mock_model_instance = MagicMock()
        mock_model_instance.transcribe.side_effect = RuntimeError("文字起こし失敗")

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            # memo_store=None で初期化（例外が発生しないことを確認）
            transcriber = Transcriber(memo_store=None)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        # 例外が発生しないことを確認
        result = transcriber.transcribe(audio_file)
        assert result.text == ""


# ---------------------------------------------------------------------------
# transcribe_async() のテスト
# ---------------------------------------------------------------------------


class TestTranscriberAsync:
    """Transcriber.transcribe_async() のテスト."""

    def _make_transcriber(self, tmp_path: Path, segments=None, duration=1.5):
        """テスト用 Transcriber を作成するヘルパー."""
        mock_model_instance = _make_mock_whisper_model(segments=segments, duration=duration)

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber()

        return transcriber

    def test_transcribe_async_calls_callback(self, tmp_path: Path) -> None:
        """transcribe_async() が callback を呼ぶ."""
        segments = [_make_segment("テスト")]
        transcriber = self._make_transcriber(tmp_path, segments=segments)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        results = []
        event = threading.Event()

        def callback(result: TranscribeResult) -> None:
            results.append(result)
            event.set()

        transcriber.transcribe_async(audio_file, callback, root=None)

        # callback が呼ばれるまで最大 5 秒待つ
        event.wait(timeout=5.0)

        assert len(results) == 1
        assert isinstance(results[0], TranscribeResult)

    def test_transcribe_async_callback_receives_correct_text(self, tmp_path: Path) -> None:
        """transcribe_async() の callback が正しいテキストを受け取る."""
        segments = [_make_segment("非同期テスト")]
        transcriber = self._make_transcriber(tmp_path, segments=segments)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        results = []
        event = threading.Event()

        def callback(result: TranscribeResult) -> None:
            results.append(result)
            event.set()

        transcriber.transcribe_async(audio_file, callback, root=None)
        event.wait(timeout=5.0)

        assert results[0].text == "非同期テスト"

    def test_transcribe_async_with_root_uses_after_idle(self, tmp_path: Path) -> None:
        """root が指定された場合、transcribe_async() が root.after_idle() を使用する."""
        segments = [_make_segment("テスト")]
        transcriber = self._make_transcriber(tmp_path, segments=segments)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        mock_root = MagicMock()
        event = threading.Event()

        # after_idle が呼ばれたらイベントをセット
        def after_idle_side_effect(func, *args):
            event.set()

        mock_root.after_idle.side_effect = after_idle_side_effect

        callback = MagicMock()
        transcriber.transcribe_async(audio_file, callback, root=mock_root)

        event.wait(timeout=5.0)

        mock_root.after_idle.assert_called_once()

    def test_transcribe_async_without_root_calls_callback_directly(
        self, tmp_path: Path
    ) -> None:
        """root=None の場合、transcribe_async() が callback を直接呼ぶ."""
        segments = [_make_segment("直接呼び出しテスト")]
        transcriber = self._make_transcriber(tmp_path, segments=segments)

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        results = []
        event = threading.Event()

        def callback(result: TranscribeResult) -> None:
            results.append(result)
            event.set()

        transcriber.transcribe_async(audio_file, callback, root=None)
        event.wait(timeout=5.0)

        assert len(results) == 1

    def test_transcribe_async_runs_in_separate_thread(self, tmp_path: Path) -> None:
        """transcribe_async() が別スレッドで実行される."""
        main_thread_id = threading.current_thread().ident
        worker_thread_ids = []
        event = threading.Event()

        mock_model_instance = MagicMock()
        mock_info = MagicMock()
        mock_info.duration = 1.0

        def mock_transcribe(path, language):
            worker_thread_ids.append(threading.current_thread().ident)
            return (iter([]), mock_info)

        mock_model_instance.transcribe.side_effect = mock_transcribe

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber()

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        def callback(result):
            event.set()

        transcriber.transcribe_async(audio_file, callback, root=None)
        event.wait(timeout=5.0)

        assert len(worker_thread_ids) == 1
        assert worker_thread_ids[0] != main_thread_id


# ---------------------------------------------------------------------------
# ネットワーク非送信テスト（要件 6.5）
# ---------------------------------------------------------------------------


class TestTranscriberNoNetworkAccess:
    """Transcriber が外部ネットワーク接続を行わないことのテスト.

    **Validates: Requirements 6.5**
    """

    def test_transcribe_does_not_make_network_connections(self, tmp_path: Path) -> None:
        """transcribe() が外部ネットワーク接続を行わない（要件 6.5）.

        socket.socket をモックして、実際のネットワーク接続が発生しないことを検証する。
        """
        segments = [_make_segment("ローカル処理テスト")]
        mock_model_instance = _make_mock_whisper_model(segments=segments)

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber()

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        # socket.socket をモックして接続試行を検出する
        original_socket = socket.socket
        connection_attempts = []

        class MockSocket:
            def __init__(self, *args, **kwargs):
                pass

            def connect(self, address):
                connection_attempts.append(address)
                raise ConnectionRefusedError("ネットワーク接続は許可されていません")

            def connect_ex(self, address):
                connection_attempts.append(address)
                return 111  # ECONNREFUSED

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def close(self):
                pass

        with patch("socket.socket", MockSocket):
            result = transcriber.transcribe(audio_file)

        # ネットワーク接続が試みられていないことを確認
        assert len(connection_attempts) == 0, (
            f"Transcriber が外部ネットワーク接続を試みました: {connection_attempts}"
        )
        # 文字起こし自体は成功していること
        assert isinstance(result, TranscribeResult)

    def test_transcribe_async_does_not_make_network_connections(
        self, tmp_path: Path
    ) -> None:
        """transcribe_async() が外部ネットワーク接続を行わない（要件 6.5）."""
        segments = [_make_segment("非同期ローカル処理テスト")]
        mock_model_instance = _make_mock_whisper_model(segments=segments)

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber()

        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        connection_attempts = []
        event = threading.Event()

        class MockSocket:
            def __init__(self, *args, **kwargs):
                pass

            def connect(self, address):
                connection_attempts.append(address)
                raise ConnectionRefusedError("ネットワーク接続は許可されていません")

            def connect_ex(self, address):
                connection_attempts.append(address)
                return 111

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def close(self):
                pass

        results = []

        def callback(result):
            results.append(result)
            event.set()

        with patch("socket.socket", MockSocket):
            transcriber.transcribe_async(audio_file, callback, root=None)
            event.wait(timeout=5.0)

        assert len(connection_attempts) == 0, (
            f"Transcriber が外部ネットワーク接続を試みました: {connection_attempts}"
        )
        assert len(results) == 1
        assert isinstance(results[0], TranscribeResult)

    def test_transcriber_init_with_cached_model_no_network(self, tmp_path: Path) -> None:
        """モデルがキャッシュ済みの場合、初期化時にネットワーク接続を行わない（要件 6.5）.

        WhisperModel のコンストラクタをモックすることで、
        実際のダウンロードが発生しないことを検証する。
        """
        mock_model_instance = _make_mock_whisper_model()
        connection_attempts = []

        class MockSocket:
            def __init__(self, *args, **kwargs):
                pass

            def connect(self, address):
                connection_attempts.append(address)
                raise ConnectionRefusedError("ネットワーク接続は許可されていません")

            def connect_ex(self, address):
                connection_attempts.append(address)
                return 111

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def close(self):
                pass

        with patch(
            "screen_audio_recorder.transcriber._FASTER_WHISPER_AVAILABLE", True
        ), patch(
            "screen_audio_recorder.transcriber._WhisperModel",
            return_value=mock_model_instance,
        ), patch(
            "screen_audio_recorder.transcriber._MODEL_CACHE_DIR", tmp_path / "models"
        ), patch("socket.socket", MockSocket):
            from screen_audio_recorder.transcriber import Transcriber

            transcriber = Transcriber()

        assert len(connection_attempts) == 0, (
            f"Transcriber の初期化中に外部ネットワーク接続が試みられました: {connection_attempts}"
        )
        assert transcriber.enabled is True
