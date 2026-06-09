"""VideoEncoder のユニットテスト.

**Validates: Requirements 2.5, 5.3**
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from screen_audio_recorder.models import AudioChunk, RecordingMode
from screen_audio_recorder.video_encoder import VideoEncoder, _find_ffmpeg


# ---------------------------------------------------------------------------
# 全テストで _find_ffmpeg をモックする
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_find_ffmpeg():
    with patch("screen_audio_recorder.video_encoder._find_ffmpeg", return_value="ffmpeg"):
        with patch("screen_audio_recorder.video_encoder._detect_hw_encoder", return_value=None):
            yield


def make_mock_process(returncode: int = 0, stderr: bytes = b"") -> MagicMock:
    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stderr = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.communicate.return_value = (b"", stderr)
    return mock_proc


def make_audio_chunk(samples: int = 1024, channels: int = 2, value: float = 0.5) -> AudioChunk:
    data = np.full((samples, channels), value, dtype=np.float32)
    return AudioChunk(data=data, sample_rate=44100, timestamp=0.0)


# ---------------------------------------------------------------------------
# SCREEN_AND_AUDIO モードのテスト
# ---------------------------------------------------------------------------


class TestVideoEncoderScreenAndAudioMode:

    def test_start_creates_video_process(self, tmp_path: Path) -> None:
        encoder = VideoEncoder()
        output_path = tmp_path / "test.mp4"

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = make_mock_process()
            encoder.start(output_path, 15, (1920, 1080), RecordingMode.SCREEN_AND_AUDIO)

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert "libx264" in cmd
        assert "bgr24" in cmd
        assert "yuv420p" in cmd

    def test_start_records_wav_path(self, tmp_path: Path) -> None:
        """SCREEN_AND_AUDIO モードでは WAV パスを記録するが、ファイルは作成しない.

        WAV ファイルの作成・書き込みは AudioCapture が担当する。
        """
        encoder = VideoEncoder()
        output_path = tmp_path / "test.mp4"

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = make_mock_process()
            encoder.start(output_path, 15, (1920, 1080), RecordingMode.SCREEN_AND_AUDIO)

        assert encoder._audio_wav_path == output_path.with_suffix(".audio.wav")
        # WAV ファイル自体は AudioCapture が作成するので encoder は作らない
        assert encoder._audio_wav is None

    def test_write_frame_writes_to_video_process(self, tmp_path: Path) -> None:
        encoder = VideoEncoder()
        output_path = tmp_path / "test.mp4"
        mock_proc = make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc):
            encoder.start(output_path, 15, (640, 480), RecordingMode.SCREEN_AND_AUDIO)

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        encoder.write_frame(frame)

        # パイプ書き込みは別スレッドで行われるため、少し待つ
        import time
        time.sleep(0.5)

        # write が1回以上呼ばれることを確認
        assert mock_proc.stdin.write.call_count >= 1
        # 書き込まれた全バイトを結合してフレームデータと一致することを確認
        written = b"".join(call.args[0] for call in mock_proc.stdin.write.call_args_list)
        assert written == frame.tobytes()

    def test_write_audio_noop_in_screen_and_audio_mode(self, tmp_path: Path) -> None:
        """SCREEN_AND_AUDIO モードでは encoder の write_audio は何もしない.

        音声の WAV 書き込みは AudioCapture が直接行う。
        """
        encoder = VideoEncoder()
        output_path = tmp_path / "test.mp4"

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = make_mock_process()
            encoder.start(output_path, 15, (640, 480), RecordingMode.SCREEN_AND_AUDIO)

        chunk = make_audio_chunk()
        # _audio_wav が None なので write_audio はスキップされる（エラーにならない）
        encoder.write_audio(chunk)


# ---------------------------------------------------------------------------
# AUDIO_ONLY モードのテスト
# ---------------------------------------------------------------------------


class TestVideoEncoderAudioOnlyMode:

    def test_start_audio_only_creates_wav(self, tmp_path: Path) -> None:
        """AUDIO_ONLY モードで WAV ファイルが作成される."""
        encoder = VideoEncoder()
        output_path = tmp_path / "test.mp3"
        encoder.start(output_path, 15, (1920, 1080), RecordingMode.AUDIO_ONLY)

        wav_path = output_path.with_suffix(".raw.wav")
        assert wav_path.exists()
        encoder._audio_wav.close()

    def test_write_audio_writes_to_wav(self, tmp_path: Path) -> None:
        """AUDIO_ONLY モードで音声データが WAV に書き込まれる."""
        encoder = VideoEncoder()
        output_path = tmp_path / "test.mp3"
        encoder.start(output_path, 15, (1920, 1080), RecordingMode.AUDIO_ONLY)

        chunk = make_audio_chunk()
        encoder.write_audio(chunk)

        wav_path = output_path.with_suffix(".raw.wav")
        encoder._audio_wav.close()
        assert wav_path.stat().st_size > 44

    def test_audio_only_no_video_process(self, tmp_path: Path) -> None:
        """AUDIO_ONLY モードで映像プロセスが起動されない."""
        encoder = VideoEncoder()
        output_path = tmp_path / "test.mp3"
        encoder.start(output_path, 15, (1920, 1080), RecordingMode.AUDIO_ONLY)

        assert encoder._video_process is None
        encoder._audio_wav.close()


# ---------------------------------------------------------------------------
# finish() のテスト
# ---------------------------------------------------------------------------


class TestFinish:

    def test_finish_audio_only_returns_path(self, tmp_path: Path) -> None:
        encoder = VideoEncoder()
        output_path = tmp_path / "test.wav"  # WAV なら変換不要でそのまま
        encoder.start(output_path, 15, (1920, 1080), RecordingMode.AUDIO_ONLY)

        # データを書き込む
        chunk = make_audio_chunk()
        encoder.write_audio(chunk)

        result = encoder.finish()
        # WAV 出力の場合はリネームされるので存在確認
        assert result.exists() or result.with_suffix(".wav").exists()

    def test_finish_without_start_raises(self) -> None:
        encoder = VideoEncoder()
        with pytest.raises(RuntimeError):
            encoder.finish()

    def test_write_frame_without_start_no_error(self) -> None:
        encoder = VideoEncoder()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        encoder.write_frame(frame)  # no error

    def test_write_audio_without_start_no_error(self) -> None:
        encoder = VideoEncoder()
        chunk = make_audio_chunk()
        encoder.write_audio(chunk)  # no error


# ---------------------------------------------------------------------------
# _find_ffmpeg() のテスト
# ---------------------------------------------------------------------------


class TestFindFfmpeg:

    def test_returns_internal_when_exists(self, tmp_path: Path) -> None:
        fake = tmp_path / "ffmpeg.exe"
        fake.touch()
        with patch("screen_audio_recorder.video_encoder._FFMPEG_INTERNAL", fake):
            result = _find_ffmpeg()
        assert result == str(fake)

    def test_returns_something_when_internal_not_exists(self) -> None:
        with patch("screen_audio_recorder.video_encoder._FFMPEG_INTERNAL", Path("/nonexistent")):
            result = _find_ffmpeg()
        assert isinstance(result, str)
        assert len(result) > 0
