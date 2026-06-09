"""AudioCapture: マイク音声およびシステム音声の取得・ミックスを担当するクラス.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6**
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from screen_audio_recorder.models import AudioChunk

# PyAudioWPatch は Windows 専用ライブラリのため、利用不可の場合は None にフォールバック
try:
    import pyaudiowpatch as pyaudio  # type: ignore[import]
except ImportError:
    pyaudio = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# 音声フォーマット定数
SAMPLE_RATE = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2  # 16bit = 2 bytes
CHUNK_SIZE = 4096  # フレームあたりのサンプル数（大きいほど途切れにくい）


@dataclass
class MicDevice:
    """マイクデバイス情報を表すデータクラス.

    Attributes:
        index: PyAudio デバイスインデックス
        name: デバイス名
    """

    index: int
    name: str


class ErrorNotifier:
    """エラー通知クラス（スタブ実装）.

    実際の GUI 実装では tkinter の messagebox を使用する。
    ここでは logging のみ行うスタブとして定義する。
    """

    def show_warning(self, title: str, message: str) -> None:
        """警告ダイアログを表示する（処理は継続）."""
        logger.warning("[%s] %s", title, message)

    def show_error(self, title: str, message: str) -> None:
        """エラーダイアログを表示する（処理は中止）."""
        logger.error("[%s] %s", title, message)


def _pcm16_to_float32(data: bytes, channels: int) -> np.ndarray:
    """16bit PCM バイト列を float32 numpy 配列に変換する.

    Args:
        data: 16bit PCM バイト列
        channels: チャンネル数

    Returns:
        shape (samples, channels) の float32 配列、値域 [-1.0, 1.0]
    """
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels)
    else:
        samples = samples.reshape(-1, 1)
    return samples


def mix_audio(
    mic_data: np.ndarray | None,
    sys_data: np.ndarray | None,
) -> np.ndarray:
    """MicAudio と SystemAudio をミックスする.

    両方のデータが存在する場合は平均加算し、クリッピング防止のため
    [-1.0, 1.0] にクリップする。片方のみの場合はそのまま返す。

    Args:
        mic_data: マイク音声データ shape (samples, channels), dtype float32
        sys_data: システム音声データ shape (samples, channels), dtype float32

    Returns:
        ミックス済み音声データ shape (samples, channels), dtype float32
    """
    if mic_data is None and sys_data is None:
        return np.zeros((CHUNK_SIZE, CHANNELS), dtype=np.float32)

    if mic_data is None:
        return sys_data  # type: ignore[return-value]

    if sys_data is None:
        return mic_data

    # サンプル数を短い方に合わせる（独立バッファを上書きしない）
    min_samples = min(mic_data.shape[0], sys_data.shape[0])
    mic_trimmed = mic_data[:min_samples]
    sys_trimmed = sys_data[:min_samples]

    # 平均加算してクリッピング防止
    mixed = (mic_trimmed + sys_trimmed) / 2.0
    return np.clip(mixed, -1.0, 1.0).astype(np.float32)


class AudioCapture:
    """マイク音声およびシステム音声の録音・ミックスを担当するクラス.

    PyAudioWPatch の WASAPI ループバックモードでシステム音声を取得し、
    マイク音声と同一フォーマット（44100Hz、16bit、ステレオ）に統一して
    numpy でミックスする。

    デバイス利用不可時は ErrorNotifier 経由で警告を表示し、
    利用可能な音声のみで継続する。
    """

    def __init__(self, error_notifier: ErrorNotifier | None = None) -> None:
        """AudioCapture を初期化する.

        Args:
            error_notifier: エラー通知オブジェクト。None の場合はデフォルトを使用。
        """
        self._error_notifier = error_notifier or ErrorNotifier()
        self._audio_queue: queue.Queue[AudioChunk] = queue.Queue()
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

        # 独立したキュー（各キャプチャスレッドがデータを入れる）
        self._mic_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._sys_queue: queue.Queue[np.ndarray] = queue.Queue()

        self._pyaudio_instance: object | None = None

        # 直接 WAV 書き込みモード用
        self._wav_file = None
        self._wav_lock = threading.Lock()
        self._direct_pa = None
        self._direct_stream = None
        self._direct_rate = SAMPLE_RATE
        self._direct_channels = CHANNELS
        self._sd_stream = None  # sounddevice InputStream

    # ------------------------------------------------------------------
    # パブリック API
    # ------------------------------------------------------------------

    def list_mic_devices(self) -> list[MicDevice]:
        """利用可能なマイクデバイス一覧を返す.

        Returns:
            MicDevice のリスト。PyAudioWPatch が利用不可の場合は空リスト。
        """
        if pyaudio is None:
            logger.warning("PyAudioWPatch が利用不可のため、マイクデバイス一覧を取得できません。")
            return []

        devices: list[MicDevice] = []
        try:
            pa = pyaudio.PyAudio()
            try:
                device_count = pa.get_device_count()
                for i in range(device_count):
                    info = pa.get_device_info_by_index(i)
                    # 入力チャンネルが 1 以上のデバイスをマイクとして扱う
                    if info.get("maxInputChannels", 0) >= 1:
                        devices.append(MicDevice(index=i, name=str(info.get("name", ""))))
            finally:
                pa.terminate()
        except Exception:
            logger.exception("マイクデバイス一覧の取得中にエラーが発生しました。")

        return devices

    def start(
        self,
        mic_device_index: int | None,
        capture_system_audio: bool,
    ) -> None:
        """マイクおよびシステム音声の録音を開始する.

        Args:
            mic_device_index: 使用するマイクデバイスのインデックス。
                              None の場合はマイク録音を行わない。
            capture_system_audio: True の場合はシステム音声も録音する。

        Raises:
            RuntimeError: マイクとシステム音声の両方が利用不可の場合。
        """
        self._stop_event.clear()
        self._threads.clear()

        mic_ok = False
        sys_ok = False

        # マイク録音スレッドの起動を試みる
        if mic_device_index is not None:
            mic_ok = self._try_start_mic_thread(mic_device_index)
        else:
            # mic_device_index が None の場合はマイク録音をスキップ
            mic_ok = False

        # システム音声録音スレッドの起動を試みる
        if capture_system_audio:
            sys_ok = self._try_start_system_audio_thread()
        else:
            sys_ok = False

        # エラーハンドリング
        mic_requested = mic_device_index is not None
        sys_requested = capture_system_audio

        if mic_requested and not mic_ok and sys_ok:
            # マイク利用不可、システム音声のみで継続
            self._error_notifier.show_warning(
                "マイクデバイス利用不可",
                "指定されたマイクデバイスが利用できません。システム音声のみで録音を継続します。",
            )
        elif sys_requested and not sys_ok and mic_ok:
            # システム音声取得失敗、マイクのみで継続
            self._error_notifier.show_warning(
                "システム音声取得失敗",
                "システム音声の取得に失敗しました。マイク音声のみで録音を継続します。",
            )
        elif mic_requested and not mic_ok and sys_requested and not sys_ok:
            # 両方リクエストして両方失敗
            self._error_notifier.show_error(
                "音声デバイス利用不可",
                "マイクとシステム音声の両方が利用できません。録音を中止します。",
            )
            raise RuntimeError(
                "マイクとシステム音声の両方が利用できないため、録音を開始できません。"
            )
        elif not mic_requested and sys_requested and not sys_ok:
            # マイク未選択でシステム音声も失敗
            self._error_notifier.show_error(
                "システム音声取得失敗",
                "システム音声の取得に失敗しました。マイクも選択されていないため、録音を中止します。",
            )
            raise RuntimeError(
                "システム音声の取得に失敗し、マイクも選択されていないため、録音を開始できません。"
            )
        elif not mic_ok and not sys_ok and not mic_requested and not sys_requested:
            # 何もリクエストしていない（通常は発生しない）
            self._error_notifier.show_error(
                "音声デバイス利用不可",
                "音声入力が選択されていません。",
            )
            raise RuntimeError("音声入力が選択されていません。")

        # 有効なソース数に応じてパイプラインを構成
        # キャプチャスレッドが直接 _audio_queue に書き込むため、
        # ミックスワーカーや転送ワーカーは不要
        self._has_mic = mic_ok
        self._has_sys = sys_ok

    def stop(self) -> None:
        """録音を停止し、マイクとシステム音声の WAV をマージする."""
        self._stop_event.set()

        # sounddevice ストリームを停止
        if self._sd_stream is not None:
            try:
                self._sd_stream.stop()
                self._sd_stream.close()
            except Exception:
                logger.exception("sounddevice ストリームのクローズ中にエラー。")
            finally:
                self._sd_stream = None

        # システム音声ストリームを停止
        # ブロッキング read スレッドを先に停止してからストリームを閉じる
        sys_read_thread = getattr(self, "_sys_read_thread", None)
        if sys_read_thread is not None:
            sys_read_thread.join(timeout=3.0)
            self._sys_read_thread = None

        if self._direct_stream is not None:
            try:
                self._direct_stream.stop_stream()
                self._direct_stream.close()
                logger.info("システム音声録音停止。")
                logger.debug("コールバック回数: %d", getattr(self, "_callback_count", 0))
            except Exception:
                logger.exception("システム音声ストリームのクローズ中にエラー。")
            finally:
                self._direct_stream = None

        if self._direct_pa is not None:
            try:
                self._direct_pa.terminate()
            except Exception:
                pass
            finally:
                self._direct_pa = None

        # マイクコールバックストリームを停止
        if self._mic_stream is not None:
            try:
                # stop_stream() がハングする場合があるため、
                # 別スレッドでタイムアウト付きで実行する
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self._mic_stream.stop_stream)
                    try:
                        future.result(timeout=5.0)
                    except concurrent.futures.TimeoutError:
                        logger.warning("マイクストリームの stop_stream() が5秒でタイムアウト。強制終了します。")
                self._mic_stream.close()
                logger.info("マイク録音停止。")
            except Exception:
                logger.exception("マイクストリームのクローズ中にエラー。")
            finally:
                self._mic_stream = None

        if self._mic_pa is not None:
            try:
                self._mic_pa.terminate()
            except Exception:
                pass
            finally:
                self._mic_pa = None

        # スレッドモードのスレッドを停止
        for t in self._threads:
            t.join(timeout=5.0)
        self._threads.clear()

        # WAV ファイルを閉じる
        if self._wav_file is not None:
            try:
                self._wav_file.close()
            except Exception:
                logger.exception("WAV ファイルのクローズ中にエラー。")
            finally:
                self._wav_file = None

        if self._mic_wav_file is not None:
            try:
                self._mic_wav_file.close()
            except Exception:
                logger.exception("マイク WAV ファイルのクローズ中にエラー。")
            finally:
                self._mic_wav_file = None

        # 各ストリームの長さと開始時刻差を診断ログに出力
        import wave as _wave
        sys_dur = None
        mic_dur = None
        wav_path = getattr(self, "_wav_path", None)
        if wav_path and Path(wav_path).exists():
            try:
                with _wave.open(wav_path, "rb") as wf:
                    sys_dur = wf.getnframes() / wf.getframerate() if wf.getframerate() > 0 else None
            except Exception:
                pass
        if self._mic_wav_path and Path(self._mic_wav_path).exists():
            try:
                with _wave.open(self._mic_wav_path, "rb") as wf:
                    mic_dur = wf.getnframes() / wf.getframerate() if wf.getframerate() > 0 else None
            except Exception:
                pass

        logger.debug("=== 音声ストリーム診断 ===")
        logger.debug("システム音声 WAV の長さ: %s 秒",
                     f"{sys_dur:.3f}" if sys_dur else "なし")
        logger.debug("マイク WAV の長さ: %s 秒",
                     f"{mic_dur:.3f}" if mic_dur else "なし")
        sys_start = getattr(self, "_sys_start_time", None)
        mic_start = getattr(self, "_mic_start_time", None)
        if sys_start and mic_start:
            logger.debug("マイク-システム音声の開始時刻差: %.3f 秒 (マイクが遅い)",
                         mic_start - sys_start)
        if sys_dur and mic_dur:
            logger.debug("システム音声-マイクの長さの差: %.3f 秒",
                         sys_dur - mic_dur)

        # マイク WAV が存在する場合、システム音声 WAV とマージ
        if self._mic_wav_path and Path(self._mic_wav_path).exists():
            wav_path = getattr(self, "_wav_path", None)
            if wav_path and Path(wav_path).exists():
                self._merge_wav_files(wav_path, self._mic_wav_path)
            else:
                # システム音声がない場合、マイク WAV をメイン出力にリネーム
                if wav_path:
                    Path(self._mic_wav_path).rename(wav_path)

        if self._pyaudio_instance is not None:
            try:
                self._pyaudio_instance.terminate()
            except Exception:
                pass
            finally:
                self._pyaudio_instance = None

    def _sys_audio_read_worker(self) -> None:
        """システム音声のポーリング + タイマーベース無音挿入ワーカー.

        一定間隔（CHUNK_SIZE / sample_rate 秒）でポーリングし、
        データがあれば読み取って WAV に書き込む。
        データがなければ（= 無音区間）無音データを書き込む。
        これにより WAV の長さが実時間と正確に一致する。
        """
        chunk_size = CHUNK_SIZE
        rate = self._direct_rate
        channels = self._direct_channels
        interval = chunk_size / rate  # 1チャンクの期待間隔（秒）
        silence = b'\x00' * (chunk_size * channels * SAMPLE_WIDTH)

        next_write_time = time.perf_counter()

        try:
            while not self._stop_event.is_set():
                now = time.perf_counter()

                # 次の書き込み時刻まで待機
                wait = next_write_time - now
                if wait > 0.001:
                    time.sleep(min(wait, 0.005))
                    continue

                # データが利用可能か確認
                try:
                    available = self._direct_stream.get_read_available()
                except Exception:
                    if self._stop_event.is_set():
                        break
                    available = 0

                if available >= chunk_size:
                    # データあり: 読み取って書き込む
                    try:
                        data = self._direct_stream.read(chunk_size, exception_on_overflow=False)
                        if self._wav_file is not None and data:
                            self._wav_file.writeframes(data)
                            self._callback_count += 1
                            # RMS 追跡
                            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                            rms = float(np.sqrt(np.mean(samples ** 2)))
                            if rms > 0.0001:
                                self._sys_rms_sum += rms
                                self._sys_rms_count += 1
                            # 1秒ごとに音量ログ
                            if now - self._sys_volume_log_time >= 1.0:
                                self._sys_volume_log_time = now
                                logger.debug("[音量] システム音声 RMS: %.6f (dB: %.1f)",
                                            rms, 20 * np.log10(rms + 1e-10))
                    except OSError:
                        if self._stop_event.is_set():
                            break
                        # read エラー時は無音を書き込む
                        if self._wav_file is not None:
                            self._wav_file.writeframes(silence)
                else:
                    # データなし（無音区間）: 無音データを書き込む
                    if self._wav_file is not None:
                        self._wav_file.writeframes(silence)
                        self._callback_count += 1

                next_write_time += interval

                # タイマーが大きく遅れた場合はリセット
                if time.perf_counter() - next_write_time > interval * 3:
                    next_write_time = time.perf_counter()

        except Exception:
            logger.exception("システム音声ポーリングワーカーでエラー。")

    def _merge_wav_files(self, sys_wav_path: str, mic_wav_path: str) -> None:
        """システム音声 WAV とマイク WAV を ffmpeg でマージする.

        サンプルレートが異なる場合（例: システム48000Hz, マイク44100Hz）も
        -ar 44100 で統一してからマージする。
        録音中に追跡した RMS を元に、マイク音量をシステム音声と同レベルに
        自動調整してからミックスする。
        """
        from pathlib import Path
        try:
            from screen_audio_recorder.video_encoder import _find_ffmpeg
            import subprocess

            ffmpeg_bin = _find_ffmpeg()
            output_path = sys_wav_path + ".merged.wav"

            # マイクゲインの計算
            mic_gain = 1.0
            sys_avg_rms = (self._sys_rms_sum / self._sys_rms_count) if self._sys_rms_count > 0 else 0.0
            mic_avg_rms = (self._mic_rms_sum / self._mic_rms_count) if self._mic_rms_count > 0 else 0.0

            if mic_avg_rms > 0.0001 and sys_avg_rms > 0.0001:
                # マイクの音量をシステム音声と同レベルに引き上げる
                mic_gain = sys_avg_rms / mic_avg_rms
                # ゲインの上限を設定（過度な増幅でノイズが目立つのを防ぐ）
                mic_gain = min(mic_gain, 50.0)
                logger.debug(
                    "音量自動調整: sys_avg_rms=%.6f, mic_avg_rms=%.6f, mic_gain=%.2f (%.1f dB)",
                    sys_avg_rms, mic_avg_rms, mic_gain, 20 * np.log10(mic_gain),
                )
            else:
                logger.debug(
                    "音量自動調整: スキップ (sys_rms=%.6f [%d samples], mic_rms=%.6f [%d samples])",
                    sys_avg_rms, self._sys_rms_count, mic_avg_rms, self._mic_rms_count,
                )

            # ffmpeg で2つの音声をミックス
            # マイクにゲインを適用してからミックスする
            if mic_gain > 1.01:
                # マイクにボリュームフィルタを適用してからミックス
                filter_complex = (
                    f"[1:a]volume={mic_gain:.2f}[mic_boosted];"
                    f"[0:a][mic_boosted]amix=inputs=2:duration=longest:dropout_transition=0"
                )
            else:
                filter_complex = "amix=inputs=2:duration=longest:dropout_transition=0"

            merge_cmd = [
                ffmpeg_bin, "-y",
                "-i", sys_wav_path,
                "-i", mic_wav_path,
                "-filter_complex", filter_complex,
                "-ar", "44100",
                "-ac", "2",
                output_path,
            ]
            import sys as _sys
            _flags = subprocess.CREATE_NO_WINDOW if _sys.platform == "win32" else 0
            result = subprocess.run(merge_cmd, capture_output=True, timeout=120, creationflags=_flags)

            if result.returncode == 0:
                # マージ成功: 元ファイルを置き換え
                Path(mic_wav_path).unlink(missing_ok=True)
                # Windows ではファイルハンドル解放に遅延があるため、
                # unlink 後の rename が PermissionError になることがある。
                # shutil.move を使い、失敗時はリトライする。
                import shutil
                import time as _time
                target = Path(sys_wav_path)
                target.unlink(missing_ok=True)
                for attempt in range(5):
                    try:
                        shutil.move(output_path, str(target))
                        break
                    except PermissionError:
                        if attempt < 4:
                            _time.sleep(0.5)
                        else:
                            # 最終手段: merged ファイルをそのまま使う
                            logger.warning(
                                "リネーム失敗。マージ済みファイルをそのまま使用: %s", output_path
                            )
                            # _wav_path を merged ファイルに差し替え
                            self._wav_path = output_path
                            break
                logger.info("音声マージ完了: %s", sys_wav_path)
            else:
                err = result.stderr.decode("utf-8", errors="replace")[:200]
                logger.error("音声マージ失敗: %s", err)
                # マージ失敗時はシステム音声のみ残す
                Path(mic_wav_path).unlink(missing_ok=True)
                Path(output_path).unlink(missing_ok=True)
        except Exception:
            logger.exception("音声マージ中にエラー。")
            Path(mic_wav_path).unlink(missing_ok=True)

    def get_audio_queue(self) -> queue.Queue[AudioChunk]:
        """ミックス済み音声チャンクキューを返す."""
        return self._audio_queue

    def start_direct_recording(
        self,
        wav_path: str,
        mic_device_index: int | None,
        capture_system_audio: bool,
    ) -> None:
        """音声を直接 WAV ファイルに書き込むモードで録音を開始する.

        システム音声とマイクを別々の WAV に録音し、stop() 後にマージする。
        各コールバックが独立した WAV に書き込むため途切れなし。
        """
        import wave

        self._stop_event.clear()
        self._threads.clear()
        self._wav_path = wav_path
        self._sd_stream = None
        self._mic_wav_file = None
        self._mic_wav_path = None
        self._mic_stream = None
        self._mic_pa = None
        self._sys_read_thread = None
        # 各ストリームの開始時刻を記録（同期診断用）
        self._sys_start_time: float | None = None
        self._mic_start_time: float | None = None
        # 音量自動調整用: RMS の二乗和とサンプル数を追跡
        self._sys_rms_sum: float = 0.0
        self._sys_rms_count: int = 0
        self._mic_rms_sum: float = 0.0
        self._mic_rms_count: int = 0

        if pyaudio is None:
            self._error_notifier.show_error("音声エラー", "PyAudioWPatch が利用できません。")
            raise RuntimeError("PyAudioWPatch が利用できません。")

        pa = pyaudio.PyAudio()

        # --- システム音声（ループバック）---
        loopback_device = None
        sys_rate = SAMPLE_RATE
        sys_channels = CHANNELS
        sys_ok = False

        if capture_system_audio:
            try:
                wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_speakers_index = wasapi_info["defaultOutputDevice"]
                default_speakers = pa.get_device_info_by_index(default_speakers_index)

                for i in range(pa.get_device_count()):
                    dev = pa.get_device_info_by_index(i)
                    if dev.get("isLoopbackDevice", False):
                        if default_speakers.get("name", "").split(" ")[0] in dev.get("name", ""):
                            loopback_device = dev
                            break

                if loopback_device is None:
                    try:
                        loopback_device = pa.get_loopback_device_info_by_speakers(default_speakers)
                    except Exception:
                        pass

                if loopback_device is not None:
                    sys_rate = int(loopback_device["defaultSampleRate"])
                    sys_channels = int(loopback_device["maxInputChannels"])
                    logger.info("ループバック: %s (rate=%d, ch=%d)",
                                loopback_device["name"], sys_rate, sys_channels)
            except Exception:
                logger.exception("ループバックデバイスの検索に失敗。")

        # システム音声 WAV を開く（ブロッキング read モード）
        if loopback_device is not None:
            self._wav_file = wave.open(wav_path, "wb")
            self._wav_file.setnchannels(sys_channels)
            self._wav_file.setsampwidth(SAMPLE_WIDTH)
            self._wav_file.setframerate(sys_rate)
            self._direct_rate = sys_rate
            self._direct_channels = sys_channels
            self._callback_count = 0
            self._sys_volume_log_time: float = 0.0

            try:
                # ブロッキング read モードでストリームを開く（コールバックなし）
                # stream.read() は無音時でもゼロ埋めデータを返すため、長さが正確になる
                self._direct_stream = pa.open(
                    format=pyaudio.paInt16,
                    channels=sys_channels,
                    rate=sys_rate,
                    input=True,
                    input_device_index=int(loopback_device["index"]),
                    frames_per_buffer=CHUNK_SIZE,
                )
                self._direct_stream.start_stream()
                self._direct_pa = pa
                sys_ok = True
                self._sys_start_time = time.perf_counter()
                logger.info("システム音声ブロッキング録音開始: device=%d", int(loopback_device["index"]))

                # 専用スレッドで read ループを実行
                self._sys_read_thread = threading.Thread(
                    target=self._sys_audio_read_worker,
                    daemon=True,
                )
                self._sys_read_thread.start()
            except Exception:
                logger.exception("システム音声ストリームの起動に失敗。")
                self._wav_file.close()
                self._wav_file = None

        # --- マイク ---
        mic_ok = False
        if mic_device_index is not None:
            try:
                mic_pa = pyaudio.PyAudio() if sys_ok else pa
                mic_info = mic_pa.get_device_info_by_index(mic_device_index)
                mic_rate = int(mic_info["defaultSampleRate"])
                mic_channels = min(int(mic_info["maxInputChannels"]), 2)

                self._mic_wav_path = wav_path.replace(".wav", ".mic.wav")
                self._mic_wav_file = wave.open(self._mic_wav_path, "wb")
                self._mic_wav_file.setnchannels(mic_channels)
                self._mic_wav_file.setsampwidth(SAMPLE_WIDTH)
                self._mic_wav_file.setframerate(mic_rate)
                # 音量ログ用: 最後にログ出力した時刻
                self._mic_volume_log_time: float = 0.0

                def _mic_callback(in_data, frame_count, time_info, status):
                    if self._mic_wav_file is not None and in_data:
                        self._mic_wav_file.writeframes(in_data)
                        # RMS 追跡（音量自動調整用）
                        samples = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
                        rms = float(np.sqrt(np.mean(samples ** 2)))
                        if rms > 0.0001:  # 無音でないチャンクのみ集計
                            self._mic_rms_sum += rms
                            self._mic_rms_count += 1
                        # 1秒ごとに音量(RMS)をログ出力
                        now = time.perf_counter()
                        if now - self._mic_volume_log_time >= 1.0:
                            self._mic_volume_log_time = now
                            logger.debug("[音量] マイク RMS: %.6f (dB: %.1f)", rms, 20 * np.log10(rms + 1e-10))
                    return (None, pyaudio.paContinue)

                self._mic_stream = mic_pa.open(
                    format=pyaudio.paInt16,
                    channels=mic_channels,
                    rate=mic_rate,
                    input=True,
                    input_device_index=mic_device_index,
                    frames_per_buffer=CHUNK_SIZE,
                    stream_callback=_mic_callback,
                )
                self._mic_stream.start_stream()
                self._mic_pa = mic_pa
                mic_ok = True
                self._mic_start_time = time.perf_counter()
                logger.info("マイクコールバック録音開始: device=%d, rate=%d", mic_device_index, mic_rate)
            except Exception:
                logger.exception("マイクストリームの起動に失敗。")
                if self._mic_wav_file:
                    self._mic_wav_file.close()
                    self._mic_wav_file = None

        # エラーチェック
        if not sys_ok and not mic_ok:
            pa.terminate()
            self._error_notifier.show_error("音声エラー", "録音デバイスが見つかりません。")
            raise RuntimeError("録音デバイスが見つかりません。")

        if not sys_ok and mic_ok:
            # マイクのみ → マイク WAV をメインの出力パスにリネームする（stop 時）
            self._error_notifier.show_warning("システム音声取得失敗", "マイクのみで録音します。")

        logger.info("直接録音開始: sys=%s, mic=%s", sys_ok, mic_ok)

    def _try_start_direct_mic_thread(self, device_index: int) -> bool:
        """マイク音声をコールバックモードで直接 WAV に書き込む."""
        if pyaudio is None:
            return False
        try:
            pa = pyaudio.PyAudio()

            def _callback(in_data, frame_count, time_info, status):
                """PyAudio コールバック: マイクデータを WAV に書き込む."""
                if self._wav_file is not None and in_data:
                    try:
                        self._wav_file.writeframes(in_data)
                    except Exception:
                        pass
                return (None, pyaudio.paContinue)

            stream = pa.open(
                format=pyaudio.paInt16,
                channels=self._direct_channels,
                rate=self._direct_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK_SIZE,
                stream_callback=_callback,
            )
            stream.start_stream()

            self._direct_pa = pa
            self._direct_stream = stream

            logger.info("コールバックモードでマイク録音を開始しました")
            return True
        except Exception:
            logger.exception("直接マイク録音の起動に失敗しました。")
            return False

    def _try_start_direct_system_thread(self) -> bool:
        """システム音声をコールバックモードで直接 WAV に書き込む."""
        if pyaudio is None:
            return False
        try:
            pa = pyaudio.PyAudio()
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers_index = wasapi_info["defaultOutputDevice"]
            default_speakers = pa.get_device_info_by_index(default_speakers_index)

            loopback_device = None
            for i in range(pa.get_device_count()):
                device_info = pa.get_device_info_by_index(i)
                if (
                    device_info.get("isLoopbackDevice", False)
                    and device_info.get("name", "").startswith(
                        default_speakers.get("name", "")
                    )
                ):
                    loopback_device = device_info
                    break

            if loopback_device is None:
                try:
                    loopback_device = pa.get_loopback_device_info_by_speakers(default_speakers)
                except Exception:
                    pa.terminate()
                    return False

            dev_rate = int(loopback_device.get("defaultSampleRate", SAMPLE_RATE))
            dev_channels = int(loopback_device.get("maxInputChannels", CHANNELS))

            def _callback(in_data, frame_count, time_info, status):
                """PyAudio コールバック: ドライバから直接データを受け取り WAV に書き込む."""
                if self._wav_file is not None and in_data:
                    try:
                        self._wav_file.writeframes(in_data)
                    except Exception:
                        pass
                return (None, pyaudio.paContinue)

            # コールバックモードでストリームを開く
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=dev_channels,
                rate=dev_rate,
                input=True,
                input_device_index=int(loopback_device["index"]),
                frames_per_buffer=CHUNK_SIZE,
                stream_callback=_callback,
            )
            stream.start_stream()

            # PyAudio インスタンスとストリームを保持（stop 時に閉じる）
            self._direct_pa = pa
            self._direct_stream = stream

            logger.info("コールバックモードでシステム音声録音を開始しました (rate=%d, ch=%d)", dev_rate, dev_channels)
            return True
        except Exception:
            logger.exception("直接システム音声録音の起動に失敗しました。")
            return False

    def _direct_capture_worker(self, pa: object, stream: object) -> None:
        """音声データを直接 WAV ファイルに書き込むワーカー.

        1つのスレッドのみがこのワーカーを実行する（WAV 競合なし）。
        """
        try:
            while not self._stop_event.is_set():
                try:
                    data = stream.read(CHUNK_SIZE, exception_on_overflow=False)  # type: ignore[union-attr]
                    if self._wav_file is not None:
                        self._wav_file.writeframes(data)
                except OSError:
                    logger.exception("直接録音中にエラーが発生しました。")
                    break
        finally:
            try:
                stream.stop_stream()  # type: ignore[union-attr]
                stream.close()  # type: ignore[union-attr]
                pa.terminate()  # type: ignore[union-attr]
            except Exception:
                logger.exception("ストリームのクローズ中にエラーが発生しました。")

    # ------------------------------------------------------------------
    # 内部実装
    # ------------------------------------------------------------------

    def _try_start_mic_thread(self, device_index: int) -> bool:
        """マイク録音スレッドの起動を試みる.

        Args:
            device_index: マイクデバイスのインデックス

        Returns:
            起動に成功した場合は True、失敗した場合は False
        """
        if pyaudio is None:
            logger.warning("PyAudioWPatch が利用不可のため、マイク録音を開始できません。")
            return False

        try:
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK_SIZE,
            )
            thread = threading.Thread(
                target=self._mic_capture_worker,
                args=(pa, stream),
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
            return True
        except Exception:
            logger.exception("マイク録音スレッドの起動に失敗しました。")
            return False

    def _try_start_system_audio_thread(self) -> bool:
        """システム音声録音スレッドの起動を試みる.

        Returns:
            起動に成功した場合は True、失敗した場合は False
        """
        if pyaudio is None:
            logger.warning("PyAudioWPatch が利用不可のため、システム音声録音を開始できません。")
            return False

        try:
            pa = pyaudio.PyAudio()
            # WASAPI ループバックデバイスを取得
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers_index = wasapi_info["defaultOutputDevice"]
            default_speakers = pa.get_device_info_by_index(default_speakers_index)

            # ループバックデバイスを探す
            loopback_device = None
            for i in range(pa.get_device_count()):
                device_info = pa.get_device_info_by_index(i)
                if (
                    device_info.get("isLoopbackDevice", False)
                    and device_info.get("name", "").startswith(
                        default_speakers.get("name", "")
                    )
                ):
                    loopback_device = device_info
                    break

            if loopback_device is None:
                # ループバックデバイスが見つからない場合は get_loopback_device_info_by_speakers を試みる
                try:
                    loopback_device = pa.get_loopback_device_info_by_speakers(
                        default_speakers
                    )
                except Exception:
                    logger.exception("ループバックデバイスの取得に失敗しました。")
                    pa.terminate()
                    return False

            stream = pa.open(
                format=pyaudio.paInt16,
                channels=int(loopback_device.get("maxInputChannels", CHANNELS)),
                rate=int(loopback_device.get("defaultSampleRate", SAMPLE_RATE)),
                input=True,
                input_device_index=int(loopback_device["index"]),
                frames_per_buffer=CHUNK_SIZE,
            )
            thread = threading.Thread(
                target=self._system_audio_capture_worker,
                args=(pa, stream),
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
            return True
        except Exception:
            logger.exception("システム音声録音スレッドの起動に失敗しました。")
            return False

    def _mic_capture_worker(self, pa: object, stream: object) -> None:
        """マイク音声をキャプチャし、直接出力キューに入れるワーカー."""
        try:
            while not self._stop_event.is_set():
                try:
                    data = stream.read(CHUNK_SIZE, exception_on_overflow=False)  # type: ignore[union-attr]
                    float_data = _pcm16_to_float32(data, CHANNELS)
                    chunk = AudioChunk(
                        data=float_data,
                        sample_rate=SAMPLE_RATE,
                        timestamp=time.perf_counter(),
                    )
                    self._audio_queue.put(chunk)
                except OSError:
                    logger.exception("マイク音声の読み取り中にエラーが発生しました。")
                    break
        finally:
            try:
                stream.stop_stream()  # type: ignore[union-attr]
                stream.close()  # type: ignore[union-attr]
                pa.terminate()  # type: ignore[union-attr]
            except Exception:
                logger.exception("マイクストリームのクローズ中にエラーが発生しました。")

    def _system_audio_capture_worker(self, pa: object, stream: object) -> None:
        """システム音声をキャプチャし、直接出力キューに入れるワーカー."""
        try:
            while not self._stop_event.is_set():
                try:
                    data = stream.read(CHUNK_SIZE, exception_on_overflow=False)  # type: ignore[union-attr]
                    float_data = _pcm16_to_float32(data, CHANNELS)
                    chunk = AudioChunk(
                        data=float_data,
                        sample_rate=SAMPLE_RATE,
                        timestamp=time.perf_counter(),
                    )
                    self._audio_queue.put(chunk)
                except OSError:
                    logger.exception("システム音声の読み取り中にエラーが発生しました。")
                    break
        finally:
            try:
                stream.stop_stream()  # type: ignore[union-attr]
                stream.close()  # type: ignore[union-attr]
                pa.terminate()  # type: ignore[union-attr]
            except Exception:
                logger.exception("システム音声ストリームのクローズ中にエラーが発生しました。")

    def _forward_worker(self, source_queue: queue.Queue[np.ndarray]) -> None:
        """単一ソースのデータをそのまま出力キューに転送するワーカー.

        ミックス不要な場合（片方のソースのみ）に使用する。
        ブロッキング get() でデータを待つため、データの欠落が発生しない。
        """
        while not self._stop_event.is_set():
            try:
                data = source_queue.get(timeout=0.05)
                chunk = AudioChunk(
                    data=data,
                    sample_rate=SAMPLE_RATE,
                    timestamp=time.perf_counter(),
                )
                self._audio_queue.put(chunk)
            except queue.Empty:
                continue

    def _mix_worker(self) -> None:
        """MicAudio と SystemAudio をミックスしてキューに追加するワーカー.

        両方のソースがある場合に使用する。
        各キューからブロッキング get() でデータを取得し、ミックスする。
        """
        while not self._stop_event.is_set():
            mic_data = None
            sys_data = None

            # マイクデータを取得（短いタイムアウトで待機）
            try:
                mic_data = self._mic_queue.get(timeout=0.05)
            except queue.Empty:
                pass

            # システム音声データを取得（短いタイムアウトで待機）
            try:
                sys_data = self._sys_queue.get(timeout=0.05)
            except queue.Empty:
                pass

            if mic_data is not None or sys_data is not None:
                mixed = mix_audio(mic_data, sys_data)
                chunk = AudioChunk(
                    data=mixed,
                    sample_rate=SAMPLE_RATE,
                    timestamp=time.perf_counter(),
                )
                self._audio_queue.put(chunk)
