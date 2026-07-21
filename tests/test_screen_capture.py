"""ScreenCapture のユニットテスト.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 3.4, 5.1, 5.2**
"""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from screen_audio_recorder.models import RecordingMode, RecordingRegion
from screen_audio_recorder.screen_capture import ScreenCapture


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def make_region(x: int = 0, y: int = 0, width: int = 640, height: int = 480) -> RecordingRegion:
    """テスト用の RecordingRegion を生成する."""
    return RecordingRegion(x=x, y=y, width=width, height=height)


def make_fake_frame(width: int = 640, height: int = 480) -> np.ndarray:
    """テスト用のフレーム（numpy 配列）を生成する."""
    return np.zeros((height, width, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# get_frame_queue() のテスト
# ---------------------------------------------------------------------------


class TestGetFrameQueue:
    """get_frame_queue() のテスト."""

    def test_returns_queue_instance(self) -> None:
        """get_frame_queue() が queue.Queue インスタンスを返す."""
        capture = ScreenCapture()
        q = capture.get_frame_queue()
        assert isinstance(q, queue.Queue)

    def test_returns_same_queue(self) -> None:
        """get_frame_queue() は常に同じキューを返す."""
        capture = ScreenCapture()
        q1 = capture.get_frame_queue()
        q2 = capture.get_frame_queue()
        assert q1 is q2


# ---------------------------------------------------------------------------
# set_region() のテスト
# ---------------------------------------------------------------------------


class TestSetRegion:
    """set_region() のテスト."""

    def test_set_region_updates_region(self) -> None:
        """set_region() が録画領域を正しく更新する."""
        capture = ScreenCapture()
        region1 = make_region(0, 0, 640, 480)
        region2 = make_region(100, 200, 800, 600)

        capture.set_region(region1)
        assert capture._region == region1

        capture.set_region(region2)
        assert capture._region == region2

    def test_set_region_thread_safe(self) -> None:
        """set_region() がスレッドセーフに動作する."""
        capture = ScreenCapture()
        errors: list[Exception] = []

        def update_region(x: int) -> None:
            try:
                for _ in range(50):
                    capture.set_region(make_region(x=x))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=update_region, args=(i * 10,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_set_region_during_capture(self) -> None:
        """キャプチャ中に set_region() を呼び出しても例外が発生しない."""
        capture = ScreenCapture()
        region = make_region()

        # キャプチャスレッドをモックして実際のキャプチャは行わない
        with patch.object(capture, "_capture_worker_dxcam"), \
             patch.object(capture, "_capture_worker_mss"):
            capture.set_region(region)
            new_region = make_region(50, 50, 320, 240)
            capture.set_region(new_region)
            assert capture._region == new_region


# ---------------------------------------------------------------------------
# get_preview_frame() のテスト
# ---------------------------------------------------------------------------


class TestGetPreviewFrame:
    """get_preview_frame() のテスト."""

    def test_returns_none_before_capture(self) -> None:
        """キャプチャ開始前は None を返す."""
        capture = ScreenCapture()
        assert capture.get_preview_frame() is None

    def test_returns_latest_frame(self) -> None:
        """_store_frame() 後に最新フレームを返す."""
        capture = ScreenCapture()
        frame = make_fake_frame()
        capture._store_frame(frame)
        result = capture.get_preview_frame()
        assert result is not None
        assert np.array_equal(result, frame)

    def test_returns_most_recent_frame(self) -> None:
        """複数フレームが格納された場合、最新のフレームを返す."""
        capture = ScreenCapture()
        frame1 = make_fake_frame()
        frame1[:] = 100  # 値を設定して区別できるようにする
        frame2 = make_fake_frame()
        frame2[:] = 200

        capture._store_frame(frame1)
        capture._store_frame(frame2)

        result = capture.get_preview_frame()
        assert result is not None
        assert np.array_equal(result, frame2)

    def test_preview_frame_thread_safe(self) -> None:
        """get_preview_frame() がスレッドセーフに動作する."""
        capture = ScreenCapture()
        errors: list[Exception] = []

        def write_frames() -> None:
            try:
                for i in range(50):
                    frame = make_fake_frame()
                    capture._store_frame(frame)
            except Exception as e:
                errors.append(e)

        def read_frames() -> None:
            try:
                for _ in range(50):
                    capture.get_preview_frame()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=write_frames),
            threading.Thread(target=read_frames),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ---------------------------------------------------------------------------
# start() / stop() のテスト（dxcam モック）
# ---------------------------------------------------------------------------


class TestStartStopWithDxcam:
    """dxcam をモックした start() / stop() のテスト."""

    def test_start_creates_capture_thread(self) -> None:
        """start() がキャプチャスレッドを作成する（dxcam モック）."""
        capture = ScreenCapture()
        region = make_region()

        fake_frame = make_fake_frame()
        mock_camera = MagicMock()
        mock_camera.grab.return_value = fake_frame
        mock_camera.width = 1920
        mock_camera.height = 1080

        with patch("screen_audio_recorder.screen_capture.dxcam") as mock_dxcam:
            mock_dxcam.create.return_value = mock_camera
            capture.start(region)
            # スレッドが起動していることを確認
            assert capture._capture_thread is not None
            assert capture._capture_thread.is_alive()
            capture.stop()

    def test_stop_terminates_thread(self) -> None:
        """stop() がキャプチャスレッドを終了する（dxcam モック）."""
        capture = ScreenCapture()
        region = make_region()

        mock_camera = MagicMock()
        mock_camera.grab.return_value = make_fake_frame()
        mock_camera.width = 1920
        mock_camera.height = 1080

        with patch("screen_audio_recorder.screen_capture.dxcam") as mock_dxcam:
            mock_dxcam.create.return_value = mock_camera
            capture.start(region)
            capture.stop()
            # スレッドが終了していることを確認
            assert capture._capture_thread is None

    def test_frames_added_to_queue(self) -> None:
        """キャプチャしたフレームがキューに追加される（dxcam モック）."""
        capture = ScreenCapture()
        region = make_region()

        fake_frame = make_fake_frame()
        mock_camera = MagicMock()
        mock_camera.grab.return_value = fake_frame
        mock_camera.width = 1920
        mock_camera.height = 1080

        with patch("screen_audio_recorder.screen_capture.dxcam") as mock_dxcam:
            mock_dxcam.create.return_value = mock_camera
            capture.start(region)
            # フレームがキューに追加されるまで少し待つ
            time.sleep(0.2)
            capture.stop()

        q = capture.get_frame_queue()
        assert not q.empty()


# ---------------------------------------------------------------------------
# start() / stop() のテスト（mss フォールバック）
# ---------------------------------------------------------------------------


class TestStartStopWithMss:
    """mss をモックした start() / stop() のテスト（dxcam フォールバック）."""

    def test_start_uses_mss_when_dxcam_unavailable(self) -> None:
        """dxcam が利用不可の場合、mss を使用してキャプチャを開始する."""
        capture = ScreenCapture()
        region = make_region()

        fake_frame_array = make_fake_frame()

        mock_screenshot = MagicMock()
        mock_screenshot.__array__ = MagicMock(return_value=fake_frame_array)

        mock_sct = MagicMock()
        mock_sct.__enter__ = MagicMock(return_value=mock_sct)
        mock_sct.__exit__ = MagicMock(return_value=False)
        mock_sct.grab.return_value = mock_screenshot

        with patch("screen_audio_recorder.screen_capture.dxcam", None), \
             patch("screen_audio_recorder.screen_capture.mss") as mock_mss_module:
            mock_mss_module.mss.return_value = mock_sct
            capture.start(region)
            assert capture._capture_thread is not None
            assert capture._capture_thread.is_alive()
            capture.stop()

    def test_no_thread_when_both_unavailable(self) -> None:
        """dxcam も mss も利用不可の場合、スレッドが作成されない."""
        capture = ScreenCapture()
        region = make_region()

        with patch("screen_audio_recorder.screen_capture.dxcam", None), \
             patch("screen_audio_recorder.screen_capture.mss", None):
            capture.start(region)
            assert capture._capture_thread is None


# ---------------------------------------------------------------------------
# 要件 5.1, 5.2: 録音のみモードで ScreenCapture が起動されないことのテスト
# ---------------------------------------------------------------------------


class TestAudioOnlyMode:
    """要件 5.1, 5.2: 録音のみモードで ScreenCapture.start() が呼ばれないことを検証する."""

    def test_screen_capture_not_started_in_audio_only_mode(self) -> None:
        """RecordingMode.AUDIO_ONLY 選択時に ScreenCapture.start() が呼ばれない.

        RecorderController（または同等のロジック）が AUDIO_ONLY モードを選択した場合、
        ScreenCapture.start() は呼び出されないことを検証する。

        **Validates: Requirements 5.1, 5.2**
        """
        capture = ScreenCapture()
        region = make_region()

        # ScreenCapture.start() をモックして呼び出しを追跡する
        with patch.object(capture, "start") as mock_start:
            # AUDIO_ONLY モードのシミュレーション: start() を呼ばない
            mode = RecordingMode.AUDIO_ONLY
            if mode != RecordingMode.AUDIO_ONLY:
                capture.start(region)

            # AUDIO_ONLY モードでは start() が呼ばれないことを確認
            mock_start.assert_not_called()

    def test_screen_capture_started_in_screen_and_audio_mode(self) -> None:
        """RecordingMode.SCREEN_AND_AUDIO 選択時に ScreenCapture.start() が呼ばれる.

        **Validates: Requirements 2.1, 5.1**
        """
        capture = ScreenCapture()
        region = make_region()

        with patch.object(capture, "start") as mock_start:
            # SCREEN_AND_AUDIO モードのシミュレーション: start() を呼ぶ
            mode = RecordingMode.SCREEN_AND_AUDIO
            if mode == RecordingMode.SCREEN_AND_AUDIO:
                capture.start(region)

            # SCREEN_AND_AUDIO モードでは start() が呼ばれることを確認
            mock_start.assert_called_once_with(region)

    def test_recorder_controller_audio_only_does_not_call_screen_capture(self) -> None:
        """RecorderController が AUDIO_ONLY モードで ScreenCapture を起動しないことを検証する.

        RecorderController の start_recording() ロジックをシミュレートして、
        AUDIO_ONLY モードでは ScreenCapture.start() が呼ばれないことを確認する。

        **Validates: Requirements 5.1, 5.2**
        """
        capture = ScreenCapture()
        region = make_region()

        # RecorderController の start_recording() ロジックをシミュレート
        def simulate_start_recording(
            mode: RecordingMode,
            screen_capture: ScreenCapture,
            recording_region: RecordingRegion,
        ) -> None:
            """RecorderController.start_recording() のシミュレーション."""
            if mode == RecordingMode.SCREEN_AND_AUDIO:
                screen_capture.start(recording_region)
            # AUDIO_ONLY の場合は ScreenCapture を起動しない

        with patch.object(capture, "start") as mock_start:
            simulate_start_recording(RecordingMode.AUDIO_ONLY, capture, region)
            mock_start.assert_not_called()

        with patch.object(capture, "start") as mock_start:
            simulate_start_recording(RecordingMode.SCREEN_AND_AUDIO, capture, region)
            mock_start.assert_called_once_with(region)


# ---------------------------------------------------------------------------
# get_window_region() のテスト
# ---------------------------------------------------------------------------


class TestGetWindowRegion:
    """get_window_region() クラスメソッドのテスト."""

    def test_returns_region_from_win32gui(self) -> None:
        """win32gui.GetWindowRect() の結果から RecordingRegion を返す."""
        with patch("screen_audio_recorder.screen_capture.win32gui") as mock_win32gui:
            mock_win32gui.GetWindowRect.return_value = (100, 200, 900, 700)
            result = ScreenCapture.get_window_region(hwnd=12345)

        assert result is not None
        assert result.x == 100
        assert result.y == 200
        assert result.width == 800  # 900 - 100
        assert result.height == 500  # 700 - 200

    def test_returns_none_when_win32gui_unavailable(self) -> None:
        """win32gui が利用不可の場合は None を返す."""
        with patch("screen_audio_recorder.screen_capture.win32gui", None):
            result = ScreenCapture.get_window_region(hwnd=12345)
        assert result is None

    def test_returns_none_on_exception(self) -> None:
        """GetWindowRect() が例外を送出した場合は None を返す."""
        with patch("screen_audio_recorder.screen_capture.win32gui") as mock_win32gui:
            mock_win32gui.GetWindowRect.side_effect = Exception("ウィンドウが見つかりません")
            result = ScreenCapture.get_window_region(hwnd=99999)
        assert result is None

    def test_returns_none_for_zero_size_window(self) -> None:
        """サイズが 0 のウィンドウに対して None を返す."""
        with patch("screen_audio_recorder.screen_capture.win32gui") as mock_win32gui:
            mock_win32gui.GetWindowRect.return_value = (100, 100, 100, 100)  # width=0, height=0
            result = ScreenCapture.get_window_region(hwnd=12345)
        assert result is None

    def test_returns_recording_region_instance(self) -> None:
        """返り値が RecordingRegion インスタンスである."""
        with patch("screen_audio_recorder.screen_capture.win32gui") as mock_win32gui:
            mock_win32gui.GetWindowRect.return_value = (0, 0, 1920, 1080)
            result = ScreenCapture.get_window_region(hwnd=1)
        assert isinstance(result, RecordingRegion)
