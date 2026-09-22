"""MemoStore の変更リスナー機構のユニットテスト（ADR-004）."""

from __future__ import annotations

from pathlib import Path

from screen_audio_recorder.memo_store import MemoStore


def _store(tmp_path: Path) -> MemoStore:
    return MemoStore(data_path=tmp_path / "memos.json")


def test_listener_fires_on_create(tmp_path: Path) -> None:
    store = _store(tmp_path)
    hits = []
    store.add_listener(lambda: hits.append("x"))
    store.create(text="本文", theme="t", output_file=Path("x.wav"), summary="s")
    assert len(hits) == 1


def test_listener_fires_on_update_memo(tmp_path: Path) -> None:
    store = _store(tmp_path)
    memo = store.create(text="本文", theme="t", output_file=Path("x.wav"), summary="s")
    hits = []
    store.add_listener(lambda: hits.append("x"))
    store.update_memo(memo_id=memo.id, body="更新", theme="t2", summary="s2")
    assert len(hits) == 1


def test_listener_fires_on_update_theme(tmp_path: Path) -> None:
    store = _store(tmp_path)
    memo = store.create(text="本文", theme="t", output_file=Path("x.wav"), summary="s")
    hits = []
    store.add_listener(lambda: hits.append("x"))
    store.update_theme(memo.id, "新テーマ")
    assert len(hits) == 1


def test_listener_fires_on_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    memo = store.create(text="本文", theme="t", output_file=Path("x.wav"), summary="s")
    hits = []
    store.add_listener(lambda: hits.append("x"))
    store.delete(memo.id)
    assert len(hits) == 1


def test_no_fire_when_delete_nonexistent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    hits = []
    store.add_listener(lambda: hits.append("x"))
    store.delete("does-not-exist")
    assert hits == []


def test_no_fire_when_update_nonexistent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    hits = []
    store.add_listener(lambda: hits.append("x"))
    store.update_memo(memo_id="nope", body="b", theme="t", summary="s")
    store.update_theme("nope", "t")
    assert hits == []


def test_remove_listener(tmp_path: Path) -> None:
    store = _store(tmp_path)
    hits = []
    cb = lambda: hits.append("x")  # noqa: E731
    store.add_listener(cb)
    store.remove_listener(cb)
    store.create(text="本文", theme="t", output_file=Path("x.wav"), summary="s")
    assert hits == []


def test_listener_exception_does_not_break_save(tmp_path: Path) -> None:
    store = _store(tmp_path)

    def _boom() -> None:
        raise RuntimeError("boom")

    hits = []
    store.add_listener(_boom)
    store.add_listener(lambda: hits.append("ok"))
    # 例外を送出せず、後続リスナーも呼ばれ、保存も成功する
    memo = store.create(text="本文", theme="t", output_file=Path("x.wav"), summary="s")
    assert hits == ["ok"]
    assert store.get_by_id(memo.id) is not None


def test_multiple_listeners_all_called(tmp_path: Path) -> None:
    store = _store(tmp_path)
    hits = []
    store.add_listener(lambda: hits.append("a"))
    store.add_listener(lambda: hits.append("b"))
    store.create(text="本文", theme="t", output_file=Path("x.wav"), summary="s")
    assert sorted(hits) == ["a", "b"]
