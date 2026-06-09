"""MemoStore のユニットテストおよびプロパティテスト.

**Validates: Requirements 8.1, 8.2, 8.3, 9.1, 9.5**
"""

from __future__ import annotations

import math
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from screen_audio_recorder.memo_store import MemoStore
from screen_audio_recorder.models import Memo, MemoPage


# ---------------------------------------------------------------------------
# テスト用フィクスチャ
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> MemoStore:
    """一時ディレクトリを使用した MemoStore インスタンスを返す."""
    return MemoStore(data_path=tmp_path / "memos.json")


# ---------------------------------------------------------------------------
# ユニットテスト: 初期化
# ---------------------------------------------------------------------------


class TestMemoStoreInit:
    """MemoStore の初期化テスト."""

    def test_data_file_not_created_on_init(self, tmp_path: Path) -> None:
        """初期化時点ではデータファイルは作成されない（遅延作成）."""
        data_path = tmp_path / "memos.json"
        MemoStore(data_path=data_path)
        # ファイルは create() が呼ばれるまで存在しなくてよい
        # ただしディレクトリは作成される
        assert data_path.parent.exists()

    def test_data_dir_created_automatically(self, tmp_path: Path) -> None:
        """データディレクトリが自動作成される."""
        data_path = tmp_path / "subdir" / "memos.json"
        MemoStore(data_path=data_path)
        assert data_path.parent.exists()

    def test_default_path_under_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """デフォルトのデータパスが Path.home() 配下にある（要件 8.2）."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        store = MemoStore()
        assert store.data_path.is_relative_to(tmp_path)


# ---------------------------------------------------------------------------
# ユニットテスト: create()
# ---------------------------------------------------------------------------


class TestMemoStoreCreate:
    """MemoStore.create() のテスト."""

    def test_create_returns_memo(self, store: MemoStore, tmp_path: Path) -> None:
        """create() が Memo オブジェクトを返す."""
        memo = store.create("テスト本文", "テーマ", tmp_path / "rec.mp4")
        assert isinstance(memo, Memo)

    def test_create_assigns_uuid(self, store: MemoStore, tmp_path: Path) -> None:
        """create() が UUID4 形式の ID を割り当てる."""
        import re
        memo = store.create("本文", "テーマ", tmp_path / "rec.mp4")
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        assert re.match(uuid_pattern, memo.id), f"ID {memo.id!r} が UUID4 形式でない"

    def test_create_assigns_utc_timestamp(self, store: MemoStore, tmp_path: Path) -> None:
        """create() が UTC タイムスタンプを割り当てる."""
        before = datetime.now(tz=timezone.utc)
        memo = store.create("本文", "テーマ", tmp_path / "rec.mp4")
        after = datetime.now(tz=timezone.utc)
        assert before <= memo.created_at <= after
        assert memo.created_at.tzinfo is not None

    def test_create_stores_body(self, store: MemoStore, tmp_path: Path) -> None:
        """create() が本文を正しく保存する."""
        memo = store.create("本日の会議では重要な決定がありました。", "会議", tmp_path / "rec.mp4")
        assert memo.body == "本日の会議では重要な決定がありました。"

    def test_create_stores_theme(self, store: MemoStore, tmp_path: Path) -> None:
        """create() がテーマを正しく保存する."""
        memo = store.create("本文", "会議メモ", tmp_path / "rec.mp4")
        assert memo.theme == "会議メモ"

    def test_create_stores_output_file(self, store: MemoStore, tmp_path: Path) -> None:
        """create() が output_file を正しく保存する."""
        output_file = tmp_path / "recordings" / "2024-01-15_10-30-00.mp4"
        memo = store.create("本文", "テーマ", output_file)
        assert memo.output_file == output_file

    def test_create_persists_to_file(self, store: MemoStore, tmp_path: Path) -> None:
        """create() 後にデータファイルが作成される."""
        store.create("本文", "テーマ", tmp_path / "rec.mp4")
        assert store.data_path.exists()

    def test_create_multiple_memos(self, store: MemoStore, tmp_path: Path) -> None:
        """複数のメモを作成できる."""
        memo1 = store.create("本文1", "テーマ1", tmp_path / "rec1.mp4")
        memo2 = store.create("本文2", "テーマ2", tmp_path / "rec2.mp4")
        assert memo1.id != memo2.id

    def test_create_unique_ids(self, store: MemoStore, tmp_path: Path) -> None:
        """複数回 create() を呼んでも ID が重複しない."""
        ids = {store.create("本文", "テーマ", tmp_path / "rec.mp4").id for _ in range(10)}
        assert len(ids) == 10


# ---------------------------------------------------------------------------
# ユニットテスト: get_by_id()
# ---------------------------------------------------------------------------


class TestMemoStoreGetById:
    """MemoStore.get_by_id() のテスト."""

    def test_get_existing_memo(self, store: MemoStore, tmp_path: Path) -> None:
        """存在するメモを ID で取得できる."""
        created = store.create("本文", "テーマ", tmp_path / "rec.mp4")
        retrieved = store.get_by_id(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id

    def test_get_nonexistent_memo_returns_none(self, store: MemoStore) -> None:
        """存在しない ID に対して None を返す."""
        result = store.get_by_id("00000000-0000-4000-8000-000000000000")
        assert result is None

    def test_get_by_id_preserves_fields(self, store: MemoStore, tmp_path: Path) -> None:
        """取得したメモのフィールドが作成時と一致する."""
        output_file = tmp_path / "rec.mp4"
        created = store.create("詳細な本文テキスト", "テーマ文字列", output_file)
        retrieved = store.get_by_id(created.id)
        assert retrieved is not None
        assert retrieved.body == created.body
        assert retrieved.theme == created.theme
        assert retrieved.output_file == created.output_file


# ---------------------------------------------------------------------------
# ユニットテスト: get_all()
# ---------------------------------------------------------------------------


class TestMemoStoreGetAll:
    """MemoStore.get_all() のテスト."""

    def test_empty_store_returns_empty_page(self, store: MemoStore) -> None:
        """メモが存在しない場合は空のページを返す."""
        page = store.get_all()
        assert page.memos == []
        assert page.total == 0

    def test_returns_all_memos(self, store: MemoStore, tmp_path: Path) -> None:
        """作成したすべてのメモが返される."""
        for i in range(5):
            store.create(f"本文{i}", f"テーマ{i}", tmp_path / f"rec{i}.mp4")
        page = store.get_all(page_size=10)
        assert page.total == 5
        assert len(page.memos) == 5

    def test_sorted_descending_by_created_at(self, store: MemoStore, tmp_path: Path) -> None:
        """メモが作成日時の降順で返される（要件 9.1）."""
        for i in range(3):
            store.create(f"本文{i}", f"テーマ{i}", tmp_path / f"rec{i}.mp4")
        page = store.get_all(page_size=10)
        dates = [m.created_at for m in page.memos]
        assert dates == sorted(dates, reverse=True)

    def test_pagination_page_size(self, store: MemoStore, tmp_path: Path) -> None:
        """page_size で返却件数が制限される（要件 9.5）."""
        for i in range(10):
            store.create(f"本文{i}", f"テーマ{i}", tmp_path / f"rec{i}.mp4")
        page = store.get_all(page=1, page_size=3)
        assert len(page.memos) == 3

    def test_pagination_total_pages(self, store: MemoStore, tmp_path: Path) -> None:
        """total_pages が ceil(total / page_size) と等しい（要件 9.5）."""
        for i in range(10):
            store.create(f"本文{i}", f"テーマ{i}", tmp_path / f"rec{i}.mp4")
        page = store.get_all(page=1, page_size=3)
        assert page.total_pages == math.ceil(10 / 3)

    def test_pagination_second_page(self, store: MemoStore, tmp_path: Path) -> None:
        """2 ページ目のメモが正しく返される."""
        for i in range(5):
            store.create(f"本文{i}", f"テーマ{i}", tmp_path / f"rec{i}.mp4")
        page1 = store.get_all(page=1, page_size=3)
        page2 = store.get_all(page=2, page_size=3)
        ids_page1 = {m.id for m in page1.memos}
        ids_page2 = {m.id for m in page2.memos}
        assert ids_page1.isdisjoint(ids_page2)

    def test_memo_page_metadata(self, store: MemoStore, tmp_path: Path) -> None:
        """MemoPage のメタデータが正しい."""
        for i in range(5):
            store.create(f"本文{i}", f"テーマ{i}", tmp_path / f"rec{i}.mp4")
        page = store.get_all(page=1, page_size=3)
        assert page.page == 1
        assert page.page_size == 3
        assert page.total == 5


# ---------------------------------------------------------------------------
# ユニットテスト: delete()
# ---------------------------------------------------------------------------


class TestMemoStoreDelete:
    """MemoStore.delete() のテスト."""

    def test_delete_existing_memo(self, store: MemoStore, tmp_path: Path) -> None:
        """存在するメモを削除できる（要件 8.3）."""
        memo = store.create("本文", "テーマ", tmp_path / "rec.mp4")
        store.delete(memo.id)
        assert store.get_by_id(memo.id) is None

    def test_delete_nonexistent_memo_no_error(self, store: MemoStore) -> None:
        """存在しない ID を削除しても例外が発生しない."""
        store.delete("00000000-0000-4000-8000-000000000000")  # エラーなし

    def test_delete_does_not_affect_other_memos(self, store: MemoStore, tmp_path: Path) -> None:
        """削除操作が他のメモに影響しない."""
        memo1 = store.create("本文1", "テーマ1", tmp_path / "rec1.mp4")
        memo2 = store.create("本文2", "テーマ2", tmp_path / "rec2.mp4")
        store.delete(memo1.id)
        assert store.get_by_id(memo2.id) is not None

    def test_delete_reduces_total_count(self, store: MemoStore, tmp_path: Path) -> None:
        """削除後に total が減少する."""
        memo = store.create("本文", "テーマ", tmp_path / "rec.mp4")
        store.create("本文2", "テーマ2", tmp_path / "rec2.mp4")
        store.delete(memo.id)
        page = store.get_all()
        assert page.total == 1


# ---------------------------------------------------------------------------
# ユニットテスト: JSON 永続化
# ---------------------------------------------------------------------------


class TestMemoStoreJsonPersistence:
    """JSON ファイルの永続化テスト."""

    def test_data_survives_reload(self, tmp_path: Path) -> None:
        """データが別インスタンスで読み込んでも保持される."""
        data_path = tmp_path / "memos.json"
        store1 = MemoStore(data_path=data_path)
        created = store1.create("本文", "テーマ", tmp_path / "rec.mp4")

        store2 = MemoStore(data_path=data_path)
        retrieved = store2.get_by_id(created.id)
        assert retrieved is not None
        assert retrieved.body == "本文"

    def test_json_schema_version(self, tmp_path: Path) -> None:
        """JSON ファイルに version フィールドが含まれる."""
        import json
        data_path = tmp_path / "memos.json"
        store = MemoStore(data_path=data_path)
        store.create("本文", "テーマ", tmp_path / "rec.mp4")
        data = json.loads(data_path.read_text(encoding="utf-8"))
        assert data["version"] == 1

    def test_corrupted_file_handled_gracefully(self, tmp_path: Path) -> None:
        """壊れた JSON ファイルがあっても例外が発生しない."""
        data_path = tmp_path / "memos.json"
        data_path.write_text("{ invalid json }", encoding="utf-8")
        store = MemoStore(data_path=data_path)
        page = store.get_all()
        assert page.total == 0

    def test_empty_file_handled_gracefully(self, tmp_path: Path) -> None:
        """空のファイルがあっても例外が発生しない."""
        data_path = tmp_path / "memos.json"
        data_path.write_text("", encoding="utf-8")
        store = MemoStore(data_path=data_path)
        page = store.get_all()
        assert page.total == 0

    def test_created_at_stored_as_utc_z_format(self, tmp_path: Path) -> None:
        """created_at が ISO 8601 UTC 形式（末尾 Z）で保存される."""
        import json
        data_path = tmp_path / "memos.json"
        store = MemoStore(data_path=data_path)
        store.create("本文", "テーマ", tmp_path / "rec.mp4")
        data = json.loads(data_path.read_text(encoding="utf-8"))
        created_at_str = data["memos"][0]["created_at"]
        assert created_at_str.endswith("Z"), f"created_at {created_at_str!r} が Z で終わっていない"


# ---------------------------------------------------------------------------
# プロパティテスト: プロパティ 11 — メモのラウンドトリップ
# ---------------------------------------------------------------------------


@given(
    body=st.text(min_size=0, max_size=500),
    theme=st.text(min_size=0, max_size=10),
    output_file_str=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
        min_size=1,
        max_size=200,
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_memo_round_trip(
    tmp_path: Path,
    body: str,
    theme: str,
    output_file_str: str,
) -> None:
    """プロパティ 11: メモの保存と読み込みのラウンドトリップ.

    任意のメモデータを保存後に読み込んだメモは、
    作成日時・テーマ・本文・OutputFile パスのすべてのフィールドを正確に保持していなければならない。

    **Validates: Requirements 8.1**
    """
    # 各テスト実行ごとに独立したストアを使用する
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoStore(data_path=Path(tmpdir) / "memos.json")
        output_file = Path(output_file_str)

        created = store.create(body, theme, output_file)
        retrieved = store.get_by_id(created.id)

        assert retrieved is not None, "保存したメモが get_by_id() で取得できない"
        assert retrieved.id == created.id
        assert retrieved.body == body
        assert retrieved.theme == theme
        assert retrieved.output_file == output_file
        # created_at は秒精度で一致する（JSON は秒精度で保存）
        assert retrieved.created_at.replace(microsecond=0) == created.created_at.replace(microsecond=0)
        assert retrieved.created_at.tzinfo is not None


# ---------------------------------------------------------------------------
# プロパティテスト: プロパティ 12 — 削除後の不存在
# ---------------------------------------------------------------------------


@given(
    body=st.text(min_size=0, max_size=200),
    theme=st.text(min_size=0, max_size=10),
)
@settings(max_examples=100)
def test_memo_delete_not_found(
    body: str,
    theme: str,
) -> None:
    """プロパティ 12: メモ削除後の不存在.

    任意の保存済みメモに対して、削除操作後に get_by_id() を呼び出した結果は None でなければならない。

    **Validates: Requirements 8.3**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        store = MemoStore(data_path=tmpdir_path / "memos.json")
        output_file = tmpdir_path / "rec.mp4"

        memo = store.create(body, theme, output_file)
        store.delete(memo.id)

        result = store.get_by_id(memo.id)
        assert result is None, f"削除後も get_by_id({memo.id!r}) が None 以外を返した: {result}"


# ---------------------------------------------------------------------------
# プロパティテスト: プロパティ 13 — 降順ソート
# ---------------------------------------------------------------------------


@given(
    n=st.integers(min_value=2, max_value=20),
)
@settings(max_examples=100)
def test_memo_get_all_sorted_descending(
    n: int,
) -> None:
    """プロパティ 13: メモ一覧の降順ソート.

    任意の順序で作成された複数のメモに対して、
    get_all() が返すメモリストは作成日時の降順でソートされていなければならない。

    **Validates: Requirements 9.1**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        store = MemoStore(data_path=tmpdir_path / "memos.json")

        for i in range(n):
            store.create(f"本文{i}", f"テーマ{i}"[:10], tmpdir_path / f"rec{i}.mp4")

        page = store.get_all(page_size=n + 1)
        dates = [m.created_at for m in page.memos]

        assert dates == sorted(dates, reverse=True), (
            f"メモが降順でソートされていない: {dates}"
        )


# ---------------------------------------------------------------------------
# プロパティテスト: プロパティ 16 — ページネーション
# ---------------------------------------------------------------------------


@given(
    n=st.integers(min_value=101, max_value=200),
    page_size=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=50, deadline=None)
def test_memo_pagination(
    n: int,
    page_size: int,
) -> None:
    """プロパティ 16: ページネーション適用.

    N > 100 件のメモに対して、get_all() は一度に最大 page_size 件のメモのみを返し、
    total_pages が ceil(N / page_size) と等しくなければならない。

    **Validates: Requirements 9.5**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        store = MemoStore(data_path=tmpdir_path / "memos.json")

        for i in range(n):
            store.create(f"本文{i}", f"テーマ{i}"[:10], tmpdir_path / f"rec{i}.mp4")

        page = store.get_all(page=1, page_size=page_size)

        assert len(page.memos) <= page_size, (
            f"返却件数 {len(page.memos)} が page_size {page_size} を超えている"
        )
        expected_total_pages = math.ceil(n / page_size)
        assert page.total_pages == expected_total_pages, (
            f"total_pages {page.total_pages} が期待値 {expected_total_pages} と異なる"
            f" (n={n}, page_size={page_size})"
        )
        assert page.total == n
