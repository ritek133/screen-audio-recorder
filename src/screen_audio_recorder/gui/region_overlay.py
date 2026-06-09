"""RegionOverlay: 録画領域を赤枠で表示し、ドラッグ移動・リサイズ可能にするクラス.

録画開始前に表示し、ユーザーが録画範囲を決定する。
録画中は非表示にする（画面が黒くなる問題を防ぐ）。
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import TYPE_CHECKING

from screen_audio_recorder.models import RecordingRegion

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_BORDER_WIDTH = 4
_BORDER_COLOR = "red"
_MIN_SIZE = 320
_RESIZE_HANDLE = 16  # リサイズハンドルのサイズ


class RegionOverlay:
    """録画領域を赤枠で表示し、ドラッグ移動・リサイズ可能にするクラス.

    - ドラッグで移動
    - 右下角のドラッグでリサイズ
    - スクロールでサイズ変更
    """

    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._overlay: tk.Toplevel | None = None
        self._region = RecordingRegion(x=100, y=100, width=800, height=600)

        # ドラッグ状態
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._is_resizing = False

    @property
    def region(self) -> RecordingRegion:
        """現在の録画領域を返す."""
        return self._region

    def show(self) -> None:
        """赤枠オーバーレイを表示する."""
        if self._overlay is not None:
            return

        self._overlay = tk.Toplevel(self._root)
        self._overlay.overrideredirect(True)
        self._overlay.attributes("-topmost", True)
        self._overlay.attributes("-alpha", 0.3)
        self._overlay.configure(bg="black")

        # 赤枠を描画するキャンバス
        self._canvas = tk.Canvas(
            self._overlay,
            bg="black",
            highlightthickness=_BORDER_WIDTH,
            highlightbackground=_BORDER_COLOR,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # リサイズハンドル（右下角）
        self._canvas.create_rectangle(
            0, 0, _RESIZE_HANDLE, _RESIZE_HANDLE,
            fill="red", outline="red", tags="resize_handle"
        )

        # イベントバインド
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<MouseWheel>", self._on_scroll)

        self._update_geometry()

    def hide(self) -> None:
        """オーバーレイを非表示にする."""
        if self._overlay is not None:
            self._overlay.destroy()
            self._overlay = None
            self._canvas = None

    def _update_geometry(self) -> None:
        """ウィンドウの位置とサイズを更新する."""
        if self._overlay is None:
            return
        r = self._region
        self._overlay.geometry(f"{r.width}x{r.height}+{r.x}+{r.y}")

        # リサイズハンドルを右下に配置
        if self._canvas is not None:
            self._canvas.delete("resize_handle")
            self._canvas.create_rectangle(
                r.width - _RESIZE_HANDLE - _BORDER_WIDTH,
                r.height - _RESIZE_HANDLE - _BORDER_WIDTH,
                r.width - _BORDER_WIDTH,
                r.height - _BORDER_WIDTH,
                fill="red", outline="darkred", tags="resize_handle"
            )

    def _on_press(self, event: tk.Event) -> None:
        """マウスボタン押下."""
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root

        # 右下角付近ならリサイズモード
        r = self._region
        if (event.x > r.width - _RESIZE_HANDLE - _BORDER_WIDTH * 2 and
                event.y > r.height - _RESIZE_HANDLE - _BORDER_WIDTH * 2):
            self._is_resizing = True
        else:
            self._is_resizing = False

    def _on_drag(self, event: tk.Event) -> None:
        """ドラッグ中."""
        dx = event.x_root - self._drag_start_x
        dy = event.y_root - self._drag_start_y
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root

        r = self._region

        if self._is_resizing:
            # リサイズ
            new_w = max(_MIN_SIZE, r.width + dx)
            new_h = max(_MIN_SIZE, r.height + dy)
            self._region = RecordingRegion(x=r.x, y=r.y, width=new_w, height=new_h)
        else:
            # 移動
            self._region = RecordingRegion(x=r.x + dx, y=r.y + dy, width=r.width, height=r.height)

        self._update_geometry()

    def _on_release(self, event: tk.Event) -> None:
        """マウスボタン解放."""
        self._is_resizing = False

    def _on_scroll(self, event: tk.Event) -> None:
        """スクロールでサイズ変更."""
        step = 40
        delta = 1 if event.delta > 0 else -1
        r = self._region
        new_w = max(_MIN_SIZE, r.width + delta * step)
        new_h = max(_MIN_SIZE, r.height + delta * step)
        self._region = RecordingRegion(x=r.x, y=r.y, width=new_w, height=new_h)
        self._update_geometry()
