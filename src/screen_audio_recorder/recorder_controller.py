"""RecorderController: 録画・録音の制御を担当するクラス.

ScreenCapture・AudioCapture・VideoEncoder・Transcriber・ThemeGeneratorService・
MemoStore・FileStore・ErrorNotifier を統合し、録画パイプライン全体を管理する。

**Validates: Requirements 2.1, 2.4, 5.1, 5.2, 5.4, 6.1, 7.4**
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from screen_audio_recorder.models import RecordingMode, RecordingRegion, TranscribeResult

logger = logging.getLogger("screen_audio_recorder")

# 録画解像度のデフォルト値
_DEFAULT_FPS = 15
_DEFAULT_RESOLUTION = (1920, 1080)


class RecorderController:
    """録画・録音の制御を担当するクラス.

    各コンポーネント（ScreenCapture・AudioCapture・VideoEncoder・Transcriber・
    ThemeGeneratorService・MemoStore・FileStore・ErrorNotifier）を受け取り、
    録画パイプライン全体を管理する。

    スレッドモデル:
        - キャプチャスレッド: フレームキューと音声キューを読み取り VideoEncoder に書き込む
        - 文字起こしスレッド: Transcriber.transcribe_async() で非同期実行

    Attributes:
        _screen_capture: 画面キャプチャコンポーネント
        _audio_capture: 音声キャプチャコンポーネント
        _video_encoder: 映像エンコーダコンポーネント
        _transcriber: 文字起こしコンポーネント
        _theme_generator: テーマ生成サービス
        _memo_store: メモ保存コンポーネント
        _file_store: ファイル保存コンポーネント
        _error_notifier: エラー通知コンポーネント
        _root: tkinter ルートウィンドウ（GUI スレッド通知用）
        _is_recording: 録画中フラグ
        _capture_thread: キャプチャスレッド
        _current_mode: 現在の録画モード
    """

    def __init__(
        self,
        screen_capture,
        audio_capture,
        video_encoder,
        transcriber,
        theme_generator,
        memo_store,
        file_store,
        error_notifier,
        root=None,
        text_post_processor=None,
    ) -> None:
        """RecorderController を初期化する.

        Args:
            screen_capture: ScreenCapture インスタンス
            audio_capture: AudioCapture インスタンス
            video_encoder: VideoEncoder インスタンス
            transcriber: Transcriber インスタンス
            theme_generator: ThemeGeneratorService インスタンス
            memo_store: MemoStore インスタンス
            file_store: FileStore インスタンス
            error_notifier: ErrorNotifier インスタンス
            root: tkinter ルートウィンドウ。None の場合は直接 callback を呼ぶ。
            text_post_processor: TextPostProcessor インスタンス。None の場合は従来のテーマ生成のみ。
        """
        self._screen_capture = screen_capture
        self._audio_capture = audio_capture
        self._video_encoder = video_encoder
        self._transcriber = transcriber
        self._theme_generator = theme_generator
        self._memo_store = memo_store
        self._file_store = file_store
        self._error_notifier = error_notifier
        self._root = root
        self._text_post_processor = text_post_processor

        self._is_recording = False
        self._capture_thread: threading.Thread | None = None
        self._current_mode: RecordingMode | None = None
        self._current_output_path: Path | None = None
        self._stop_event = threading.Event()
        self._first_frame_written = threading.Event()
        self._on_memo_saved_callback = None
        self._video_start_time: float | None = None

    def set_on_memo_saved(self, callback) -> None:
        """メモ保存完了時のコールバックを設定する."""
        self._on_memo_saved_callback = callback

    # ------------------------------------------------------------------
    # パブリック API
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """録画中かどうかを返す.

        Returns:
            録画中の場合は True、そうでない場合は False
        """
        return self._is_recording

    def start_recording(self, mode: RecordingMode, region: RecordingRegion, mic_device_index: int | None = None) -> None:
        """録画または録音を開始する.

        Args:
            mode: 録画モード（SCREEN_AND_AUDIO または AUDIO_ONLY）
            region: 録画対象の画面領域
            mic_device_index: マイクデバイスインデックス。None の場合はマイクなし。
        """
        if self._is_recording:
            logger.warning("既に録画中です。start_recording() の呼び出しを無視します。")
            return

        self._current_mode = mode
        self._stop_event.clear()

        # 出力ファイルパスを決定
        if mode == RecordingMode.SCREEN_AND_AUDIO:
            ext = "mp4"
        else:
            ext = "wav"
        self._current_output_path = self._file_store.get_output_path(ext)

        if mode == RecordingMode.AUDIO_ONLY:
            # 音声のみモード: コールバックで直接 WAV に書き込む
            self._audio_capture.start_direct_recording(
                wav_path=str(self._current_output_path),
                mic_device_index=mic_device_index,
                capture_system_audio=True,
            )
            self._is_recording = True
            logger.info("録画を開始しました。モード: %s（直接 WAV 録音）", mode)
            return

        # 画面+音声モード:
        # 音声と映像の同期を厳密に保つため、以下の順序で起動する:
        #   1. 画面キャプチャ起動 → 解像度取得
        #   2. ffmpeg 起動（映像パイプライン準備）
        #   3. キャプチャスレッド起動 → 最初のフレームを ffmpeg に書き込む
        #   4. 最初のフレーム書き込み完了を待ってから音声録音を開始
        # これにより、ffmpeg 起動の遅延分だけ音声が先行する問題を防ぐ。

        # 1. 画面キャプチャを起動し、最初のフレームで実際の解像度を取得
        resolution = (region.width, region.height)
        self._screen_capture.start(region)
        for _ in range(50):
            actual = self._screen_capture.actual_resolution
            if actual is not None:
                resolution = actual
                logger.info("実際の画面解像度: %dx%d", resolution[0], resolution[1])
                break
            time.sleep(0.1)

        # 解像度バリデーション: 幅または高さが2未満の場合は録画不可
        # （DPI スケーリングでウィンドウ座標が画面外に出ている場合に発生しうる）
        width, height = resolution
        if (width & ~1) < 2 or (height & ~1) < 2:
            logger.error(
                "録画解像度が無効です: %dx%d。録画領域が画面外の可能性があります。"
                "録画を中断します。",
                width, height,
            )
            self._screen_capture.stop()
            if self._error_notifier:
                self._error_notifier.notify(
                    "録画エラー",
                    f"録画領域のサイズが無効です ({width}x{height})。\n"
                    "ウィンドウが画面外に移動している可能性があります。\n"
                    "録画領域を再選択してください。",
                )
            return

        # 2. VideoEncoder を起動（映像のみ、音声は後で WAV に直接書き込み）
        self._video_encoder.start(
            output_path=self._current_output_path,
            fps=_DEFAULT_FPS,
            resolution=resolution,
            mode=mode,
        )

        # 3. キャプチャスレッドを起動（映像フレームを VideoEncoder に書き込む）
        #    最初のフレーム書き込み完了時に _first_frame_written をセットする
        self._first_frame_written.clear()
        self._capture_thread = threading.Thread(
            target=self._video_capture_worker,
            daemon=True,
        )
        self._capture_thread.start()

        # 4. ffmpeg が最初のフレームを実際に受け取るまで待機してから音声録音を開始
        #    パイプライタースレッドが最初の書き込みを完了するまで待つ
        if not self._video_encoder._first_pipe_write_done.wait(timeout=5.0):
            logger.warning("最初のフレーム書き込みがタイムアウトしました。音声録音を開始します。")

        # 映像の実際の開始時刻を記録（結合時のオフセット補正用）
        self._video_start_time = time.perf_counter()

        audio_wav_path = self._current_output_path.with_suffix(".audio.wav")
        self._audio_capture.start_direct_recording(
            wav_path=str(audio_wav_path),
            mic_device_index=mic_device_index,
            capture_system_audio=True,
        )

        # 音声開始時刻を VideoEncoder に記録（結合時のオフセット補正用）
        audio_start_time = time.perf_counter()
        audio_delay = audio_start_time - self._video_start_time
        self._video_encoder.set_audio_delay(audio_delay)

        # 各ストリームの開始時刻を診断ログに出力
        sys_start = getattr(self._audio_capture, "_sys_start_time", None)
        mic_start = getattr(self._audio_capture, "_mic_start_time", None)
        logger.debug("=== ストリーム開始時刻診断 ===")
        logger.debug("映像開始 (perf_counter): %.3f", self._video_start_time)
        if isinstance(sys_start, (int, float)):
            logger.debug("システム音声開始: %.3f (映像から +%.3f 秒)",
                         sys_start, sys_start - self._video_start_time)
        if isinstance(mic_start, (int, float)):
            logger.debug("マイク開始: %.3f (映像から +%.3f 秒)",
                         mic_start, mic_start - self._video_start_time)
        logger.debug("音声開始遅延 (audio_delay): %.3f 秒", audio_delay)

        # 一番遅いストリームを基準にして、結合時のトリムオフセットを計算
        # 映像の先頭を「一番遅いストリームの開始時刻 - 映像開始時刻」分トリムする
        latest_start = self._video_start_time
        if isinstance(sys_start, (int, float)):
            latest_start = max(latest_start, sys_start)
        if isinstance(mic_start, (int, float)):
            latest_start = max(latest_start, mic_start)
        video_trim = latest_start - self._video_start_time
        self._video_encoder.set_video_trim(video_trim)
        logger.debug("映像先頭トリム: %.3f 秒 (一番遅いストリームに合わせる)", video_trim)

        self._is_recording = True
        logger.info("録画を開始しました。モード: %s", mode)

    def stop_recording(self) -> None:
        """録画・録音を停止し、後処理パイプラインを実行する.

        後処理パイプライン:
            VideoEncoder.finish() → Transcriber.transcribe_async() →
            ThemeGeneratorService.generate() → MemoStore.create()

        要件 2.4: 録画停止時に OutputFile を生成する
        要件 5.4: 録音停止時に OutputFile を生成し Transcriber に渡す
        要件 6.1: OutputFile 生成後に文字起こしを開始する
        要件 7.4: テーマ生成後に MemoStore に渡す
        """
        if not self._is_recording:
            logger.warning("録画中ではありません。stop_recording() の呼び出しを無視します。")
            return

        self._is_recording = False
        self._stop_event.set()

        # 録画終了時刻を即座に記録（audio_capture.stop() のハング時間を含めない）
        self._video_encoder.mark_recording_end()

        # キャプチャスレッドの終了を待つ
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=5.0)
            self._capture_thread = None

        # 音声キャプチャを停止
        self._audio_capture.stop()

        if self._current_mode == RecordingMode.AUDIO_ONLY:
            # 音声のみモード: WAV がそのまま最終出力
            output_path = self._current_output_path
            logger.info("録画を停止しました。OutputFile: %s", output_path)
        else:
            # 画面+音声モード: 従来の処理
            # 画面キャプチャを停止
            self._screen_capture.stop()

            # エンコードを完了して OutputFile パスを取得
            output_path = self._video_encoder.finish()
            logger.info("録画を停止しました。OutputFile: %s", output_path)

        # 文字起こしを非同期で開始
        # output_path をクロージャでキャプチャし、次の録画で _current_output_path が
        # 上書きされても正しいパスでメモが保存されるようにする
        captured_output_path = output_path

        def _on_transcribe_done(result: TranscribeResult) -> None:
            self._on_transcribe_complete(result, captured_output_path)

        self._transcriber.transcribe_async(
            audio_path=output_path,
            callback=_on_transcribe_done,
            root=self._root,
        )

    def update_region(self, region: RecordingRegion) -> None:
        """録画領域をリアルタイムで更新する.

        ScreenCapture.set_region() をリアルタイム呼び出しする。

        Args:
            region: 新しい録画領域

        要件 2.4: 録画領域のリアルタイム変更
        """
        self._screen_capture.set_region(region)

    # ------------------------------------------------------------------
    # 内部実装
    # ------------------------------------------------------------------

    def _video_capture_worker(self) -> None:
        """映像フレームのみを VideoEncoder に書き込むワーカー（音声は別途 WAV に直接書き込み）.

        起動時にキューに溜まった古いフレームを破棄し、
        映像パイプライン開始時点からのフレームのみを書き込む。
        最初のフレーム書き込み完了時に _first_frame_written をセットし、
        音声録音の開始タイミングを通知する。

        フレームレート制御:
            1/fps 間隔のタイマーで書き込みタイミングを制御する。
            各タイミングで:
              - キューにフレームがあれば最新を取得（古いのは破棄）
              - キューが空なら前回のフレームを再利用
            write_frame がブロックしてタイマーが遅れた場合は、
            遅れた分をスキップして現在時刻にリセットする（複製フレームは挿入しない）。
        """
        frame_queue = self._screen_capture.get_frame_queue()
        frame_interval = 1.0 / _DEFAULT_FPS

        # 解像度ポーリング中にキューに溜まったフレームを破棄する
        discarded = 0
        while not frame_queue.empty():
            try:
                frame_queue.get_nowait()
                discarded += 1
            except queue.Empty:
                break
        if discarded > 0:
            logger.debug("映像キューから %d フレームを破棄しました（同期のため）", discarded)

        first_written = False
        last_frame = None
        next_write_time = time.perf_counter()

        while not self._stop_event.is_set():
            now = time.perf_counter()

            # 次の書き込み時刻まで待機
            wait_time = next_write_time - now
            if wait_time > 0.001:
                time.sleep(min(wait_time, 0.005))
                continue

            # タイマーが遅れている場合は現在時刻にリセット
            # （write_frame のブロックやエンコーダの遅延で遅れた分はスキップ）
            if now - next_write_time > frame_interval * 2:
                next_write_time = now

            # キューから最新フレームを取得
            new_frame = None
            try:
                while True:
                    new_frame = frame_queue.get_nowait()
                    if frame_queue.empty():
                        break
            except queue.Empty:
                pass

            if new_frame is not None:
                last_frame = new_frame

            # 新しいフレームが来た場合のみ書き込む
            # （前回のフレームを再利用しない = 画面が止まって見える問題を防ぐ）
            if new_frame is not None:
                self._video_encoder.write_frame(new_frame)
                if not first_written:
                    first_written = True
                    self._first_frame_written.set()
                    next_write_time = time.perf_counter()
                    logger.debug("最初の映像フレームを ffmpeg に書き込みました")
            elif last_frame is not None:
                # 新しいフレームが来ていない場合は最後のフレームを書き込む
                # （ffmpeg は固定 fps なのでフレームを送り続ける必要がある）
                self._video_encoder.write_frame(last_frame)

            next_write_time += frame_interval

    def _capture_worker(self, mode: RecordingMode) -> None:
        """フレームキューと音声キューを読み取り VideoEncoder に書き込むワーカー."""
        frame_queue = None
        audio_queue = self._audio_capture.get_audio_queue()

        if mode == RecordingMode.SCREEN_AND_AUDIO:
            frame_queue = self._screen_capture.get_frame_queue()

        while not self._stop_event.is_set():
            wrote_something = False

            # フレームを書き込む（SCREEN_AND_AUDIO モードのみ）
            if frame_queue is not None:
                try:
                    frame = frame_queue.get_nowait()
                    self._video_encoder.write_frame(frame)
                    wrote_something = True
                except queue.Empty:
                    pass

            # 音声チャンクを書き込む（ブロッキング待機で途切れを防ぐ）
            try:
                audio_chunk = audio_queue.get(timeout=0.02)
                self._video_encoder.write_audio(audio_chunk)
                wrote_something = True
            except queue.Empty:
                pass

    def _on_transcribe_complete(self, result: TranscribeResult, output_path: Path) -> None:
        """文字起こし完了時のコールバック."""
        text = result.text

        # TextPostProcessor が利用可能な場合は LLM で後処理
        if self._text_post_processor is not None:
            post_result = self._text_post_processor.process(text)
            corrected_text = post_result.corrected_text
            summary = post_result.summary
            theme = post_result.theme
            if post_result.used_llm:
                logger.info("LLM による後処理を適用しました。")
            else:
                logger.info("LLM が利用不可のため、フォールバック処理を適用しました。")
        else:
            # 従来のテーマ生成のみ
            corrected_text = text
            summary = ""
            theme = self._theme_generator.generate(text)

        logger.info("テーマを生成しました: %s", theme)

        # メモを保存
        self._memo_store.create(
            text=corrected_text,
            theme=theme,
            output_file=output_path,
            summary=summary,
        )
        logger.info("メモを保存しました。テーマ: %s", theme)

        # GUI のメモ一覧を更新（on_memo_saved コールバック経由）
        if self._on_memo_saved_callback is not None:
            if self._root is not None:
                self._root.after_idle(self._on_memo_saved_callback)
            else:
                self._on_memo_saved_callback()
