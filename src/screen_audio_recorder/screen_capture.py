"""ScreenCapture: 画面映像のキャプチャを担当するクラス.

マルチモニタ環境に対応。録画領域の座標から適切なモニタを自動判定し、
そのモニタ用の dxcam インスタンスを使用してキャプチャする。

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 3.4**
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
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

# win32gui / win32api は Windows 専用ライブラリ
try:
    import win32gui  # type: ignore[import]
except (ImportError, Exception):
    win32gui = None  # type: ignore[assignment]

try:
    import win32api  # type: ignore[import]
except (ImportError, Exception):
    win32api = None  # type: ignore[assignment]

try:
    import ctypes
    import ctypes.wintypes
except (ImportError, Exception):
    ctypes = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# フレームレート定数
TARGET_FPS = 15
FRAME_INTERVAL = 1.0 / TARGET_FPS  # 約 0.0667 秒


@dataclass
class MonitorInfo:
    """モニタ情報を保持するデータクラス.

    Attributes:
        device_idx: dxcam の device_idx (GPU インデックス)
        output_idx: dxcam の output_idx (そのGPU内のモニタインデックス)
        left: 仮想デスクトップ上の左端 X 座標
        top: 仮想デスクトップ上の上端 Y 座標
        width: モニタの物理幅（ピクセル）
        height: モニタの物理高さ（ピクセル）
    """

    device_idx: int
    output_idx: int
    left: int
    top: int
    width: int
    height: int


def _enumerate_monitors() -> list[MonitorInfo]:
    """dxcam のファクトリから各出力のデスクトップ座標を取得してモニタ情報を構築する.

    dxcam の output オブジェクトは desc.DesktopCoordinates に
    仮想デスクトップ上の座標を持っているため、これを使用することで
    win32api.EnumDisplayMonitors との列挙順の不一致問題を回避する。

    Returns:
        MonitorInfo のリスト。取得に失敗した場合は空リスト。
    """
    monitors: list[MonitorInfo] = []

    # 方法1: dxcam のファクトリから直接取得（最も正確）
    if dxcam is not None:
        try:
            factory = getattr(dxcam, "_DXFactory__factory", None) or getattr(dxcam, "__factory", None)
            if factory is not None and hasattr(factory, "outputs"):
                for didx, device_outputs in enumerate(factory.outputs):
                    for oidx, output in enumerate(device_outputs):
                        try:
                            output.update_desc()
                            desc = output.desc
                            coords = desc.DesktopCoordinates
                            left = coords.left
                            top = coords.top
                            width = coords.right - coords.left
                            height = coords.bottom - coords.top
                            if width > 0 and height > 0:
                                monitors.append(MonitorInfo(
                                    device_idx=didx,
                                    output_idx=oidx,
                                    left=left,
                                    top=top,
                                    width=width,
                                    height=height,
                                ))
                        except Exception:
                            logger.debug(
                                "dxcam output[%d][%d] の座標取得に失敗", didx, oidx
                            )
                if monitors:
                    logger.debug("dxcam から検出されたモニタ数: %d", len(monitors))
                    for m in monitors:
                        logger.debug(
                            "  モニタ device=%d output=%d: (%d, %d) %dx%d",
                            m.device_idx, m.output_idx, m.left, m.top, m.width, m.height,
                        )
                    return monitors
        except Exception:
            logger.exception("dxcam ファクトリからのモニタ情報取得に失敗しました。")

    # 方法2: win32api フォールバック（dxcam が使えない場合、output_idx=列挙順と仮定）
    if win32api is not None:
        try:
            raw_monitors = win32api.EnumDisplayMonitors(None, None)
            for idx, (hMonitor, _hdcMonitor, _rect) in enumerate(raw_monitors):
                info = win32api.GetMonitorInfo(hMonitor)
                left, top, right, bottom = info["Monitor"]
                width = right - left
                height = bottom - top
                if width > 0 and height > 0:
                    monitors.append(MonitorInfo(
                        device_idx=0,
                        output_idx=idx,
                        left=left,
                        top=top,
                        width=width,
                        height=height,
                    ))
            logger.debug("win32api から検出されたモニタ数: %d", len(monitors))
        except Exception:
            logger.exception("win32api によるモニタ列挙中にエラーが発生しました。")
    elif ctypes is not None:
        # win32api がない場合は ctypes でフォールバック
        try:
            user32 = ctypes.windll.user32

            monitors_raw: list[tuple[int, int, int, int]] = []

            MONITORENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.wintypes.RECT),
                ctypes.c_void_p,
            )

            def _monitor_enum_callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
                rect = lprcMonitor.contents
                monitors_raw.append((rect.left, rect.top, rect.right, rect.bottom))
                return 1

            callback = MONITORENUMPROC(_monitor_enum_callback)
            user32.EnumDisplayMonitors(None, None, callback, 0)

            for idx, (left, top, right, bottom) in enumerate(monitors_raw):
                width = right - left
                height = bottom - top
                if width > 0 and height > 0:
                    monitors.append(MonitorInfo(
                        device_idx=0,
                        output_idx=idx,
                        left=left,
                        top=top,
                        width=width,
                        height=height,
                    ))
            logger.debug("ctypes から検出されたモニタ数: %d", len(monitors))
        except Exception:
            logger.exception("ctypes によるモニタ列挙中にエラーが発生しました。")

    return monitors


def _find_monitor_for_region(
    region: RecordingRegion, monitors: list[MonitorInfo]
) -> MonitorInfo | None:
    """録画領域の中心座標が属するモニタを特定する.

    Args:
        region: 録画領域（仮想デスクトップ座標）
        monitors: 全モニタのリスト

    Returns:
        最も重なりが大きいモニタ、または見つからない場合は None。
    """
    if not monitors:
        return None

    # 領域の中心座標で判定
    center_x = region.x + region.width // 2
    center_y = region.y + region.height // 2

    for m in monitors:
        if (m.left <= center_x < m.left + m.width and
                m.top <= center_y < m.top + m.height):
            return m

    # 中心が属するモニタがない場合、最も重なり面積が大きいモニタを選択
    best_monitor = None
    best_overlap = 0
    for m in monitors:
        # 重なり計算
        overlap_left = max(region.x, m.left)
        overlap_top = max(region.y, m.top)
        overlap_right = min(region.x + region.width, m.left + m.width)
        overlap_bottom = min(region.y + region.height, m.top + m.height)
        overlap_area = max(0, overlap_right - overlap_left) * max(0, overlap_bottom - overlap_top)
        if overlap_area > best_overlap:
            best_overlap = overlap_area
            best_monitor = m

    return best_monitor


def _virtual_to_local(
    region: RecordingRegion, monitor: MonitorInfo
) -> tuple[int, int, int, int] | None:
    """仮想デスクトップ座標をモニタローカル座標に変換しクランプする.

    Args:
        region: 録画領域（仮想デスクトップ座標）
        monitor: 対象モニタ

    Returns:
        (left, top, right, bottom) のモニタローカル座標タプル。
        有効な領域がない場合は None。
    """
    # 仮想デスクトップ座標をモニタローカルに変換
    local_left = region.x - monitor.left
    local_top = region.y - monitor.top
    local_right = local_left + region.width
    local_bottom = local_top + region.height

    # モニタの物理解像度内にクランプ
    left = max(0, local_left)
    top = max(0, local_top)
    right = min(local_right, monitor.width)
    bottom = min(local_bottom, monitor.height)

    # 有効なサイズチェック
    if right <= left or bottom <= top:
        return None

    # 最小サイズチェック
    if (right - left) < ScreenCapture._MIN_CAPTURE_SIZE or \
       (bottom - top) < ScreenCapture._MIN_CAPTURE_SIZE:
        logger.warning(
            "変換後の領域が小さすぎます: %dx%d (最小 %d 必要)。"
            "モニタ全体にフォールバックします。",
            right - left, bottom - top, ScreenCapture._MIN_CAPTURE_SIZE,
        )
        return None

    return (left, top, right, bottom)


class ScreenCapture:
    """画面映像のキャプチャを担当するクラス.

    dxcam（DXGI Desktop Duplication API）を第一選択として使用し、
    利用不可の場合は mss にフォールバックする。
    マルチモニタ環境では、録画領域の座標から適切なモニタを自動判定する。
    time.perf_counter() を使用して 15fps を保証するフレームレート制御を実装する。
    """

    # 録画に必要な最小ピクセル数（幅・高さそれぞれ）
    _MIN_CAPTURE_SIZE = 16

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
        self._monitors: list[MonitorInfo] = []

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

        # 前回の録画の状態をリセット
        self._actual_resolution = None

        self._stop_event.clear()

        # モニタ情報を取得（毎回再取得し、モニタ構成変更に追従する）
        self._monitors = _enumerate_monitors()

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

        マルチモニタ対応版では _virtual_to_local を使用するため、
        このメソッドはフォールバック（モニタ情報が取れない場合）に使用。

        Args:
            region: 録画領域（モニタローカル座標を想定）
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

        # 幅または高さが最小サイズに満たない場合は無効とみなす
        if (right - left) < ScreenCapture._MIN_CAPTURE_SIZE or \
           (bottom - top) < ScreenCapture._MIN_CAPTURE_SIZE:
            logger.warning(
                "クランプ後の領域が小さすぎます: %dx%d (最小 %d 必要)。"
                "全画面にフォールバックします。",
                right - left, bottom - top, ScreenCapture._MIN_CAPTURE_SIZE,
            )
            return None

        return (left, top, right, bottom)

    def _capture_worker_dxcam(self) -> None:
        """dxcam を使用して指定領域をキャプチャするワーカー.

        dxcam 0.0.5 はマルチモニタでの output_idx 指定が信頼できないため、
        常に device_idx=0, output_idx=None（プライマリモニタ）で作成し、
        録画領域がプライマリモニタ外の場合は mss にフォールバックする。
        """
        camera = None
        target_monitor: MonitorInfo | None = None
        use_mss_fallback = False

        try:
            region = self._get_current_region()

            # dxcam シングルトンキャッシュをクリア
            try:
                factory = getattr(dxcam, "_DXFactory__factory", None) or getattr(dxcam, "__factory", None)
                if factory is not None and hasattr(factory, "_camera_instances"):
                    factory._camera_instances.clear()
            except Exception:
                pass

            # dxcam は常にプライマリモニタで作成
            camera = dxcam.create(output_color="BGR")
            primary_width = camera.width
            primary_height = camera.height

            # プライマリモニタの座標を特定
            primary_monitor = None
            if self._monitors:
                # dxcam の解像度と一致するモニタを探す
                for m in self._monitors:
                    if m.width == primary_width and m.height == primary_height:
                        primary_monitor = m
                        break
                # 解像度が一致するモニタがない場合、位置(0,0)のモニタを優先
                if primary_monitor is None:
                    for m in self._monitors:
                        if m.left == 0 and m.top == 0:
                            primary_monitor = m
                            break

            if primary_monitor is None:
                # フォールバック: (0,0) 起点のプライマリモニタとして扱う
                primary_monitor = MonitorInfo(
                    device_idx=0,
                    output_idx=0,
                    left=0,
                    top=0,
                    width=primary_width,
                    height=primary_height,
                )

            logger.info(
                "dxcam ディスプレイ物理解像度: %dx%d", primary_width, primary_height
            )

            # 録画領域がプライマリモニタの範囲内にあるか確認
            if region is not None:
                local_rect = _virtual_to_local(region, primary_monitor)
                if local_rect is None:
                    # 録画領域がプライマリモニタ外 → mss にフォールバック
                    logger.info(
                        "録画領域がプライマリモニタ外です。mss にフォールバックします。"
                    )
                    use_mss_fallback = True
            else:
                local_rect = None

            if use_mss_fallback:
                # カメラを解放して mss ワーカーに切り替え
                try:
                    factory = getattr(dxcam, "_DXFactory__factory", None) or getattr(dxcam, "__factory", None)
                    if factory is not None and hasattr(factory, "_camera_instances"):
                        factory._camera_instances.clear()
                except Exception:
                    pass
                del camera
                camera = None
                self._capture_worker_mss()
                return

            target_monitor = primary_monitor

            while not self._stop_event.is_set():
                frame_start = time.perf_counter()

                try:
                    region = self._get_current_region()
                    if region is not None:
                        local_rect = _virtual_to_local(region, target_monitor)
                        if local_rect is not None:
                            frame = camera.grab(region=local_rect)
                        else:
                            frame = camera.grab()
                    else:
                        frame = camera.grab()

                    if frame is not None:
                        h, w = frame.shape[:2]
                        self._actual_resolution = (w, h)
                        self._store_frame(frame)
                except Exception:
                    logger.exception("dxcam フレームのキャプチャ中にエラーが発生しました。")

                elapsed = time.perf_counter() - frame_start
                sleep_time = FRAME_INTERVAL - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except Exception:
            logger.exception("dxcam キャプチャワーカーでエラーが発生しました。")
        finally:
            if camera is not None:
                try:
                    try:
                        factory = getattr(dxcam, "_DXFactory__factory", None) or getattr(dxcam, "__factory", None)
                        if factory is not None and hasattr(factory, "_camera_instances"):
                            factory._camera_instances.clear()
                    except Exception:
                        pass
                    del camera
                except Exception:
                    pass

    def _capture_worker_mss(self) -> None:
        """mss を使用して指定領域をキャプチャするワーカー.

        mss は仮想デスクトップ座標をそのまま受け付けるため、
        マルチモニタでも座標変換は不要。
        """
        try:
            with mss.mss() as sct:
                while not self._stop_event.is_set():
                    frame_start = time.perf_counter()

                    region = self._get_current_region()
                    if region is None:
                        time.sleep(FRAME_INTERVAL)
                        continue

                    # 指定領域をキャプチャ（mss は仮想デスクトップ座標を直接受け付ける）
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
