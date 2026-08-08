"""screen-audio-recorder アプリケーションのエントリーポイント.

MainWindow・RecorderController・MemoStore・ErrorNotifier を初期化して結合し、
~/.screen-audio-recorder/ ディレクトリ構造を初回起動時に自動作成する。

**Validates: Requirements 1.1, 1.2, 1.3**
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import tkinter as tk
from pathlib import Path


def _setup_logging() -> None:
    """アプリケーションのロギングを設定する.

    ログファイルは ~/.screen-audio-recorder/app.log に出力する。
    ローテーション: 5MB × 3 世代。

    verbose_logging が有効な場合:
        - ファイル: DEBUG レベル
        - コンソール: DEBUG レベル
    verbose_logging が無効な場合（デフォルト）:
        - ファイル: INFO レベル
        - コンソール: WARNING レベル

    要件 1.3: ユーザーのホームディレクトリ配下にのみファイルを書き込む。
    """
    from screen_audio_recorder.app_settings_store import load_app_settings

    app_settings = load_app_settings()
    verbose = app_settings.verbose_logging

    log_dir = Path.home() / "Documents" / "screen-audio-recorder"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # ファイルハンドラ（ローテーション）
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # コンソールハンドラ
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)


def _ensure_data_dirs() -> None:
    """データディレクトリ構造を初回起動時に自動作成する.

    作成するディレクトリ:
        ~/.screen-audio-recorder/
        ~/.screen-audio-recorder/recordings/
        ~/.screen-audio-recorder/models/

    要件 1.3: ユーザーのホームディレクトリ配下にのみファイルを書き込む。
    """
    base = Path.home() / "Documents" / "screen-audio-recorder"
    for subdir in ("", "recordings", "models"):
        (base / subdir).mkdir(parents=True, exist_ok=True)


# 自動更新用リポジトリ設定
_REPO_OWNER = "taicheng-huang"
_REPO_NAME = "screen-audio-recorder"


def main() -> None:
    """アプリケーションのメインエントリーポイント.

    要件 1.1: 管理者権限なしで起動できる。
    要件 1.2: Windows 10 (1903+) および Windows 11 上で動作する。
    要件 1.3: ユーザーのホームディレクトリ配下にのみファイルを書き込む。
    """
    # コンソールウィンドウを非表示にする（PyInstaller の console=False が効かない場合の保険）
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE = 0
    except Exception:
        pass

    # DPI awareness を設定（tkinter と mss の座標を一致させる）
    # Per-Monitor DPI Aware (2) に設定することで、
    # tkinter の座標が物理ピクセルと一致し、mss のキャプチャ範囲が正確になる。
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass

    # ロギングを設定
    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("screen-audio-recorder を起動しています...")

    # データディレクトリを作成
    _ensure_data_dirs()

    # 各コンポーネントを初期化
    from screen_audio_recorder.audio_capture import AudioCapture
    from screen_audio_recorder.error_notifier import ErrorNotifier
    from screen_audio_recorder.file_store import FileStore
    from screen_audio_recorder.gui.main_window import MainWindow
    from screen_audio_recorder.llm_client import LlmClient
    from screen_audio_recorder.llm_settings_store import load_all_settings as _load_all_settings, load_settings as load_llm_settings
    from screen_audio_recorder.memo_store import MemoStore
    from screen_audio_recorder.recorder_controller import RecorderController
    from screen_audio_recorder.screen_capture import ScreenCapture
    from screen_audio_recorder.text_post_processor import TextPostProcessor
    from screen_audio_recorder.theme_generator import ThemeGeneratorService
    from screen_audio_recorder.transcriber import Transcriber
    from screen_audio_recorder.video_encoder import VideoEncoder

    # tkinter ルートウィンドウを作成
    root = tk.Tk()
    root.minsize(640, 480)

    # コンポーネントを初期化
    error_notifier = ErrorNotifier(root=root)
    memo_store = MemoStore()
    file_store = FileStore()
    screen_capture = ScreenCapture()
    audio_capture = AudioCapture(error_notifier=error_notifier)
    video_encoder = VideoEncoder(error_notifier=error_notifier)

    # LLM 設定を読み込み（Whisper モデルサイズも含む）
    llm_settings, transcriber_settings, aws_settings = _load_all_settings()

    transcriber = Transcriber(
        model_size=llm_settings.whisper_model_size,
        error_notifier=error_notifier,
        memo_store=memo_store,
        lazy_load=True,  # モデルロードを遅延させる（メインウィンドウ表示後にバックグラウンドで実行）
        transcriber_settings=transcriber_settings,
        aws_settings=aws_settings,
    )
    theme_generator = ThemeGeneratorService()

    # LLM コンポーネントを初期化
    llm_client = LlmClient(llm_settings, aws_settings)
    text_post_processor = TextPostProcessor(
        llm_client=llm_client,
        theme_generator_fallback=theme_generator,
        settings=llm_settings,
    )

    # LLM 状態をログに出力
    if llm_client.available:
        logger.info(
            "LLM 有効: バックエンド=%s",
            llm_settings.backend.value,
        )
    else:
        logger.warning(
            "LLM 無効: バックエンド=%s。"
            "LLM 設定タブでモデルの設定を行ってください。"
            "設定が完了するまで janome フォールバックで動作します。",
            llm_settings.backend.value,
        )

    # LLM 設定変更時のコールバック
    def on_llm_settings_changed(new_settings, new_aws_settings=None):
        llm_client.reload(new_settings, new_aws_settings)
        text_post_processor.update_settings(new_settings)
        logger.info("LLM 設定を更新しました。バックエンド: %s", new_settings.backend.value)

    # RecorderController を初期化（全コンポーネントを結合）
    recorder_controller = RecorderController(
        screen_capture=screen_capture,
        audio_capture=audio_capture,
        video_encoder=video_encoder,
        transcriber=transcriber,
        theme_generator=theme_generator,
        memo_store=memo_store,
        file_store=file_store,
        error_notifier=error_notifier,
        root=root,
        text_post_processor=text_post_processor,
    )

    # Updater の初期化
    from screen_audio_recorder.updater import Updater
    import screen_audio_recorder

    updater = Updater(
        repo_owner=_REPO_OWNER,
        repo_name=_REPO_NAME,
        current_version=screen_audio_recorder.__version__,
        exe_path=Path(sys.executable),
    )

    # 起動時バックアップクリーンアップ
    updater.cleanup_old_backups()

    # MainWindow を初期化
    main_window = MainWindow(
        root=root,
        recorder_controller=recorder_controller,
        memo_store=memo_store,
        audio_capture=audio_capture,
        on_llm_settings_changed=on_llm_settings_changed,
        updater=updater,
    )

    logger.info("アプリケーションの初期化が完了しました。")

    # Whisper モデルをバックグラウンドでロード開始
    # 完了後に MainWindow の録画ボタンを有効化する
    def _on_model_loaded():
        main_window.set_ready()
        logger.info("Whisper モデルのバックグラウンドロードが完了しました。")

    transcriber.load_model_async(callback=_on_model_loaded, root=root)

    # tkinter イベントループを開始
    try:
        root.mainloop()
    except KeyboardInterrupt:
        logger.info("キーボード割り込みにより終了します。")
    finally:
        # 録画中の場合は停止
        if recorder_controller.is_recording:
            try:
                recorder_controller.stop_recording()
            except Exception:
                logger.exception("終了時の録画停止に失敗しました。")
        # ローカル LLM サーバーを停止
        llm_client.shutdown()
        logger.info("screen-audio-recorder を終了しました。")


if __name__ == "__main__":
    main()
