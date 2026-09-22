"""ExportManager: メモ変更を購読し、継続的に外部形式へ出力する調整役.

ADR-004 参照。MemoStore のリスナーとして登録され、メモの追加・更新・削除の
たびに通知を受ける。短時間に複数の更新が来た場合はデバウンスでまとめ、
別スレッドで HtmlExporter を呼び出して GUI をブロックしない。
"""

from __future__ import annotations

import logging
import threading

from screen_audio_recorder.export.html_exporter import HtmlExporter
from screen_audio_recorder.export_settings_store import (
    load_export_settings,
    resolve_output_html_path,
)
from screen_audio_recorder.memo_store import MemoStore
from screen_audio_recorder.models import ExportSettings

logger = logging.getLogger(__name__)

# デバウンス既定値（秒）。連続更新をまとめて 1 回出力する。
_DEFAULT_DEBOUNCE_SECONDS = 1.5


class ExportManager:
    """メモ変更を購読して HTML を継続出力するマネージャ."""

    def __init__(
        self,
        memo_store: MemoStore,
        settings: ExportSettings | None = None,
        html_exporter: HtmlExporter | None = None,
        debounce_seconds: float = _DEFAULT_DEBOUNCE_SECONDS,
    ) -> None:
        """ExportManager を初期化する.

        Args:
            memo_store: 購読対象の MemoStore
            settings: エクスポート設定。None の場合はストアから読み込む。
            html_exporter: HTML 出力担当。None の場合は既定の HtmlExporter。
            debounce_seconds: デバウンス秒数。
        """
        self._memo_store = memo_store
        self._settings = settings if settings is not None else load_export_settings()
        self._exporter = html_exporter if html_exporter is not None else HtmlExporter()
        self._debounce_seconds = max(0.0, debounce_seconds)

        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._subscribed = False

    # ------------------------------------------------------------------
    # ライフサイクル
    # ------------------------------------------------------------------

    def start(self) -> None:
        """MemoStore の変更購読を開始する."""
        if not self._subscribed:
            self._memo_store.add_listener(self._on_memo_changed)
            self._subscribed = True

    def stop(self) -> None:
        """購読を解除し、保留中のデバウンスタイマーを取り消す."""
        if self._subscribed:
            self._memo_store.remove_listener(self._on_memo_changed)
            self._subscribed = False
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def update_settings(self, settings: ExportSettings) -> None:
        """エクスポート設定を差し替える（設定タブからの保存時に呼ぶ）."""
        self._settings = settings

    # ------------------------------------------------------------------
    # 内部実装
    # ------------------------------------------------------------------

    def _on_memo_changed(self) -> None:
        """MemoStore からの変更通知（リスナー）。デバウンスして出力を予約する."""
        if not self._settings.html_enabled:
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_seconds, self._run_export)
            self._timer.daemon = True
            self._timer.start()

    def export_now(self) -> None:
        """デバウンスを介さず即座に 1 回出力する（「今すぐ出力」ボタン用）.

        html_enabled の値に関わらず実行する（手動トリガーのため）。
        """
        self._run_export(force=True)

    def _run_export(self, force: bool = False) -> None:
        """実際の HTML 出力を行う（タイマーまたは手動から呼ばれる）."""
        if not force and not self._settings.html_enabled:
            return
        try:
            # 最新の全メモを取得（大きなページサイズで全件）
            page = self._memo_store.get_all(page=1, page_size=1_000_000)
            output_path = resolve_output_html_path(self._settings)
            self._exporter.export(page.memos, output_path, self._settings)
        except Exception:
            # 出力失敗はアプリ本体（録画・保存）を妨げない
            logger.exception("HTML の継続出力に失敗しました。")
