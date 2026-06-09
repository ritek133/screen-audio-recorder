"""AudioCapture のユニットテストおよびプロパティテスト.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6**
"""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from screen_audio_recorder.audio_capture import (
    CHANNELS,
    CHUNK_SIZE,
    SAMPLE_RATE,
    AudioCapture,
    ErrorNotifier,
    MicDevice,
    _pcm16_to_float32,
    mix_audio,
)
from screen_audio_recorder.models import AudioChunk


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def make_float32_audio(
    samples: int = CHUNK_SIZE,
    channels: int = CHANNELS,
    value: float = 0.5,
) -> np.ndarray:
    """テスト用の float32 音声データを生成する."""
    return np.full((samples, channels), value, dtype=np.float32)


# ---------------------------------------------------------------------------
# MicDevice のユニットテスト
# ---------------------------------------------------------------------------


class TestMicDevice:
    """MicDevice dataclass のテスト."""

    def test_fields(self) -> None:
        """index と name フィールドが正しく設定される."""
        device = MicDevice(index=0, name="マイク")
        assert device.index == 0
        assert device.name == "マイク"


# ---------------------------------------------------------------------------
# _pcm16_to_float32 のユニットテスト
# ---------------------------------------------------------------------------


class TestPcm16ToFloat32:
    """_pcm16_to_float32 変換関数のテスト."""

    def test_zero_maps_to_zero(self) -> None:
        """PCM 値 0 は float32 の 0.0 にマップされる."""
        data = np.zeros(CHANNELS * 4, dtype=np.int16).tobytes()
        result = _pcm16_to_float32(data, CHANNELS)
        assert np.allclose(result, 0.0)

    def test_max_positive_maps_to_near_one(self) -> None:
        """PCM 最大値 (32767) は float32 の ~1.0 にマップされる."""
        data = np.full(CHANNELS * 4, 32767, dtype=np.int16).tobytes()
        result = _pcm16_to_float32(data, CHANNELS)
        assert np.all(result > 0.99)
        assert np.all(result <= 1.0)

    def test_output_shape_stereo(self) -> None:
        """ステレオ出力の shape が (samples, 2) になる."""
        n_samples = 8
        data = np.zeros(n_samples * CHANNELS, dtype=np.int16).tobytes()
        result = _pcm16_to_float32(data, CHANNELS)
        assert result.shape == (n_samples, CHANNELS)

    def test_output_dtype_float32(self) -> None:
        """出力の dtype が float32 である."""
        data = np.zeros(CHANNELS * 4, dtype=np.int16).tobytes()
        result = _pcm16_to_float32(data, CHANNELS)
        assert result.dtype == np.float32


# ---------------------------------------------------------------------------
# mix_audio のユニットテスト
# ---------------------------------------------------------------------------


class TestMixAudio:
    """mix_audio 関数のテスト."""

    def test_both_none_returns_zeros(self) -> None:
        """両方 None の場合はゼロ配列を返す."""
        result = mix_audio(None, None)
        assert result.shape == (CHUNK_SIZE, CHANNELS)
        assert np.all(result == 0.0)

    def test_mic_none_returns_sys(self) -> None:
        """mic_data が None の場合は sys_data をそのまま返す."""
        sys_data = make_float32_audio(value=0.3)
        result = mix_audio(None, sys_data)
        assert np.allclose(result, sys_data)

    def test_sys_none_returns_mic(self) -> None:
        """sys_data が None の場合は mic_data をそのまま返す."""
        mic_data = make_float32_audio(value=0.4)
        result = mix_audio(mic_data, None)
        assert np.allclose(result, mic_data)

    def test_mix_is_average(self) -> None:
        """両方存在する場合は平均加算される."""
        mic_data = make_float32_audio(value=0.4)
        sys_data = make_float32_audio(value=0.6)
        result = mix_audio(mic_data, sys_data)
        expected = (0.4 + 0.6) / 2.0
        assert np.allclose(result, expected)

    def test_clipping_prevention(self) -> None:
        """振幅が [-1.0, 1.0] の範囲内に収まる."""
        mic_data = make_float32_audio(value=1.0)
        sys_data = make_float32_audio(value=1.0)
        result = mix_audio(mic_data, sys_data)
        assert np.all(result >= -1.0)
        assert np.all(result <= 1.0)

    def test_negative_clipping_prevention(self) -> None:
        """負の振幅も [-1.0, 1.0] の範囲内に収まる."""
        mic_data = make_float32_audio(value=-1.0)
        sys_data = make_float32_audio(value=-1.0)
        result = mix_audio(mic_data, sys_data)
        assert np.all(result >= -1.0)
        assert np.all(result <= 1.0)

    def test_output_dtype_float32(self) -> None:
        """出力の dtype が float32 である."""
        mic_data = make_float32_audio(value=0.3)
        sys_data = make_float32_audio(value=0.3)
        result = mix_audio(mic_data, sys_data)
        assert result.dtype == np.float32

    def test_independent_buffers_not_modified(self) -> None:
        """ミックス後も元のバッファが変更されていない（独立性）."""
        mic_data = make_float32_audio(value=0.3)
        sys_data = make_float32_audio(value=0.7)
        mic_copy = mic_data.copy()
        sys_copy = sys_data.copy()
        mix_audio(mic_data, sys_data)
        # 元のバッファが変更されていないことを確認
        assert np.allclose(mic_data, mic_copy)
        assert np.allclose(sys_data, sys_copy)


# ---------------------------------------------------------------------------
# 要件 4.5: マイクデバイス利用不可時の動作テスト
# ---------------------------------------------------------------------------


class TestMicDeviceUnavailable:
    """要件 4.5: マイクデバイス利用不可時に警告が表示され SystemAudio のみで継続する."""

    def test_warning_shown_when_mic_unavailable(self) -> None:
        """マイクデバイス利用不可時に show_warning が呼ばれる（要件 4.5）."""
        mock_notifier = MagicMock(spec=ErrorNotifier)
        capture = AudioCapture(error_notifier=mock_notifier)

        # _try_start_mic_thread が False を返す（マイク利用不可）
        # _try_start_system_audio_thread が True を返す（システム音声利用可）
        with (
            patch.object(capture, "_try_start_mic_thread", return_value=False),
            patch.object(capture, "_try_start_system_audio_thread", return_value=True),
            patch.object(capture, "_mix_worker"),  # ミックスワーカーをモック
        ):
            # ミックスワーカースレッドが実際に起動しないようにする
            with patch("threading.Thread") as mock_thread_cls:
                mock_thread = MagicMock()
                mock_thread_cls.return_value = mock_thread
                capture.start(mic_device_index=0, capture_system_audio=True)

        # show_warning が呼ばれたことを確認
        mock_notifier.show_warning.assert_called_once()
        # show_error は呼ばれていないことを確認
        mock_notifier.show_error.assert_not_called()

    def test_recording_continues_with_system_audio_only(self) -> None:
        """マイクデバイス利用不可時に SystemAudio のみで録音が継続する（要件 4.5）."""
        mock_notifier = MagicMock(spec=ErrorNotifier)
        capture = AudioCapture(error_notifier=mock_notifier)

        sys_audio_started = []

        def fake_start_sys():
            sys_audio_started.append(True)
            return True

        with (
            patch.object(capture, "_try_start_mic_thread", return_value=False),
            patch.object(capture, "_try_start_system_audio_thread", side_effect=fake_start_sys),
            patch("threading.Thread") as mock_thread_cls,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            capture.start(mic_device_index=0, capture_system_audio=True)

        # システム音声の起動が試みられたことを確認
        assert len(sys_audio_started) == 1
        # RuntimeError が発生していないことを確認（録音継続）
        mock_notifier.show_error.assert_not_called()


# ---------------------------------------------------------------------------
# 要件 4.6: SystemAudio 取得失敗時の動作テスト
# ---------------------------------------------------------------------------


class TestSystemAudioUnavailable:
    """要件 4.6: SystemAudio 取得失敗時に警告が表示され MicAudio のみで継続する."""

    def test_warning_shown_when_system_audio_fails(self) -> None:
        """SystemAudio 取得失敗時に show_warning が呼ばれる（要件 4.6）."""
        mock_notifier = MagicMock(spec=ErrorNotifier)
        capture = AudioCapture(error_notifier=mock_notifier)

        # _try_start_mic_thread が True を返す（マイク利用可）
        # _try_start_system_audio_thread が False を返す（システム音声利用不可）
        with (
            patch.object(capture, "_try_start_mic_thread", return_value=True),
            patch.object(capture, "_try_start_system_audio_thread", return_value=False),
            patch("threading.Thread") as mock_thread_cls,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            capture.start(mic_device_index=0, capture_system_audio=True)

        # show_warning が呼ばれたことを確認
        mock_notifier.show_warning.assert_called_once()
        # show_error は呼ばれていないことを確認
        mock_notifier.show_error.assert_not_called()

    def test_recording_continues_with_mic_only(self) -> None:
        """SystemAudio 取得失敗時に MicAudio のみで録音が継続する（要件 4.6）."""
        mock_notifier = MagicMock(spec=ErrorNotifier)
        capture = AudioCapture(error_notifier=mock_notifier)

        mic_started = []

        def fake_start_mic(device_index):
            mic_started.append(device_index)
            return True

        with (
            patch.object(capture, "_try_start_mic_thread", side_effect=fake_start_mic),
            patch.object(capture, "_try_start_system_audio_thread", return_value=False),
            patch("threading.Thread") as mock_thread_cls,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            capture.start(mic_device_index=0, capture_system_audio=True)

        # マイクの起動が試みられたことを確認
        assert len(mic_started) == 1
        # RuntimeError が発生していないことを確認（録音継続）
        mock_notifier.show_error.assert_not_called()


# ---------------------------------------------------------------------------
# 両デバイス利用不可時のテスト
# ---------------------------------------------------------------------------


class TestBothDevicesUnavailable:
    """両デバイス利用不可時に show_error が呼ばれ RuntimeError が送出される."""

    def test_error_shown_and_runtime_error_raised(self) -> None:
        """両デバイス利用不可時に show_error が呼ばれ RuntimeError が送出される."""
        mock_notifier = MagicMock(spec=ErrorNotifier)
        capture = AudioCapture(error_notifier=mock_notifier)

        with (
            patch.object(capture, "_try_start_mic_thread", return_value=False),
            patch.object(capture, "_try_start_system_audio_thread", return_value=False),
        ):
            with pytest.raises(RuntimeError):
                capture.start(mic_device_index=0, capture_system_audio=True)

        mock_notifier.show_error.assert_called_once()
        mock_notifier.show_warning.assert_not_called()


# ---------------------------------------------------------------------------
# プロパティテスト: プロパティ 5 — 音声チャンネルの独立性
# ---------------------------------------------------------------------------


# float32 音声データの戦略
audio_data_strategy = st.builds(
    lambda samples, value: np.full((samples, CHANNELS), value, dtype=np.float32),
    samples=st.integers(min_value=1, max_value=4096),
    value=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)


@given(
    mic_value=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    sys_value=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    samples=st.integers(min_value=1, max_value=4096),
)
@settings(max_examples=100)
def test_audio_channel_independence(
    mic_value: float,
    sys_value: float,
    samples: int,
) -> None:
    """プロパティ 5: MicAudio と SystemAudio が独立したバッファに格納されること.

    mix_audio を呼び出した後も、元の MicAudio バッファと SystemAudio バッファが
    変更されていないことを検証する。

    **Validates: Requirements 4.3**
    """
    mic_data = np.full((samples, CHANNELS), mic_value, dtype=np.float32)
    sys_data = np.full((samples, CHANNELS), sys_value, dtype=np.float32)

    # ミックス前のバッファをコピーして保存
    mic_before = mic_data.copy()
    sys_before = sys_data.copy()

    # ミックスを実行
    mix_audio(mic_data, sys_data)

    # ミックス後も元のバッファが変更されていないことを確認（独立性）
    assert np.allclose(mic_data, mic_before), (
        "MicAudio バッファがミックス後に変更されました（独立性違反）"
    )
    assert np.allclose(sys_data, sys_before), (
        "SystemAudio バッファがミックス後に変更されました（独立性違反）"
    )


# ---------------------------------------------------------------------------
# プロパティテスト: プロパティ 6 — 音声ミックスの完全性
# ---------------------------------------------------------------------------


@given(
    mic_value=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    sys_value=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    samples=st.integers(min_value=1, max_value=4096),
)
@settings(max_examples=100)
def test_audio_mix_amplitude_within_bounds(
    mic_value: float,
    sys_value: float,
    samples: int,
) -> None:
    """プロパティ 6: ミックス結果の振幅が [-1.0, 1.0] に収まること.

    任意の MicAudio バッファと SystemAudio バッファに対して、
    ミックス結果の振幅が [-1.0, 1.0] の範囲内に収まることを検証する。

    **Validates: Requirements 4.4**
    """
    mic_data = np.full((samples, CHANNELS), mic_value, dtype=np.float32)
    sys_data = np.full((samples, CHANNELS), sys_value, dtype=np.float32)

    result = mix_audio(mic_data, sys_data)

    # 振幅が [-1.0, 1.0] の範囲内に収まることを確認
    assert np.all(result >= -1.0), (
        f"ミックス結果に -1.0 未満の値が含まれています: min={result.min()}"
    )
    assert np.all(result <= 1.0), (
        f"ミックス結果に 1.0 超の値が含まれています: max={result.max()}"
    )


@given(
    mic_value=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    sys_value=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    samples=st.integers(min_value=1, max_value=4096),
)
@settings(max_examples=100)
def test_audio_mix_shape_and_sample_rate(
    mic_value: float,
    sys_value: float,
    samples: int,
) -> None:
    """プロパティ 6: ミックス結果のサンプル数・チャンネル数が一致すること.

    任意の MicAudio バッファと SystemAudio バッファに対して、
    ミックス結果のサンプル数・チャンネル数が入力と一致することを検証する。

    **Validates: Requirements 4.4**
    """
    mic_data = np.full((samples, CHANNELS), mic_value, dtype=np.float32)
    sys_data = np.full((samples, CHANNELS), sys_value, dtype=np.float32)

    result = mix_audio(mic_data, sys_data)

    # サンプル数が入力と一致する（短い方に合わせる）
    expected_samples = min(mic_data.shape[0], sys_data.shape[0])
    assert result.shape[0] == expected_samples, (
        f"ミックス結果のサンプル数 {result.shape[0]} が期待値 {expected_samples} と一致しません"
    )

    # チャンネル数が CHANNELS と一致する
    assert result.shape[1] == CHANNELS, (
        f"ミックス結果のチャンネル数 {result.shape[1]} が期待値 {CHANNELS} と一致しません"
    )

    # dtype が float32 である
    assert result.dtype == np.float32, (
        f"ミックス結果の dtype {result.dtype} が float32 ではありません"
    )


@given(
    mic_value=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    sys_value=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    samples=st.integers(min_value=1, max_value=4096),
)
@settings(max_examples=100)
def test_audio_mix_contains_both_components(
    mic_value: float,
    sys_value: float,
    samples: int,
) -> None:
    """プロパティ 6: ミックス結果が両方の音声成分を含むこと.

    ミックス結果が MicAudio と SystemAudio の両方の成分を含む
    有効な音声データであることを検証する（平均加算の確認）。

    **Validates: Requirements 4.4**
    """
    mic_data = np.full((samples, CHANNELS), mic_value, dtype=np.float32)
    sys_data = np.full((samples, CHANNELS), sys_value, dtype=np.float32)

    result = mix_audio(mic_data, sys_data)

    # 平均加算の結果が期待値と一致する（クリッピング後）
    expected_raw = (mic_value + sys_value) / 2.0
    expected_clipped = float(np.clip(expected_raw, -1.0, 1.0))

    assert np.allclose(result, expected_clipped, atol=1e-6), (
        f"ミックス結果 {result.flat[0]:.6f} が期待値 {expected_clipped:.6f} と一致しません"
    )


# ---------------------------------------------------------------------------
# AudioCapture.get_audio_queue() のテスト
# ---------------------------------------------------------------------------


class TestGetAudioQueue:
    """get_audio_queue() のテスト."""

    def test_returns_queue_instance(self) -> None:
        """get_audio_queue() が queue.Queue インスタンスを返す."""
        capture = AudioCapture()
        q = capture.get_audio_queue()
        assert isinstance(q, queue.Queue)

    def test_returns_same_queue(self) -> None:
        """get_audio_queue() は常に同じキューを返す."""
        capture = AudioCapture()
        q1 = capture.get_audio_queue()
        q2 = capture.get_audio_queue()
        assert q1 is q2
