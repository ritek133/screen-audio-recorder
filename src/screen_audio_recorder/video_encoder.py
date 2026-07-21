"""VideoEncoder: ffmpeg を使用した映像・音声エンコードを担当するクラス.

映像+音声モードでは映像のみ ffmpeg に書き込み、音声は別 WAV ファイルに保存。
finish() で映像と音声を結合して最終 MP4 を生成する。

**Validates: Requirements 2.5, 5.3**
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

# Windows でサブプロセスのコンソールウィンドウを非表示にするフラグ
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

from screen_audio_recorder.models import AudioChunk, RecordingMode

logger = logging.getLogger(__name__)

_FFMPEG_INTERNAL = Path(sys.executable).parent / "_internal" / "ffmpeg.exe"
_FFMPEG_FALLBACK = "ffmpeg"


def _find_ffmpeg() -> str:
    """ffmpeg バイナリのパスを返す."""
    if _FFMPEG_INTERNAL.exists():
        return str(_FFMPEG_INTERNAL)
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg_path = get_ffmpeg_exe()
        if ffmpeg_path and Path(ffmpeg_path).exists():
            return ffmpeg_path
    except ImportError:
        pass
    return _FFMPEG_FALLBACK


def _detect_hw_encoder(ffmpeg_bin: str) -> str | None:
    """利用可能なハードウェアエンコーダを自動検出する.

    各エンコーダに対して実際にテストエンコードを実行し、
    動作するものを返す。環境に応じて最適なエンコーダが自動選択される。

    優先順位:
        1. h264_nvenc  — NVIDIA GPU (NVENC)。最も高速。
        2. h264_amf   — AMD GPU (AMF/VCN)。RX 5000+ / Ryzen 5000+ APU。
        3. h264_qsv    — Intel 内蔵 GPU (Quick Sync Video)。
        4. None        — CPU フォールバック (libx264 ultrafast)。

    注意: h264_mf (Media Foundation) は内部バッファリング遅延が大きく
    リアルタイム録画で映像が数秒遅れるため、候補から除外している。

    Returns:
        エンコーダ名、またはハードウェアエンコーダが利用不可の場合は None。
    """
    import tempfile

    # h264_mf は除外（バッファリング遅延が大きくリアルタイム録画に不向き）
    candidates = ["h264_nvenc", "h264_amf", "h264_qsv"]

    try:
        result = subprocess.run(
            [ffmpeg_bin, "-encoders"],
            capture_output=True, timeout=10,
            creationflags=_SUBPROCESS_FLAGS,
        )
        available = result.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None

    for encoder in candidates:
        if encoder not in available:
            continue
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp_path = tmp.name

            test_cmd = [
                ffmpeg_bin, "-y",
                "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1:r=15",
                "-c:v", encoder,
            ]
            if encoder == "h264_qsv":
                test_cmd += ["-pix_fmt", "nv12"]
            elif encoder == "h264_nvenc":
                test_cmd += ["-pix_fmt", "yuv420p"]
            elif encoder == "h264_amf":
                test_cmd += ["-pix_fmt", "nv12"]

            test_cmd += [tmp_path]

            test_result = subprocess.run(
                test_cmd,
                capture_output=True, timeout=15,
                creationflags=_SUBPROCESS_FLAGS,
            )
            Path(tmp_path).unlink(missing_ok=True)

            if test_result.returncode == 0:
                logger.debug("HW エンコーダテスト成功: %s", encoder)
                return encoder
            else:
                err = test_result.stderr.decode("utf-8", errors="replace")[:200]
                logger.debug("HW エンコーダテスト失敗: %s — %s", encoder, err)
        except Exception as e:
            logger.debug("HW エンコーダテスト例外: %s — %s", encoder, e)
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
            continue

    return None


class VideoEncoder:
    """映像・音声エンコードを担当するクラス.

    SCREEN_AND_AUDIO モード:
        - 映像: rawvideo → ffmpeg stdin → 無音 MP4
        - 音声: PCM データを WAV ファイルに直接書き込み
        - finish() で映像 MP4 + 音声 WAV を結合して最終 MP4 を生成

    AUDIO_ONLY モード:
        - 音声: PCM データを ffmpeg stdin → MP3/WAV
    """

    def __init__(self, error_notifier=None) -> None:
        self._error_notifier = error_notifier
        self._video_process: subprocess.Popen | None = None
        self._audio_wav: wave.Wave_write | None = None
        self._audio_wav_path: Path | None = None
        self._video_tmp_path: Path | None = None
        self._output_path: Path | None = None
        self._mode: RecordingMode | None = None
        self._fps: int = 15
        self._resolution: tuple[int, int] = (1920, 1080)
        self._capture_resolution: tuple[int, int] = (1920, 1080)
        self._audio_process: subprocess.Popen | None = None
        self._audio_delay: float = 0.0
        self._frame_count: int = 0
        self._recording_wall_time: float = 0.0
        self._recording_start_time: float | None = None
        # パイプ書き込み専用スレッド（write_frame のブロックを防ぐ）
        import queue as _queue
        self._pipe_queue: _queue.Queue[bytes | None] = _queue.Queue(maxsize=30)
        self._pipe_thread: threading.Thread | None = None
        # パイプ書き込みの累積遅延（秒）。キューが満杯でフレームを捨てた回数から計算。
        self._pipe_dropped_frames: int = 0
        # パイプライタースレッドが最初のフレームを書き込み完了した時のイベント
        self._first_pipe_write_done = threading.Event()
        # 映像先頭トリム量（秒）。一番遅いストリームに合わせる。
        self._video_trim: float = 0.0
        # ハードウェアエンコーダ検出（初期化時に実行）
        ffmpeg_bin = _find_ffmpeg()
        self._hw_encoder = _detect_hw_encoder(ffmpeg_bin)
        if self._hw_encoder:
            logger.info("ハードウェアエンコーダを検出: %s", self._hw_encoder)
        else:
            logger.info("ハードウェアエンコーダなし。CPU エンコード (libx264 veryfast) を使用")

    def set_audio_delay(self, delay: float) -> None:
        """音声の開始遅延を設定する（結合時のオフセット補正用）.

        Args:
            delay: 音声が映像より遅れて開始した秒数。正の値。
        """
        self._audio_delay = delay

    def mark_recording_end(self) -> None:
        """録画終了時刻を記録する.

        stop_recording() から即座に呼ばれる。
        audio_capture.stop() のハング時間を壁時計時間に含めないため。
        """
        if self._recording_start_time is not None:
            self._recording_wall_time = time.perf_counter() - self._recording_start_time
            logger.debug("録画終了マーク: 壁時計時間 %.3f 秒", self._recording_wall_time)

    def set_video_trim(self, trim_seconds: float) -> None:
        """映像先頭のトリム量を設定する.

        一番遅いストリーム（通常はマイク）に合わせて映像の先頭をトリムする。

        Args:
            trim_seconds: トリムする秒数。
        """
        self._video_trim = trim_seconds

    def start(
        self,
        output_path: Path,
        fps: int,
        resolution: tuple[int, int],
        mode: RecordingMode,
    ) -> None:
        self._output_path = output_path
        self._fps = fps
        self._resolution = resolution
        self._mode = mode
        self._frame_count = 0
        self._capture_resolution = resolution
        self._pipe_dropped_frames = 0
        self._video_trim = 0.0
        self._recording_start_time = None
        self._recording_wall_time = 0.0
        self._first_pipe_write_done.clear()

        ffmpeg_bin = _find_ffmpeg()
        width, height = resolution

        # libx264 は幅・高さが2の倍数でないとエラーになるため丸める
        width = width & ~1
        height = height & ~1

        # 最小解像度チェック: ffmpeg が処理できない極小サイズを拒否
        if width < 2 or height < 2:
            raise ValueError(
                f"映像解像度が無効です: {width}x{height} "
                f"(元: {resolution[0]}x{resolution[1]})。"
                "録画領域が画面外にある可能性があります。"
            )

        self._resolution = (width, height)

        if mode == RecordingMode.SCREEN_AND_AUDIO:
            self._video_tmp_path = output_path.with_suffix(".video.mp4")

            # ffmpeg コマンドを構築
            # キャプチャ元の解像度のまま rawvideo を受け取り、
            # 高解像度の場合は ffmpeg 側で scale してからエンコードする。
            video_cmd = [
                ffmpeg_bin, "-y",
                "-f", "rawvideo",
                "-vcodec", "rawvideo",
                "-s", f"{width}x{height}",
                "-pix_fmt", "bgr24",
                "-r", str(fps),
                "-i", "pipe:0",
                "-an",
            ]

            # 高解像度の場合は ffmpeg 側でリサイズ
            max_w, max_h = 1920, 1080
            if width > max_w or height > max_h:
                video_cmd += ["-vf", f"scale={max_w}:-2"]
                logger.debug("ffmpeg 側で %dx%d → 最大 %dx%d にリサイズします",
                            width, height, max_w, max_h)

            # エンコーダ設定
            if self._hw_encoder == "h264_nvenc":
                video_cmd += [
                    "-vcodec", "h264_nvenc",
                    "-preset", "p1",
                    "-cq", "23",
                    "-pix_fmt", "yuv420p",
                ]
            elif self._hw_encoder == "h264_qsv":
                video_cmd += [
                    "-vcodec", "h264_qsv",
                    "-global_quality", "23",
                    "-pix_fmt", "nv12",
                ]
            else:
                video_cmd += [
                    "-vcodec", "libx264",
                    "-preset", "veryfast",
                    "-crf", "18",
                    "-pix_fmt", "yuv420p",
                ]

            video_cmd += [str(self._video_tmp_path)]
            logger.debug("映像 ffmpeg: %s", " ".join(video_cmd))
            self._video_process = subprocess.Popen(
                video_cmd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=_SUBPROCESS_FLAGS,
            )

            # パイプ書き込み専用スレッドを起動
            # write_frame() はキューに入れるだけで即座に返る
            self._pipe_thread = threading.Thread(
                target=self._pipe_writer_worker, daemon=True,
            )
            self._pipe_thread.start()

            self._audio_wav_path = output_path.with_suffix(".audio.wav")

        elif mode == RecordingMode.AUDIO_ONLY:
            self._audio_wav_path = output_path.with_suffix(".raw.wav")
            self._audio_wav = wave.open(str(self._audio_wav_path), "wb")
            self._audio_wav.setnchannels(2)
            self._audio_wav.setsampwidth(2)
            self._audio_wav.setframerate(44100)

    def write_frame(self, frame: np.ndarray) -> None:
        """映像フレームを書き込む（SCREEN_AND_AUDIO モードのみ）.

        フレームデータをパイプ書き込みキューに入れて即座に返る。
        実際のパイプ書き込みは _pipe_writer_worker スレッドが行う。
        キューが満杯の場合は古いフレームを捨てて最新を入れる。
        """
        if self._video_process is None or self._video_process.stdin is None:
            return

        try:
            # チャンネル数を確認（BGRA → BGR 変換）
            if frame.ndim == 3 and frame.shape[2] == 4:
                frame = frame[:, :, :3]

            h, w = frame.shape[:2]
            exp_w, exp_h = self._resolution

            # フレームサイズが期待と異なる場合はクロップ/パディング
            if w != exp_w or h != exp_h:
                new_frame = np.zeros((exp_h, exp_w, 3), dtype=np.uint8)
                copy_h = min(h, exp_h)
                copy_w = min(w, exp_w)
                new_frame[:copy_h, :copy_w] = frame[:copy_h, :copy_w]
                frame = new_frame

            data = frame.tobytes()
            expected_size = exp_w * exp_h * 3
            if len(data) != expected_size:
                logger.error(
                    "フレームバイト数不一致: got=%d, expected=%d (frame shape=%s)",
                    len(data), expected_size, frame.shape,
                )
                return

            # キューに入れる（満杯なら古いフレームを捨てて最新を入れる）
            import queue as _queue
            try:
                self._pipe_queue.put_nowait(data)
            except _queue.Full:
                try:
                    self._pipe_queue.get_nowait()
                except _queue.Empty:
                    pass
                try:
                    self._pipe_queue.put_nowait(data)
                except _queue.Full:
                    pass
                self._pipe_dropped_frames += 1

            self._frame_count += 1
            if self._recording_start_time is None:
                self._recording_start_time = time.perf_counter()
        except Exception as e:
            logger.error("映像フレーム処理エラー: %s", e)

    def _pipe_writer_worker(self) -> None:
        """パイプ書き込み専用ワーカー.

        キューからフレームデータを取り出して ffmpeg の stdin に書き込む。
        write_frame() がブロックされないよう、書き込みはこのスレッドで行う。
        最初の書き込み完了時に _first_pipe_write_done をセットする。
        None を受け取ったら終了する。
        """
        first_done = False
        while True:
            try:
                data = self._pipe_queue.get(timeout=1.0)
                if data is None:
                    break
                if self._video_process is not None and self._video_process.stdin is not None:
                    self._video_process.stdin.write(data)
                    if not first_done:
                        first_done = True
                        self._first_pipe_write_done.set()
            except Exception:
                if self._video_process is None:
                    break

    def write_audio(self, audio_chunk: AudioChunk) -> None:
        """音声チャンクを書き込む."""
        pcm_data = (audio_chunk.data * 32767.0).clip(-32768, 32767).astype(np.int16)
        pcm_bytes = pcm_data.tobytes()

        # 両モードとも WAV ファイルに直接書き込み（途切れ防止）
        if self._audio_wav is not None:
            try:
                self._audio_wav.writeframes(pcm_bytes)
            except Exception as e:
                logger.error("WAV 書き込みエラー: %s", e)

    def finish(self) -> Path:
        """エンコードを完了し OutputFile パスを返す."""
        if self._output_path is None:
            raise RuntimeError("出力パスが設定されていません。")

        if self._mode == RecordingMode.SCREEN_AND_AUDIO:
            return self._finish_screen_and_audio()
        elif self._mode == RecordingMode.AUDIO_ONLY:
            return self._finish_audio_only()
        else:
            raise RuntimeError(f"未知のモード: {self._mode}")

    def _probe_duration(self, file_path: Path) -> float | None:
        """ffmpeg でファイルの長さ（秒）を取得する.

        imageio_ffmpeg には ffprobe が含まれないため、
        ffmpeg 自体を使って長さを取得する。
        """
        # 方法1: WAV ファイルの場合は wave モジュールで直接取得（最も確実）
        if file_path.suffix.lower() == ".wav":
            try:
                with wave.open(str(file_path), "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    if rate > 0:
                        duration = frames / rate
                        return duration
            except Exception:
                pass

        # 方法2: ffmpeg -i で情報を取得（MP4 等）
        try:
            ffmpeg_bin = _find_ffmpeg()
            result = subprocess.run(
                [ffmpeg_bin, "-i", str(file_path)],
                capture_output=True, timeout=30,
                creationflags=_SUBPROCESS_FLAGS,
            )
            # ffmpeg -i は入力のみだと returncode != 0 だが stderr に情報が出る
            stderr_text = result.stderr.decode("utf-8", errors="replace")
            # "Duration: HH:MM:SS.ss" を探す
            import re
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", stderr_text)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = int(match.group(3))
                centiseconds = int(match.group(4))
                duration = hours * 3600 + minutes * 60 + seconds + centiseconds / 100.0
                return duration
        except Exception:
            pass
        return None

    def _finish_screen_and_audio(self) -> Path:
        """映像+音声モードの完了処理。映像 MP4 と音声 WAV を結合する。

        同期方針:
            _video_capture_worker が 1/fps 間隔で正確にフレームを書き込むため、
            映像の長さは実時間と一致する。結合時は単純にストリームを合わせ、
            -shortest で短い方に合わせて末尾を切る。
            音声の開始遅延（_audio_delay）は -itsoffset で補正する。

        音声 WAV は AudioCapture が管理・クローズ済みであること。
        """
        # 録画の壁時計時間（mark_recording_end() で記録済みの場合はそちらを使用）
        if self._recording_wall_time <= 0 and self._recording_start_time is not None:
            self._recording_wall_time = time.perf_counter() - self._recording_start_time
        logger.debug("録画の壁時計時間: %.3f 秒, 書き込みフレーム数: %d, 期待フレーム数: %d",
                     self._recording_wall_time, self._frame_count,
                     int(self._recording_wall_time * self._fps))

        # パイプ書き込みスレッドを停止
        if self._pipe_thread is not None:
            # 終了シグナル（None）をキューに入れる
            try:
                self._pipe_queue.put(None, timeout=5.0)
            except Exception:
                pass
            self._pipe_thread.join(timeout=10.0)
            self._pipe_thread = None

        # 映像 ffmpeg を終了
        if self._video_process is not None:
            if self._video_process.stdin is not None:
                self._video_process.stdin.close()
            stdout, stderr = self._video_process.communicate()
            if self._video_process.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")[:300]
                logger.error("映像エンコードエラー: %s", err)
            self._video_process = None

        # 映像と音声の長さを診断ログに出力
        video_dur = None
        audio_dur = None
        if self._video_tmp_path and self._video_tmp_path.exists():
            video_dur = self._probe_duration(self._video_tmp_path)
            logger.debug("映像一時ファイルの長さ: %s 秒 (path=%s)",
                        f"{video_dur:.3f}" if video_dur else "不明", self._video_tmp_path)
        if self._audio_wav_path and self._audio_wav_path.exists():
            audio_dur = self._probe_duration(self._audio_wav_path)
            logger.debug("音声 WAV の長さ: %s 秒 (path=%s)",
                        f"{audio_dur:.3f}" if audio_dur else "不明", self._audio_wav_path)
        if video_dur and audio_dur:
            logger.debug("映像-音声の長さの差: %.3f 秒 (映像=%.3f, 音声=%.3f)",
                        video_dur - audio_dur, video_dur, audio_dur)
        logger.debug("音声開始遅延 (_audio_delay): %.3f 秒", self._audio_delay)

        # 映像 + 音声を結合
        # 音声マージでリネーム失敗した場合のフォールバック: .merged.wav を探す
        if self._audio_wav_path and not self._audio_wav_path.exists():
            merged_fallback = Path(str(self._audio_wav_path) + ".merged.wav")
            if merged_fallback.exists():
                logger.debug("音声 WAV フォールバック: %s を使用", merged_fallback)
                self._audio_wav_path = merged_fallback

        if (
            self._video_tmp_path and self._video_tmp_path.exists()
            and self._audio_wav_path and self._audio_wav_path.exists()
        ):
            ffmpeg_bin = _find_ffmpeg()

            # 同期オフセットを計算
            # 1. 映像先頭トリム: 一番遅いストリームに合わせて映像の先頭をカット
            # 2. パイプ遅延: write_frame のブロックで映像内容が遅れた分を音声で補正
            pipe_delay = self._pipe_dropped_frames * (1.0 / self._fps)
            total_video_trim = self._video_trim + pipe_delay
            logger.debug("同期オフセット: 映像トリム=%.3f 秒 (開始差=%.3f + パイプ遅延=%.3f, ドロップ=%d)",
                        total_video_trim, self._video_trim, pipe_delay, self._pipe_dropped_frames)

            merge_cmd = [ffmpeg_bin, "-y"]

            # 映像の先頭をトリム（開始時刻差 + パイプ遅延）
            if total_video_trim > 0.01:
                merge_cmd += ["-ss", f"{total_video_trim:.3f}"]

            merge_cmd += ["-i", str(self._video_tmp_path)]
            merge_cmd += ["-i", str(self._audio_wav_path)]
            # 映像は既に H.264 エンコード済みなのでコピー（再エンコード不要で高速）
            merge_cmd += ["-c:v", "copy"]
            merge_cmd += ["-c:a", "aac", "-b:a", "128k"]
            merge_cmd += ["-shortest"]
            merge_cmd += [str(self._output_path)]

            logger.debug("結合 ffmpeg: %s", " ".join(merge_cmd))
            try:
                # -c:v copy なので長時間録画でも短時間で完了する（最低60秒、録画1分あたり+5秒）
                encode_timeout = max(60, int(self._recording_wall_time / 12) + 60)
                result = subprocess.run(
                    merge_cmd, capture_output=True, timeout=encode_timeout,
                    creationflags=_SUBPROCESS_FLAGS,
                )
                if result.returncode != 0:
                    err = result.stderr.decode("utf-8", errors="replace")[:300]
                    logger.error("結合エラー: %s", err)
                else:
                    logger.info("映像+音声結合完了: %s", self._output_path)
                    # 一時ファイルを削除
                    self._video_tmp_path.unlink(missing_ok=True)
                    self._audio_wav_path.unlink(missing_ok=True)
            except Exception as e:
                logger.exception("結合中にエラー: %s", e)
        else:
            logger.warning("映像または音声の一時ファイルが見つかりません。")

        return self._output_path

    def _finish_audio_only(self) -> Path:
        """音声のみモードの完了処理。WAV → MP3/WAV 変換。"""
        # WAV ファイルを閉じる
        if self._audio_wav is not None:
            self._audio_wav.close()
            self._audio_wav = None

        if self._audio_wav_path and self._audio_wav_path.exists():
            ext = self._output_path.suffix.lower()
            if ext == ".wav":
                # WAV 出力の場合はそのままリネーム
                self._audio_wav_path.rename(self._output_path)
            else:
                # MP3 出力の場合は ffmpeg で変換
                ffmpeg_bin = _find_ffmpeg()
                convert_cmd = [
                    ffmpeg_bin, "-y",
                    "-i", str(self._audio_wav_path),
                    "-acodec", "libmp3lame", "-b:a", "192k",
                    str(self._output_path),
                ]
                logger.debug("音声変換 ffmpeg: %s", " ".join(convert_cmd))
                try:
                    result = subprocess.run(
                        convert_cmd, capture_output=True, timeout=120,
                        creationflags=_SUBPROCESS_FLAGS,
                    )
                    if result.returncode != 0:
                        err = result.stderr.decode("utf-8", errors="replace")[:300]
                        logger.error("音声変換エラー: %s", err)
                        # 変換失敗時は WAV をそのまま出力
                        self._audio_wav_path.rename(self._output_path.with_suffix(".wav"))
                        self._output_path = self._output_path.with_suffix(".wav")
                    else:
                        # 一時 WAV を削除
                        self._audio_wav_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.exception("音声変換中にエラー: %s", e)

        logger.info("エンコード完了: %s", self._output_path)
        return self._output_path
