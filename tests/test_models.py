"""RecordingRegion.clamp() のプロパティテストおよびユニットテスト.

**Validates: Requirements 3.1, 3.2, 3.3**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from screen_audio_recorder.models import RecordingRegion, RecordingMode


# ---------------------------------------------------------------------------
# ユニットテスト
# ---------------------------------------------------------------------------


class TestRecordingRegionClamp:
    """RecordingRegion.clamp() のユニットテスト."""

    def test_clamp_returns_new_instance(self) -> None:
        """clamp() は新しいインスタンスを返す."""
        region = RecordingRegion(x=0, y=0, width=640, height=480)
        clamped = region.clamp(1920, 1080)
        assert clamped is not region

    def test_clamp_preserves_valid_size(self) -> None:
        """有効なサイズはそのまま保持される."""
        region = RecordingRegion(x=0, y=0, width=640, height=480)
        clamped = region.clamp(1920, 1080)
        assert clamped.width == 640
        assert clamped.height == 480

    def test_clamp_enforces_min_width(self) -> None:
        """幅が MIN_WIDTH 未満の場合は MIN_WIDTH にクランプされる."""
        region = RecordingRegion(x=0, y=0, width=100, height=480)
        clamped = region.clamp(1920, 1080)
        assert clamped.width == RecordingRegion.MIN_WIDTH

    def test_clamp_enforces_min_height(self) -> None:
        """高さが MIN_HEIGHT 未満の場合は MIN_HEIGHT にクランプされる."""
        region = RecordingRegion(x=0, y=0, width=640, height=100)
        clamped = region.clamp(1920, 1080)
        assert clamped.height == RecordingRegion.MIN_HEIGHT

    def test_clamp_enforces_max_width(self) -> None:
        """幅がディスプレイ幅を超える場合はディスプレイ幅にクランプされる."""
        region = RecordingRegion(x=0, y=0, width=3000, height=480)
        clamped = region.clamp(1920, 1080)
        assert clamped.width == 1920

    def test_clamp_enforces_max_height(self) -> None:
        """高さがディスプレイ高さを超える場合はディスプレイ高さにクランプされる."""
        region = RecordingRegion(x=0, y=0, width=640, height=2000)
        clamped = region.clamp(1920, 1080)
        assert clamped.height == 1080

    def test_clamp_preserves_position(self) -> None:
        """clamp() は x, y 座標を変更しない."""
        region = RecordingRegion(x=100, y=200, width=640, height=480)
        clamped = region.clamp(1920, 1080)
        assert clamped.x == 100
        assert clamped.y == 200

    def test_clamp_at_exact_min_size(self) -> None:
        """最小サイズちょうどの場合はそのまま保持される."""
        region = RecordingRegion(x=0, y=0, width=320, height=240)
        clamped = region.clamp(1920, 1080)
        assert clamped.width == 320
        assert clamped.height == 240

    def test_clamp_at_exact_display_size(self) -> None:
        """ディスプレイサイズちょうどの場合はそのまま保持される."""
        region = RecordingRegion(x=0, y=0, width=1920, height=1080)
        clamped = region.clamp(1920, 1080)
        assert clamped.width == 1920
        assert clamped.height == 1080

    def test_clamp_both_dimensions_too_small(self) -> None:
        """幅・高さ両方が最小値未満の場合は両方クランプされる."""
        region = RecordingRegion(x=0, y=0, width=10, height=10)
        clamped = region.clamp(1920, 1080)
        assert clamped.width == RecordingRegion.MIN_WIDTH
        assert clamped.height == RecordingRegion.MIN_HEIGHT

    def test_clamp_both_dimensions_too_large(self) -> None:
        """幅・高さ両方がディスプレイサイズを超える場合は両方クランプされる."""
        region = RecordingRegion(x=0, y=0, width=9999, height=9999)
        clamped = region.clamp(1920, 1080)
        assert clamped.width == 1920
        assert clamped.height == 1080


# ---------------------------------------------------------------------------
# プロパティテスト
# ---------------------------------------------------------------------------

# ディスプレイサイズの戦略（MIN_WIDTH/MIN_HEIGHT 以上の値）
display_width_strategy = st.integers(
    min_value=RecordingRegion.MIN_WIDTH, max_value=7680
)
display_height_strategy = st.integers(
    min_value=RecordingRegion.MIN_HEIGHT, max_value=4320
)

# 任意の幅・高さ（負の値や極端に大きい値も含む）
any_width_strategy = st.integers(min_value=-100, max_value=10000)
any_height_strategy = st.integers(min_value=-100, max_value=10000)

# スクロール量（正: 拡大、負: 縮小、ゼロ: 変化なし）
scroll_delta_strategy = st.integers(min_value=-20, max_value=20)


@given(
    initial_width=st.integers(min_value=RecordingRegion.MIN_WIDTH, max_value=3840),
    initial_height=st.integers(min_value=RecordingRegion.MIN_HEIGHT, max_value=2160),
    scroll_delta=scroll_delta_strategy,
    display_width=display_width_strategy,
    display_height=display_height_strategy,
)
@settings(max_examples=200)
def test_scroll_region_bounds(
    initial_width: int,
    initial_height: int,
    scroll_delta: int,
    display_width: int,
    display_height: int,
) -> None:
    """プロパティ 4: スクロールによる領域サイズ変更.

    スクロール量（正・負・ゼロ）に対して、clamp 後のサイズが
    [320×240, display_size] の範囲内に収まることを検証する。

    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    # スクロール量に応じてサイズを変更（1スクロール = 20px）
    step = 20
    new_width = initial_width + scroll_delta * step
    new_height = initial_height + scroll_delta * step

    region = RecordingRegion(x=0, y=0, width=new_width, height=new_height)
    clamped = region.clamp(display_width, display_height)

    # 要件 3.2: 最小サイズは 320×240
    assert clamped.width >= RecordingRegion.MIN_WIDTH, (
        f"width {clamped.width} < MIN_WIDTH {RecordingRegion.MIN_WIDTH}"
    )
    assert clamped.height >= RecordingRegion.MIN_HEIGHT, (
        f"height {clamped.height} < MIN_HEIGHT {RecordingRegion.MIN_HEIGHT}"
    )

    # 要件 3.3: 最大サイズはディスプレイ解像度
    assert clamped.width <= display_width, (
        f"width {clamped.width} > display_width {display_width}"
    )
    assert clamped.height <= display_height, (
        f"height {clamped.height} > display_height {display_height}"
    )


@given(
    width=any_width_strategy,
    height=any_height_strategy,
    display_width=display_width_strategy,
    display_height=display_height_strategy,
)
@settings(max_examples=200)
def test_clamp_always_within_bounds(
    width: int,
    height: int,
    display_width: int,
    display_height: int,
) -> None:
    """任意の幅・高さに対して、clamp 後のサイズが常に有効範囲内に収まる.

    **Validates: Requirements 3.2, 3.3**
    """
    region = RecordingRegion(x=0, y=0, width=width, height=height)
    clamped = region.clamp(display_width, display_height)

    assert RecordingRegion.MIN_WIDTH <= clamped.width <= display_width
    assert RecordingRegion.MIN_HEIGHT <= clamped.height <= display_height


@given(
    x=st.integers(min_value=-1000, max_value=5000),
    y=st.integers(min_value=-1000, max_value=5000),
    width=any_width_strategy,
    height=any_height_strategy,
    display_width=display_width_strategy,
    display_height=display_height_strategy,
)
@settings(max_examples=100)
def test_clamp_preserves_position_property(
    x: int,
    y: int,
    width: int,
    height: int,
    display_width: int,
    display_height: int,
) -> None:
    """clamp() は x, y 座標を変更しない（任意の入力に対して）.

    **Validates: Requirements 3.2, 3.3**
    """
    region = RecordingRegion(x=x, y=y, width=width, height=height)
    clamped = region.clamp(display_width, display_height)

    assert clamped.x == x
    assert clamped.y == y


# ---------------------------------------------------------------------------
# RecordingMode のテスト
# ---------------------------------------------------------------------------


class TestRecordingMode:
    """RecordingMode 列挙型のテスト."""

    def test_screen_and_audio_value(self) -> None:
        """SCREEN_AND_AUDIO の値が正しい."""
        assert RecordingMode.SCREEN_AND_AUDIO.value == "screen_and_audio"

    def test_audio_only_value(self) -> None:
        """AUDIO_ONLY の値が正しい."""
        assert RecordingMode.AUDIO_ONLY.value == "audio_only"

    def test_two_modes_exist(self) -> None:
        """2 つのモードが存在する."""
        assert len(RecordingMode) == 2
