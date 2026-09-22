"""ExportManager のユニットテスト."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from screen_audio_recorder.export.export_manager import ExportManager
from screen_audio_recorder.memo_store import MemoStore
from screen_audio_recorder.models import ExportSettings


class _FakeExporter:
    """export() の呼び出し回数と引数を記録するスタブ."""

    def __init__(self) -> None:
        self.calls: list[int] = []
        self._lock = threading.Lock()
        self.event = threading.Event()

    def export(self, memos, output_path, settings=None) -> None:  # noqa: ANN001
        with self._lock:
            self.calls.append(len(memos))
        self.event.set()


def _make_store(tmp_path: Path) -> MemoStore:
    return MemoStore(data_path=tmp_path / "memos.json")


def test_export_now_calls_exporter(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.create(text="本文", theme="t", output_file=Path("x.wav"), summary="s")
    exporter = _FakeExporter()
    mgr = ExportManager(
        memo_store=store,
        settings=ExportSettings(html_enabled=False),  # 手動なので無効でも実行される
        html_exporter=exporter,
    )
    mgr.export_now()
    assert exporter.calls == [1]


def test_disabled_does_not_export_on_change(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    exporter = _FakeExporter()
    mgr = ExportManager(
        memo_store=store,
        settings=ExportSettings(html_enabled=False),
        html_exporter=exporter,
        debounce_seconds=0.05,
    )
    mgr.start()
    try:
        store.create(text="本文", theme="t", output_file=Path("x.wav"), summary="s")
        # 無効なのでタイマーは張られない
        time.sleep(0.2)
        assert exporter.calls == []
    finally:
        mgr.stop()


def test_enabled_exports_after_debounce(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    exporter = _FakeExporter()
    mgr = ExportManager(
        memo_store=store,
        settings=ExportSettings(html_enabled=True),
        html_exporter=exporter,
        debounce_seconds=0.05,
    )
    mgr.start()
    try:
        store.create(text="本文", theme="t", output_file=Path("x.wav"), summary="s")
        assert exporter.event.wait(timeout=2.0)
        assert exporter.calls == [1]
    finally:
        mgr.stop()


def test_debounce_coalesces_rapid_changes(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    exporter = _FakeExporter()
    mgr = ExportManager(
        memo_store=store,
        settings=ExportSettings(html_enabled=True),
        html_exporter=exporter,
        debounce_seconds=0.3,
    )
    mgr.start()
    try:
        # デバウンス窓内に複数回更新 → 1 回にまとまる
        for i in range(5):
            store.create(
                text=f"本文{i}", theme="t", output_file=Path("x.wav"), summary="s"
            )
            time.sleep(0.02)
        assert exporter.event.wait(timeout=2.0)
        # 少し待って追加発火がないことを確認
        time.sleep(0.4)
        assert len(exporter.calls) == 1
        assert exporter.calls[0] == 5  # 全 5 件が渡る
    finally:
        mgr.stop()


def test_stop_cancels_pending_timer(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    exporter = _FakeExporter()
    mgr = ExportManager(
        memo_store=store,
        settings=ExportSettings(html_enabled=True),
        html_exporter=exporter,
        debounce_seconds=0.5,
    )
    mgr.start()
    store.create(text="本文", theme="t", output_file=Path("x.wav"), summary="s")
    mgr.stop()  # デバウンス発火前に停止
    time.sleep(0.7)
    assert exporter.calls == []


def test_exporter_exception_does_not_propagate(tmp_path: Path) -> None:
    store = _make_store(tmp_path)

    class _Boom:
        def export(self, *a, **k):  # noqa: ANN002, ANN003
            raise RuntimeError("boom")

    mgr = ExportManager(
        memo_store=store,
        settings=ExportSettings(html_enabled=True),
        html_exporter=_Boom(),
    )
    # 例外を送出せず握りつぶすこと
    mgr.export_now()
