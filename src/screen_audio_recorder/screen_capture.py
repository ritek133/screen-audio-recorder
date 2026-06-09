"""ScreenCapture: 画面映像のキャプチャを担当するクラス.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 3.4**
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import TYPE_CHECKING

import numpy as np

from screen_audio_recorder.models import RecordingRegion

# dxcam は Windows 専用ライブラリのため、利用不可の場合は None にフォールバック
try:
    import dxcam  # type: ignore[import]
except (ImportError, Exception):
    dxcam = None  # type: ignore[assignment]

# mss は dxcam が利用不可の場合のフォールバック
try:
    import mss  # type: ignore[import]
except (ImportError, Exception):
    mss = None  # type: ignore[assignment]

# win32gui は Windows 専用ライブラリのため、利用不可の場合は None にフォールバック
try:
    import win32gui  # type: ignore[import]
except (ImportError, Exception):
    win32gui = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# フレームレート定数
TARGET_FPS = 15
FRAME_INTERVAL = 1.0 / TARGET_FPS  # 約 0.0667 秒


class ScreenCapture:
    """画面映像のキャプチャを担当するクラス.

    dxcam（DXGI Desktop Duplication API）を第一選択として使用し、
    利用不可の場合は mss にフォールバックする。
    time.perf_counter() を使用して 15fps を保証するフレームレート制御を実装する。
    """

    def __init__(self) -> None:
        """ScreenCapture を初期化する."""
        self._frame_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._region: RecordingRegion | None = None
        self._region_lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._latest_frame_lock = threading.Lock()
        self._actual_resolution: tuple[int, int] | None = None  # (width, height)

    # ------------------------------------------------------------------
    # パブリック API
    # ------------------------------------------------------------------

    def start(self, region: RecordingRegion) -> None:
        """指定領域のキャプチャを開始する.

        Args:
            region: キャプチャする画面領域
        """
        with self._region_lock:
            self._region = region

        self._stop_event.clear()

        # dxcam を優先（DXGI Desktop Duplication API で高速・低CPU負荷）
        # dxcam が利用不可の場合は mss にフォールバック
        if dxcam is not None:
            target = self._capture_worker_dxcam
            logger.info("dxcam を使用して画面キャプチャを開始します。")
        elif mss is not None:
            target = self._capture_worker_mss
            logger.info("mss を使用して画面キャプチャを開始します。")
        else:
            logger.error("dxcam も mss も利用不可のため、画面キャプチャを開始できません。")
            return

        self._capture_thread = threading.Thread(target=target, daemon=True)
        self._capture_thread.start()

    def stop(self) -> None:
        """キャプチャを停止する."""
        self._stop_event.set()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=5.0)
            self._capture_thread = None

    def get_frame_queue(self) -> queue.Queue[np.ndarray]:
        """フレームキューを返す（エンコーダが消費する）.

        Returns:
            np.ndarray を格納するキュー。
        """
        return self._frame_queue

    def set_region(self, region: RecordingRegion) -> None:
        """録画領域をリアルタイムで変更する.

        Args:
            region: 新しい録画領域
        """
        with self._region_lock:
            self._region = region

    def get_preview_frame(self) -> np.ndarray | None:
        """プレビュー用の最新フレームを返す."""
        with self._latest_frame_lock:
            return self._latest_frame

    @property
    def actual_resolution(self) -> tuple[int, int] | None:
        """キャプチャ中のフレームの実際の解像度 (width, height) を返す."""
        return self._actual_resolution

    @classmethod
    def get_window_region(cls, hwnd: int) -> RecordingRegion | None:
        """ウィンドウハンドルから RecordingRegion を取得する.

        win32gui.GetWindowRect() でウィンドウ座標を取得する。

        Args:
            hwnd: ウィンドウハンドル

        Returns:
            ウィンドウの RecordingRegion、または取得失敗時は None。
        """
        if win32gui is None:
            logger.warning("win32gui が利用不可のため、ウィンドウ座標を取得できません。")
            return None

        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                logger.warning("ウィンドウのサイズが無効です: width=%d, height=%d", width, height)
                return None
            return RecordingRegion(x=left, y=top, width=width, height=height)
        except Exception:
            logger.exception("ウィンドウ座標の取得中にエラーが発生しました。hwnd=%d", hwnd)
            return None

    # ------------------------------------------------------------------
    # 内部実装
    # ------------------------------------------------------------------

    def _get_current_region(self) -> RecordingRegion | None:
        """現在の録画領域をスレッドセーフに取得する."""
        with self._region_lock:
            return self._region

    def _store_frame(self, frame: np.ndarray) -> None:
        """フレームをキューと最新フレームバッファに格納する."""
        self._frame_queue.put(frame)
        with self._latest_frame_lock:
            self._latest_frame = frame

    @staticmethod
    def _clamp_region_to_display(
        region: RecordingRegion, display_width: int, display_height: int
    ) -> tuple[int, int, int, int] | None:
        """RecordingRegion をディスプレイの物理解像度内にクランプする.

        DPI スケーリング環境ではウィンドウ座標が物理解像度を超える場合があるため、
        dxcam に渡す前に (left, top, right, bottom) を物理解像度内に収める。

        Args:
            region: 録画領域
            display_width: ディスプレイの物理幅（ピクセル）
            display_height: ディスプレイの物理高さ（ピクセル）

        Returns:
            (left, top, right, bottom) タプル、または有効な領域がない場合は None。
        """
        left = max(0, min(region.x, display_width - 1))
        top = max(0, min(region.y, display_height - 1))
        right = max(left + 1, min(region.x + region.width, display_width))
        bottom = max(top + 1, min(region.y + region.height, display_height))

        # クランプ後に有効なサイズがあるか確認
        if right <= left or bottom <= top:
            return None

        return (left, top, right, bottom)

    def _capture_worker_dxcam(self) -> None:
        """dxcam を使用して指定領域をキャプチャするワーカー."""
        camera = None
        try:
            camera = dxcam.create(output_color="BGR")

            # dxcam からディスプレイの物理解像度を取得
            display_width = camera.width
            display_height = camera.height
            logger.info(
                "dxcam ディスプレイ物理解像度: %dx%d", display_width, display_height
            )

            while not self._stop_event.is_set():
                frame_start = time.perf_counter()

                try:
                    region = self._get_current_region()
                    if region is not None:
                        # 物理解像度内にクランプしてから dxcam に渡す
                        clamped = self._clamp_region_to_display(
                            region, display_width, display_height
                        )
                        if clamped is not None:
                            frame = camera.grab(region=clamped)
                        else:
                            logger.warning(
                                "録画領域がディスプレイ範囲外です: x=%d, y=%d, w=%d, h=%d",
                                region.x, region.y, region.width, region.height,
                            )
                            frame = camera.grab()
                    else:
                        frame = camera.grab()

                    if frame is not None:
                        # 実際の解像度を記録
                        h, w = frame.shape[:2]
                        self._actual_resolution = (w, h)
                        self._store_frame(frame)
                except Exception:
                    logger.exception("dxcam フレームのキャプチャ中にエラーが発生しました。")

                # 15fps を保証するフレームレート制御
                elapsed = time.perf_counter() - frame_start
                sleep_time = FRAME_INTERVAL - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except Exception:
            logger.exception("dxcam キャプチャワーカーでエラーが発生しました。")
        finally:
            if camera is not None:
                try:
                    del camera
                except Exception:
                    pass

    def _capture_worker_mss(self) -> None:
        """mss を使用して指定領域をキャプチャするワーカー."""
        try:
            with mss.mss() as sct:
                while not self._stop_event.is_set():
                    frame_start = time.perf_counter()

                    region = self._get_current_region()
                    if region is None:
                        time.sleep(FRAME_INTERVAL)
                        continue

                    # 指定領域をキャプチャ
                    monitor = {
                        "left": region.x,
                        "top": region.y,
                        "width": region.width,
                        "height": region.height,
                    }

                    try:
                        screenshot = sct.grab(monitor)
                        frame = np.array(screenshot)
                        frame = frame[:, :, :3]  # BGRA -> BGR
                        h, w = frame.shape[:2]
                        self._actual_resolution = (w, h)
                        self._store_frame(frame)
                    except Exception:
                        logger.exception("mss フレームのキャプチャ中にエラーが発生しました。")

                    elapsed = time.perf_counter() - frame_start
                    sleep_time = FRAME_INTERVAL - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
        except Exception:
            logger.exception("mss キャプチャワーカーでエラーが発生しました。")
