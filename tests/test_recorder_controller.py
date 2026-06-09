"""RecorderController のユニットテスト.

全コンポーネントをモックして以下を検証する:
- RecordingMode.AUDIO_ONLY 時に ScreenCapture.start() が呼ばれないこと（要件 5.1、5.2）
- RecordingMode.SCREEN_AND_AUDIO 時に ScreenCapture.start() が呼ばれること（要件 2.1）
- stop_recording() 後に VideoEncoder.finish() が呼ばれること（要件 2.4）
- update_region() が ScreenCapture.set_region() を呼ぶこと（要件 2.4）
- ThemeGeneratorService.generate() が文字起こし完了後に呼ばれること（要件 7.1、7.4）
- MemoStore.create() がテーマと本文を受け取ること（要件 8.1）

**Validates: Requirements 2.1, 2.4, 5.1, 5.2, 5.4, 6.1, 7.4**
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

from screen_audio_recorder.models import (
    AudioChunk,
    RecordingMode,
    RecordingRegion,
    TranscribeResult,
)
from screen_audio_recorder.recorder_controller import RecorderController


# ---------------------------------------------------------------------------
# テスト用ヘルパー
# ---------------------------------------------------------------------------


def make_region(x: int = 0, y: int = 0, width: int = 1920, height: int = 1080) -> RecordingRegion:
    """テスト用 RecordingRegion を生成する."""
    return RecordingRegion(x=x, y=y, width=width, height=height)


def make_transcribe_result(text: str = "テスト文字起こし", error: str | None = None) -> TranscribeResult:
    """テスト用 TranscribeResult を生成する."""
    return TranscribeResult(
        text=text,
        language="ja",
        duration_seconds=1.0,
        error=error,
    )


def make_controller(
    transcribe_text: str = "テスト文字起こし",
    theme: str = "テーマ",
    output_path: Path | None = None,
) -> tuple[RecorderController, dict]:
    """テスト用 RecorderController とモックコンポーネントを生成するヘルパー.

    Args:
        transcribe_text: 文字起こし結果テキスト
        theme: ThemeGeneratorService.generate() が返すテーマ
        output_path: FileStore.get_output_path() が返すパス

    Returns:
        (RecorderController インスタンス, モックコンポーネント辞書) のタプル
    """
    if output_path is None:
        output_path = Path("/tmp/test_output.mp3")

    # 各コンポーネントのモックを作成
    mock_screen_capture = MagicMock()
    mock_screen_capture.get_frame_queue.return_value = queue.Queue()

    mock_audio_capture = MagicMock()
    mock_audio_capture.get_audio_queue.return_value = queue.Queue()

    mock_video_encoder = MagicMock()
    mock_video_encoder.finish.return_value = output_path

    # transcribe_async は callback を直接呼ぶように設定
    mock_transcriber = MagicMock()
    transcribe_result = make_transcribe_result(text=transcribe_text)

    def transcribe_async_side_effect(audio_path, callback, root=None):
        # 別スレッドで callback を呼ぶ（実際の動作を模倣）
        t = threading.Thread(target=callback, args=(transcribe_result,), daemon=True)
        t.start()

    mock_transcriber.transcribe_async.side_effect = transcribe_async_side_effect

    mock_theme_generator = MagicMock()
    mock_theme_generator.generate.return_value = theme

    mock_memo_store = MagicMock()
    mock_file_store = MagicMock()
    mock_file_store.get_output_path.return_value = output_path

    mock_error_notifier = MagicMock()

    controller = RecorderController(
        screen_capture=mock_screen_capture,
        audio_capture=mock_audio_capture,
        video_encoder=mock_video_encoder,
        transcriber=mock_transcriber,
        theme_generator=mock_theme_generator,
        memo_store=mock_memo_store,
        file_store=mock_file_store,
        error_notifier=mock_error_notifier,
    )

    mocks = {
        "screen_capture": mock_screen_capture,
        "audio_capture": mock_audio_capture,
        "video_encoder": mock_video_encoder,
        "transcriber": mock_transcriber,
        "theme_generator": mock_theme_generator,
        "memo_store": mock_memo_store,
        "file_store": mock_file_store,
        "error_notifier": mock_error_notifier,
    }

    return controller, mocks


# ---------------------------------------------------------------------------
# is_recording プロパティのテスト
# ---------------------------------------------------------------------------


class TestIsRecording:
    """is_recording プロパティのテスト."""

    def test_is_recording_initially_false(self) -> None:
        """初期状態では is_recording が False である."""
        controller, _ = make_controller()
        assert controller.is_recording is False

    def test_is_recording_true_after_start(self) -> None:
        """start_recording() 後は is_recording が True になる."""
        controller, _ = make_controller()
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)

        assert controller.is_recording is True

        # クリーンアップ
        controller.stop_recording()

    def test_is_recording_false_after_stop(self) -> None:
        """stop_recording() 後は is_recording が False になる."""
        controller, _ = make_controller()
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        assert controller.is_recording is False


# ---------------------------------------------------------------------------
# RecordingMode.AUDIO_ONLY 時の ScreenCapture 非起動テスト（要件 5.1、5.2）
# ---------------------------------------------------------------------------


class TestAudioOnlyMode:
    """RecordingMode.AUDIO_ONLY 時の動作テスト.

    **Validates: Requirements 5.1, 5.2**
    """

    def test_audio_only_does_not_call_screen_capture_start(self) -> None:
        """AUDIO_ONLY モードで ScreenCapture.start() が呼ばれないこと（要件 5.2）."""
        controller, mocks = make_controller()
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)

        # ScreenCapture.start() が呼ばれていないことを確認
        mocks["screen_capture"].start.assert_not_called()

        # クリーンアップ
        controller.stop_recording()

    def test_audio_only_calls_audio_capture_start(self) -> None:
        """AUDIO_ONLY モードで AudioCapture.start_direct_recording() が呼ばれること."""
        controller, mocks = make_controller()
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)

        # AudioCapture.start_direct_recording() が呼ばれていることを確認
        mocks["audio_capture"].start_direct_recording.assert_called_once()

        # クリーンアップ
        controller.stop_recording()

    def test_audio_only_calls_video_encoder_start(self) -> None:
        """AUDIO_ONLY モードで VideoEncoder.start() が呼ばれないこと（直接 WAV 録音）."""
        controller, mocks = make_controller()
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)

        # AUDIO_ONLY では VideoEncoder は使わない
        mocks["video_encoder"].start.assert_not_called()

        # クリーンアップ
        controller.stop_recording()

    def test_audio_only_video_encoder_start_with_audio_only_mode(self) -> None:
        """AUDIO_ONLY モードで直接 WAV 録音が使われること."""
        controller, mocks = make_controller()
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)

        # start_direct_recording が呼ばれていることを確認
        mocks["audio_capture"].start_direct_recording.assert_called_once()

        # クリーンアップ
        controller.stop_recording()

    def test_audio_only_stop_does_not_call_screen_capture_stop(self) -> None:
        """AUDIO_ONLY モードで stop_recording() 後に ScreenCapture.stop() が呼ばれないこと."""
        controller, mocks = make_controller()
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        # ScreenCapture.stop() が呼ばれていないことを確認
        mocks["screen_capture"].stop.assert_not_called()


# ---------------------------------------------------------------------------
# RecordingMode.SCREEN_AND_AUDIO 時の ScreenCapture 起動テスト（要件 2.1）
# ---------------------------------------------------------------------------


class TestScreenAndAudioMode:
    """RecordingMode.SCREEN_AND_AUDIO 時の動作テスト.

    **Validates: Requirements 2.1**
    """

    def test_screen_and_audio_calls_screen_capture_start(self) -> None:
        """SCREEN_AND_AUDIO モードで ScreenCapture.start() が呼ばれること（要件 2.1）."""
        controller, mocks = make_controller(output_path=Path("/tmp/test_output.mp4"))
        region = make_region()

        controller.start_recording(RecordingMode.SCREEN_AND_AUDIO, region)

        # ScreenCapture.start() が呼ばれていることを確認
        mocks["screen_capture"].start.assert_called_once_with(region)

        # クリーンアップ
        controller.stop_recording()

    def test_screen_and_audio_calls_audio_capture_start(self) -> None:
        """SCREEN_AND_AUDIO モードで AudioCapture.start_direct_recording() が呼ばれること."""
        controller, mocks = make_controller(output_path=Path("/tmp/test_output.mp4"))
        region = make_region()

        controller.start_recording(RecordingMode.SCREEN_AND_AUDIO, region)

        # AudioCapture.start_direct_recording() が呼ばれていることを確認
        mocks["audio_capture"].start_direct_recording.assert_called_once()

        # クリーンアップ
        controller.stop_recording()

    def test_screen_and_audio_calls_video_encoder_start(self) -> None:
        """SCREEN_AND_AUDIO モードで VideoEncoder.start() が呼ばれること."""
        controller, mocks = make_controller(output_path=Path("/tmp/test_output.mp4"))
        region = make_region()

        controller.start_recording(RecordingMode.SCREEN_AND_AUDIO, region)

        # VideoEncoder.start() が呼ばれていることを確認
        mocks["video_encoder"].start.assert_called_once()

        # クリーンアップ
        controller.stop_recording()

    def test_screen_and_audio_stop_calls_screen_capture_stop(self) -> None:
        """SCREEN_AND_AUDIO モードで stop_recording() 後に ScreenCapture.stop() が呼ばれること."""
        controller, mocks = make_controller(output_path=Path("/tmp/test_output.mp4"))
        region = make_region()

        controller.start_recording(RecordingMode.SCREEN_AND_AUDIO, region)
        controller.stop_recording()

        # ScreenCapture.stop() が呼ばれていることを確認
        mocks["screen_capture"].stop.assert_called_once()


# ---------------------------------------------------------------------------
# stop_recording() 後の VideoEncoder.finish() 呼び出しテスト（要件 2.4）
# ---------------------------------------------------------------------------


class TestStopRecording:
    """stop_recording() の動作テスト.

    **Validates: Requirements 2.4, 5.4**
    """

    def test_stop_recording_calls_video_encoder_finish(self) -> None:
        """SCREEN_AND_AUDIO モードで stop_recording() 後に VideoEncoder.finish() が呼ばれること."""
        controller, mocks = make_controller(output_path=Path("/tmp/test_output.mp4"))
        region = make_region()

        controller.start_recording(RecordingMode.SCREEN_AND_AUDIO, region)
        controller.stop_recording()

        # VideoEncoder.finish() が呼ばれていることを確認
        mocks["video_encoder"].finish.assert_called_once()

    def test_stop_recording_calls_audio_capture_stop(self) -> None:
        """stop_recording() 後に AudioCapture.stop() が呼ばれること."""
        controller, mocks = make_controller()
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        # AudioCapture.stop() が呼ばれていることを確認
        mocks["audio_capture"].stop.assert_called_once()

    def test_stop_recording_calls_transcriber_transcribe_async(self) -> None:
        """stop_recording() 後に Transcriber.transcribe_async() が呼ばれること（要件 6.1）."""
        controller, mocks = make_controller()
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        # Transcriber.transcribe_async() が呼ばれていることを確認
        mocks["transcriber"].transcribe_async.assert_called_once()

    def test_stop_recording_without_start_does_not_raise(self) -> None:
        """start_recording() なしで stop_recording() を呼んでも例外が発生しない."""
        controller, _ = make_controller()

        # 例外が発生しないことを確認
        controller.stop_recording()

    def test_double_start_recording_is_ignored(self) -> None:
        """start_recording() を二重に呼んでも二重起動しない."""
        controller, mocks = make_controller()
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.start_recording(RecordingMode.AUDIO_ONLY, region)  # 2回目は無視される

        # AudioCapture.start_direct_recording() が1回だけ呼ばれていることを確認
        mocks["audio_capture"].start_direct_recording.assert_called_once()

        # クリーンアップ
        controller.stop_recording()


# ---------------------------------------------------------------------------
# update_region() が ScreenCapture.set_region() を呼ぶテスト（要件 2.4）
# ---------------------------------------------------------------------------


class TestUpdateRegion:
    """update_region() の動作テスト.

    **Validates: Requirements 2.4**
    """

    def test_update_region_calls_screen_capture_set_region(self) -> None:
        """update_region() が ScreenCapture.set_region() を呼ぶこと."""
        controller, mocks = make_controller()
        new_region = make_region(x=100, y=100, width=800, height=600)

        controller.update_region(new_region)

        # ScreenCapture.set_region() が呼ばれていることを確認
        mocks["screen_capture"].set_region.assert_called_once_with(new_region)

    def test_update_region_passes_correct_region(self) -> None:
        """update_region() が正しい RecordingRegion を ScreenCapture.set_region() に渡すこと."""
        controller, mocks = make_controller()
        new_region = RecordingRegion(x=50, y=75, width=1280, height=720)

        controller.update_region(new_region)

        call_args = mocks["screen_capture"].set_region.call_args
        passed_region = call_args.args[0] if call_args.args else call_args.kwargs.get("region")
        assert passed_region == new_region

    def test_update_region_can_be_called_multiple_times(self) -> None:
        """update_region() を複数回呼べること."""
        controller, mocks = make_controller()
        region1 = make_region(width=800, height=600)
        region2 = make_region(width=1280, height=720)
        region3 = make_region(width=1920, height=1080)

        controller.update_region(region1)
        controller.update_region(region2)
        controller.update_region(region3)

        # 3回呼ばれていることを確認
        assert mocks["screen_capture"].set_region.call_count == 3


# ---------------------------------------------------------------------------
# ThemeGeneratorService.generate() が文字起こし完了後に呼ばれるテスト（要件 7.1、7.4）
# ---------------------------------------------------------------------------


class TestThemeGeneratorIntegration:
    """ThemeGeneratorService の統合テスト.

    **Validates: Requirements 7.1, 7.4**
    """

    def test_theme_generator_called_after_transcription(self) -> None:
        """文字起こし完了後に ThemeGeneratorService.generate() が呼ばれること（要件 7.1）."""
        transcribe_text = "本日の会議では新しいプロジェクトについて議論しました"
        controller, mocks = make_controller(transcribe_text=transcribe_text)
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        # 文字起こしスレッドの完了を待つ
        time.sleep(0.5)

        # ThemeGeneratorService.generate() が呼ばれていることを確認
        mocks["theme_generator"].generate.assert_called_once()

    def test_theme_generator_receives_transcribed_text(self) -> None:
        """ThemeGeneratorService.generate() が文字起こしテキストを受け取ること."""
        transcribe_text = "テスト文字起こしテキスト"
        controller, mocks = make_controller(transcribe_text=transcribe_text)
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        # 文字起こしスレッドの完了を待つ
        time.sleep(0.5)

        # ThemeGeneratorService.generate() に正しいテキストが渡されていることを確認
        mocks["theme_generator"].generate.assert_called_once_with(transcribe_text)

    def test_theme_generator_called_with_empty_text_on_transcription_failure(self) -> None:
        """文字起こし失敗時（空テキスト）でも ThemeGeneratorService.generate() が呼ばれること."""
        controller, mocks = make_controller(transcribe_text="")
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        # 文字起こしスレッドの完了を待つ
        time.sleep(0.5)

        # ThemeGeneratorService.generate() が空テキストで呼ばれていることを確認
        mocks["theme_generator"].generate.assert_called_once_with("")


# ---------------------------------------------------------------------------
# MemoStore.create() がテーマと本文を受け取るテスト（要件 8.1）
# ---------------------------------------------------------------------------


class TestMemoStoreIntegration:
    """MemoStore.create() の統合テスト.

    **Validates: Requirements 8.1**
    """

    def test_memo_store_create_called_after_theme_generation(self) -> None:
        """テーマ生成後に MemoStore.create() が呼ばれること（要件 7.4）."""
        controller, mocks = make_controller(
            transcribe_text="テスト文字起こし",
            theme="テーマ",
        )
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        # 文字起こしスレッドの完了を待つ
        time.sleep(0.5)

        # MemoStore.create() が呼ばれていることを確認
        mocks["memo_store"].create.assert_called_once()

    def test_memo_store_create_receives_correct_theme(self) -> None:
        """MemoStore.create() が正しいテーマを受け取ること（要件 8.1）."""
        expected_theme = "会議メモ"
        controller, mocks = make_controller(
            transcribe_text="本日の会議内容",
            theme=expected_theme,
        )
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        # 文字起こしスレッドの完了を待つ
        time.sleep(0.5)

        # MemoStore.create() に正しいテーマが渡されていることを確認
        mocks["memo_store"].create.assert_called_once()
        call_kwargs = mocks["memo_store"].create.call_args
        passed_theme = call_kwargs.kwargs.get("theme") or (
            call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        )
        assert passed_theme == expected_theme

    def test_memo_store_create_receives_correct_body(self) -> None:
        """MemoStore.create() が正しい本文（文字起こしテキスト）を受け取ること（要件 8.1）."""
        expected_text = "本日の会議では新しいプロジェクトについて議論しました"
        controller, mocks = make_controller(
            transcribe_text=expected_text,
            theme="会議",
        )
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        # 文字起こしスレッドの完了を待つ
        time.sleep(0.5)

        # MemoStore.create() に正しいテキストが渡されていることを確認
        mocks["memo_store"].create.assert_called_once()
        call_kwargs = mocks["memo_store"].create.call_args
        passed_text = call_kwargs.kwargs.get("text") or (
            call_kwargs.args[0] if len(call_kwargs.args) > 0 else None
        )
        assert passed_text == expected_text

    def test_memo_store_create_receives_output_file_path(self) -> None:
        """MemoStore.create() が OutputFile パスを受け取ること（要件 8.1）."""
        expected_output_path = Path("/tmp/test_recording.mp3")
        controller, mocks = make_controller(
            transcribe_text="テスト",
            theme="テーマ",
            output_path=expected_output_path,
        )
        region = make_region()

        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        # 文字起こしスレッドの完了を待つ
        time.sleep(0.5)

        # MemoStore.create() に正しい OutputFile パスが渡されていることを確認
        mocks["memo_store"].create.assert_called_once()
        call_kwargs = mocks["memo_store"].create.call_args
        passed_output_file = call_kwargs.kwargs.get("output_file") or (
            call_kwargs.args[2] if len(call_kwargs.args) > 2 else None
        )
        assert passed_output_file == expected_output_path

    def test_full_pipeline_audio_only(self) -> None:
        """AUDIO_ONLY モードでのフルパイプラインテスト.

        VideoEncoder.finish() → Transcriber.transcribe_async() →
        ThemeGeneratorService.generate() → MemoStore.create() の順で呼ばれること。
        """
        call_order = []

        transcribe_text = "フルパイプラインテスト"
        expected_theme = "パイプライン"
        output_path = Path("/tmp/full_pipeline_test.mp3")

        mock_screen_capture = MagicMock()
        mock_screen_capture.get_frame_queue.return_value = queue.Queue()

        mock_audio_capture = MagicMock()
        mock_audio_capture.get_audio_queue.return_value = queue.Queue()

        mock_video_encoder = MagicMock()

        def finish_side_effect():
            call_order.append("finish")
            return output_path

        mock_video_encoder.finish.side_effect = finish_side_effect

        mock_transcriber = MagicMock()
        transcribe_result = make_transcribe_result(text=transcribe_text)

        def transcribe_async_side_effect(audio_path, callback, root=None):
            call_order.append("transcribe_async")
            t = threading.Thread(target=callback, args=(transcribe_result,), daemon=True)
            t.start()

        mock_transcriber.transcribe_async.side_effect = transcribe_async_side_effect

        mock_theme_generator = MagicMock()

        def generate_side_effect(text):
            call_order.append("generate")
            return expected_theme

        mock_theme_generator.generate.side_effect = generate_side_effect

        mock_memo_store = MagicMock()

        def create_side_effect(text, theme, output_file, summary=""):
            call_order.append("create")

        mock_memo_store.create.side_effect = create_side_effect

        mock_file_store = MagicMock()
        mock_file_store.get_output_path.return_value = output_path

        mock_error_notifier = MagicMock()

        controller = RecorderController(
            screen_capture=mock_screen_capture,
            audio_capture=mock_audio_capture,
            video_encoder=mock_video_encoder,
            transcriber=mock_transcriber,
            theme_generator=mock_theme_generator,
            memo_store=mock_memo_store,
            file_store=mock_file_store,
            error_notifier=mock_error_notifier,
        )

        region = make_region()
        controller.start_recording(RecordingMode.AUDIO_ONLY, region)
        controller.stop_recording()

        # パイプラインの完了を待つ
        time.sleep(0.5)

        # AUDIO_ONLY モードでは finish() は呼ばれない（WAV がそのまま最終出力）
        # transcribe_async → generate → create の順序を確認
        assert "transcribe_async" in call_order
        assert "generate" in call_order
        assert "create" in call_order

        # generate → create の順序を確認
        assert call_order.index("generate") < call_order.index("create")
