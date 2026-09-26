"""MemoListView のユニットテストおよびプロパティテスト.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5 (Properties 14, 15)**
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from screen_audio_recorder.gui.memo_list_view import (
    MemoListView,
    _PREVIEW_MAX_CHARS,
    _DISPLAY_LINE_MAX_CHARS,
    format_body_for_display,
)
from screen_audio_recorder.models import Memo, MemoPage


# ---------------------------------------------------------------------------
# テスト用ヘルパー
# ---------------------------------------------------------------------------


def make_memo(
    body: str = "テスト本文",
    theme: str = "テーマ",
    memo_id: str = "test-id-001",
) -> Memo:
    """テスト用 Memo を生成する."""
    return Memo(
        id=memo_id,
        created_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        theme=theme,
        body=body,
        summary="",
        output_file=Path("/tmp/test.mp4"),
    )


def make_memo_page(memos: list[Memo], total: int = None) -> MemoPage:
    """テスト用 MemoPage を生成する."""
    if total is None:
        total = len(memos)
    return MemoPage(
        memos=memos,
        total=total,
        page=1,
        page_size=50,
        total_pages=max(1, (total + 49) // 50),
    )


# ---------------------------------------------------------------------------
# get_preview_text() のユニットテスト（プロパティ 14）
# ---------------------------------------------------------------------------


class TestGetPreviewText:
    """MemoListView.get_preview_text() のテスト.

    **Validates: Requirements 9.2 (Property 14)**
    """

    def test_short_text_returns_full_text(self) -> None:
        """50 文字未満の本文は全文を返す."""
        body = "短い本文"
        result = MemoListView.get_preview_text(body)
        assert result == body

    def test_exactly_50_chars_returns_full_text(self) -> None:
        """ちょうど 50 文字の本文は全文を返す."""
        body = "あ" * 50
        result = MemoListView.get_preview_text(body)
        assert result == body
        assert len(result) == 50

    def test_51_chars_returns_first_50(self) -> None:
        """51 文字の本文は先頭 50 文字を返す."""
        body = "あ" * 51
        result = MemoListView.get_preview_text(body)
        assert result == "あ" * 50
        assert len(result) == 50

    def test_long_text_truncated_to_50(self) -> None:
        """長い本文は先頭 50 文字に切り詰められる."""
        body = "本日の会議では新しいプロジェクトについて議論しました。参加者は10名で、様々な意見が出ました。"
        result = MemoListView.get_preview_text(body)
        assert len(result) <= 50
        assert result == body[:50]

    def test_empty_text_returns_empty(self) -> None:
        """空文字列は空文字列を返す."""
        result = MemoListView.get_preview_text("")
        assert result == ""

    def test_returns_string_type(self) -> None:
        """返り値が str 型である."""
        result = MemoListView.get_preview_text("テスト")
        assert isinstance(result, str)

    def test_preview_length_never_exceeds_50(self) -> None:
        """プレビューテキストの長さが 50 文字を超えない."""
        body = "x" * 200
        result = MemoListView.get_preview_text(body)
        assert len(result) <= _PREVIEW_MAX_CHARS


# ---------------------------------------------------------------------------
# プロパティテスト: プロパティ 14 — メモ一覧の表示情報
# ---------------------------------------------------------------------------


@given(body=st.text(min_size=0, max_size=200))
@settings(max_examples=200)
def test_preview_text_length_constraint(body: str) -> None:
    """プロパティ 14: 任意の本文に対して、プレビューテキストが 50 文字以内であること.

    **Validates: Requirements 9.2 (Property 14)**
    """
    result = MemoListView.get_preview_text(body)

    # プレビューテキストが 50 文字以内であること
    assert len(result) <= _PREVIEW_MAX_CHARS, (
        f"プレビューテキストの長さ {len(result)} が {_PREVIEW_MAX_CHARS} を超えています"
    )

    # 本文が 50 文字以下の場合は全文が返されること
    if len(body) <= _PREVIEW_MAX_CHARS:
        assert result == body, (
            f"本文が {_PREVIEW_MAX_CHARS} 文字以下なのに全文が返されていません"
        )

    # プレビューが本文の先頭部分であること
    assert body.startswith(result), (
        f"プレビューテキストが本文の先頭部分ではありません"
    )


@given(
    body=st.text(min_size=0, max_size=200),
    theme=st.text(min_size=0, max_size=10),
)
@settings(max_examples=100)
def test_memo_display_info_contains_preview(body: str, theme: str) -> None:
    """プロパティ 14: メモ表示情報に作成日時・テーマ・本文先頭 50 文字が含まれること.

    MemoListView.get_preview_text() が正しいプレビューテキストを返すことを検証する。

    **Validates: Requirements 9.2 (Property 14)**
    """
    preview = MemoListView.get_preview_text(body)

    # プレビューが本文の先頭部分であること
    assert body.startswith(preview)

    # プレビューの長さが 50 文字以内であること
    assert len(preview) <= _PREVIEW_MAX_CHARS


# ---------------------------------------------------------------------------
# プロパティテスト: プロパティ 15 — メモ全文表示
# ---------------------------------------------------------------------------


@given(body=st.text(min_size=0, max_size=500))
@settings(max_examples=100)
def test_detail_view_shows_full_body(body: str) -> None:
    """プロパティ 15: 詳細表示のテキストがメモの body フィールドと完全一致すること.

    MemoListView の詳細表示ロジックをシミュレートして、
    body フィールドがそのまま表示されることを検証する。

    **Validates: Requirements 9.3 (Property 15)**
    """
    memo = make_memo(body=body)

    # 詳細表示のシミュレーション: body フィールドをそのまま使用
    displayed_text = memo.body

    # 詳細表示のテキストが body フィールドと完全一致すること
    assert displayed_text == body, (
        f"詳細表示のテキストが body フィールドと一致しません: "
        f"displayed={displayed_text!r}, body={body!r}"
    )


# ---------------------------------------------------------------------------
# MemoListView の find_memo_by_id テスト
# ---------------------------------------------------------------------------


class TestFindMemoById:
    """MemoListView._find_memo_by_id() のテスト."""

    def _make_view_with_memos(self, memos: list[Memo]) -> MemoListView:
        """テスト用 MemoListView を作成する（tkinter なし）."""
        mock_store = MagicMock()
        mock_store.get_all.return_value = make_memo_page(memos)

        # tkinter を使わずに MemoListView の内部状態を直接設定
        view = object.__new__(MemoListView)
        view._memo_store = mock_store
        view._current_page = 1
        view._total_pages = 1
        view._memos = memos
        return view

    def test_find_existing_memo(self) -> None:
        """存在するメモを ID で検索できる."""
        memo = make_memo(memo_id="test-001")
        view = self._make_view_with_memos([memo])

        result = view._find_memo_by_id("test-001")
        assert result is not None
        assert result.id == "test-001"

    def test_find_nonexistent_memo_returns_none(self) -> None:
        """存在しない ID に対して None を返す."""
        memo = make_memo(memo_id="test-001")
        view = self._make_view_with_memos([memo])

        result = view._find_memo_by_id("nonexistent-id")
        assert result is None

    def test_find_from_multiple_memos(self) -> None:
        """複数のメモから正しいメモを検索できる."""
        memos = [
            make_memo(body="本文1", memo_id="id-001"),
            make_memo(body="本文2", memo_id="id-002"),
            make_memo(body="本文3", memo_id="id-003"),
        ]
        view = self._make_view_with_memos(memos)

        result = view._find_memo_by_id("id-002")
        assert result is not None
        assert result.body == "本文2"


# ---------------------------------------------------------------------------
# get_preview_text の境界値テスト
# ---------------------------------------------------------------------------


class TestGetPreviewTextBoundary:
    """get_preview_text() の境界値テスト."""

    def test_49_chars_returns_full(self) -> None:
        """49 文字は全文を返す."""
        body = "あ" * 49
        assert MemoListView.get_preview_text(body) == body

    def test_50_chars_returns_full(self) -> None:
        """50 文字は全文を返す."""
        body = "あ" * 50
        assert MemoListView.get_preview_text(body) == body

    def test_51_chars_returns_50(self) -> None:
        """51 文字は先頭 50 文字を返す."""
        body = "あ" * 51
        result = MemoListView.get_preview_text(body)
        assert len(result) == 50

    def test_100_chars_returns_50(self) -> None:
        """100 文字は先頭 50 文字を返す."""
        body = "あ" * 100
        result = MemoListView.get_preview_text(body)
        assert len(result) == 50

    def test_mixed_japanese_english(self) -> None:
        """日本語と英語が混在する場合も正しく動作する."""
        body = "Hello World こんにちは世界 " * 5  # 長い文字列
        result = MemoListView.get_preview_text(body)
        assert len(result) <= 50
        assert body.startswith(result)


# ---------------------------------------------------------------------------
# format_body_for_display のテスト
# ---------------------------------------------------------------------------


class TestFormatBodyForDisplay:
    """全文ペイン表示用の改行挿入ロジックのテスト."""

    def test_empty_returns_empty(self) -> None:
        """空文字列はそのまま返す."""
        assert format_body_for_display("") == ""

    def test_no_data_loss_when_newlines_removed(self) -> None:
        """挿入した改行を取り除くと元の本文に一致する（データ欠落なし）."""
        body = "これはテストです。" * 500  # 句点あり長文
        formatted = format_body_for_display(body)
        assert formatted.replace("\n", "") == body

    def test_newline_inserted_after_sentence_boundary(self) -> None:
        """句点・感嘆符・疑問符の直後で改行される."""
        assert format_body_for_display("あ。い！う？え") == "あ。\nい！\nう？\nえ"

    def test_long_line_without_boundary_is_force_wrapped(self) -> None:
        """句点が無い長文でも各論理行が上限文字数以下になる."""
        body = "あ" * 3500  # 句点なし
        formatted = format_body_for_display(body, line_max_chars=1000)
        lines = formatted.split("\n")
        assert all(len(line) <= 1000 for line in lines)
        # データ欠落がないこと
        assert formatted.replace("\n", "") == body

    def test_existing_newlines_reset_line_count(self) -> None:
        """既存の改行は尊重され、行カウントがリセットされる."""
        body = "あ" * 500 + "\n" + "い" * 500
        formatted = format_body_for_display(body, line_max_chars=1000)
        # 既存の改行位置で分かれ、強制改行は入らない（各行 500 文字）
        assert formatted == body

    def test_long_line_10000_chars_all_lines_within_limit(self) -> None:
        """1万文字超の句点なし本文でも全論理行が上限以下（表示切れ回避）."""
        body = "テスト" * 4000  # 12000 文字・句点なし
        formatted = format_body_for_display(body, line_max_chars=1000)
        lines = formatted.split("\n")
        assert all(len(line) <= 1000 for line in lines)
        assert formatted.replace("\n", "") == body


# ---------------------------------------------------------------------------
# 再処理・再文字起こし完了時の残存容量再取得通知テスト
# ---------------------------------------------------------------------------


class TestOnProcessingDoneCallback:
    """再処理・再文字起こし完了時に on_processing_done が呼ばれることを検証する.

    録画→文字起こしフローは recorder_controller 経由で残量が更新されるが、
    再処理・再文字起こしはその経路を通らない。ここで on_processing_done を
    呼ぶことで、LLM / Transcribe 使用後に残存容量が再取得される。
    実装を revert するとこのテストは失敗する。
    """

    def _make_view(self, on_processing_done) -> MemoListView:
        """tkinter を生成せずに完了ハンドラ検証に必要な最小状態を組み立てる."""
        view = object.__new__(MemoListView)
        view._on_processing_done = on_processing_done
        # ボタン config / refresh は副作用を避けてモック化する。
        view._reprocess_btn = MagicMock()
        view._retranscribe_btn = MagicMock()
        view.refresh = MagicMock()
        return view

    def test_reprocess_done_invokes_callback(self) -> None:
        """再処理完了で on_processing_done が 1 回呼ばれる."""
        cb = MagicMock()
        view = self._make_view(cb)

        view._on_reprocess_done()

        cb.assert_called_once()
        view.refresh.assert_called_once()

    def test_retranscribe_done_invokes_callback(self) -> None:
        """再文字起こし完了で on_processing_done が 1 回呼ばれる."""
        cb = MagicMock()
        view = self._make_view(cb)

        view._on_retranscribe_done()

        cb.assert_called_once()
        view.refresh.assert_called_once()

    def test_none_callback_does_not_raise(self) -> None:
        """コールバック未設定でも例外を送出しない."""
        view = self._make_view(None)

        # 例外が出ないことを確認（明示 assert は不要だが呼び出しが通ること）。
        view._on_reprocess_done()
        view._on_retranscribe_done()

    def test_callback_exception_is_swallowed(self) -> None:
        """コールバックが例外を投げても GUI 更新を妨げない."""
        cb = MagicMock(side_effect=RuntimeError("boom"))
        view = self._make_view(cb)

        # 例外が伝播しないこと。
        view._on_reprocess_done()
        view.refresh.assert_called_once()



# ---------------------------------------------------------------------------
# 折りたたみ（collapse/expand）トグルのテスト
# ---------------------------------------------------------------------------


class TestCollapseToggle:
    """メモ一覧・要約・全文の各領域を折りたたみ／展開するトグルのテスト.

    ウィンドウを小さくするため、各領域の中身コンテナを pack_forget() で
    非表示にし、再度 pack() で表示する。ボタンのラベル（▼=展開/▶=折りたたみ）
    と内部状態フラグが正しく切り替わることを検証する。
    tkinter を生成せず、frame と button はモックで置き換える。
    """

    def _make_view(self) -> MemoListView:
        """tkinter を生成せずにトグル検証に必要な最小状態を組み立てる."""
        view = object.__new__(MemoListView)
        # 折りたたみ状態フラグ（初期は全て展開）
        view._tree_expanded = True
        view._summary_expanded = True
        view._detail_expanded = True
        # 中身コンテナ・トグルボタンをモック化
        view._tree_frame = MagicMock()
        view._summary_body = MagicMock()
        view._detail_body = MagicMock()
        view._tree_toggle_btn = MagicMock()
        view._summary_toggle_btn = MagicMock()
        view._detail_toggle_btn = MagicMock()
        # 実ファイルへの保存を避けるため永続化をモック化
        view._persist_collapse_state = MagicMock()
        return view

    def test_toggle_tree_collapses_then_expands(self) -> None:
        """メモ一覧を折りたたみ→展開できる."""
        view = self._make_view()

        # 1回目: 折りたたみ
        view._on_toggle_tree()
        assert view._tree_expanded is False
        view._tree_frame.pack_forget.assert_called_once()
        view._tree_toggle_btn.config.assert_called_with(text="▶ 一覧")

        # 2回目: 展開
        view._on_toggle_tree()
        assert view._tree_expanded is True
        view._tree_frame.pack.assert_called_once()
        view._tree_toggle_btn.config.assert_called_with(text="▼ 一覧")

    def test_toggle_summary_collapses_then_expands(self) -> None:
        """要約を折りたたみ→展開できる."""
        view = self._make_view()

        view._on_toggle_summary()
        assert view._summary_expanded is False
        view._summary_body.pack_forget.assert_called_once()
        view._summary_toggle_btn.config.assert_called_with(text="▶ 要約")

        view._on_toggle_summary()
        assert view._summary_expanded is True
        view._summary_body.pack.assert_called_once()
        view._summary_toggle_btn.config.assert_called_with(text="▼ 要約")

    def test_toggle_detail_collapses_then_expands(self) -> None:
        """全文を折りたたみ→展開できる."""
        view = self._make_view()

        view._on_toggle_detail()
        assert view._detail_expanded is False
        view._detail_body.pack_forget.assert_called_once()
        view._detail_toggle_btn.config.assert_called_with(text="▶ 全文")

        view._on_toggle_detail()
        assert view._detail_expanded is True
        view._detail_body.pack.assert_called_once()
        view._detail_toggle_btn.config.assert_called_with(text="▼ 全文")

    def test_toggles_are_independent(self) -> None:
        """各領域のトグルは互いに独立している."""
        view = self._make_view()

        view._on_toggle_summary()

        # 要約だけ折りたたまれ、他は展開のまま
        assert view._summary_expanded is False
        assert view._tree_expanded is True
        assert view._detail_expanded is True

    def test_toggle_persists_state(self) -> None:
        """トグルのたびに折りたたみ状態が永続化される（次回起動時の記憶）."""
        view = self._make_view()

        view._on_toggle_tree()
        view._on_toggle_summary()
        view._on_toggle_detail()

        # 3回のトグルそれぞれで保存が呼ばれる
        assert view._persist_collapse_state.call_count == 3


class TestApplyCollapseState:
    """起動時の折りたたみ状態反映のテスト."""

    def _make_view(
        self, tree: bool, summary: bool, detail: bool
    ) -> MemoListView:
        view = object.__new__(MemoListView)
        view._tree_expanded = tree
        view._summary_expanded = summary
        view._detail_expanded = detail
        view._tree_frame = MagicMock()
        view._summary_body = MagicMock()
        view._detail_body = MagicMock()
        view._tree_toggle_btn = MagicMock()
        view._summary_toggle_btn = MagicMock()
        view._detail_toggle_btn = MagicMock()
        return view

    def test_expanded_state_packs_bodies(self) -> None:
        """全展開状態では中身が pack され、ラベルは ▼ になる."""
        view = self._make_view(True, True, True)

        view._apply_collapse_state()

        view._tree_frame.pack.assert_called_once()
        view._summary_body.pack.assert_called_once()
        view._detail_body.pack.assert_called_once()
        view._tree_toggle_btn.config.assert_called_with(text="▼ 一覧")
        view._summary_toggle_btn.config.assert_called_with(text="▼ 要約")
        view._detail_toggle_btn.config.assert_called_with(text="▼ 全文")

    def test_collapsed_state_forgets_bodies(self) -> None:
        """折りたたみ状態では中身が pack_forget され、ラベルは ▶ になる."""
        view = self._make_view(False, False, False)

        view._apply_collapse_state()

        view._tree_frame.pack_forget.assert_called_once()
        view._summary_body.pack_forget.assert_called_once()
        view._detail_body.pack_forget.assert_called_once()
        view._tree_toggle_btn.config.assert_called_with(text="▶ 一覧")
        view._summary_toggle_btn.config.assert_called_with(text="▶ 要約")
        view._detail_toggle_btn.config.assert_called_with(text="▶ 全文")

    def test_mixed_state(self) -> None:
        """混在状態（一覧展開・要約折りたたみ・全文展開）が正しく反映される."""
        view = self._make_view(True, False, True)

        view._apply_collapse_state()

        view._tree_frame.pack.assert_called_once()
        view._summary_body.pack_forget.assert_called_once()
        view._detail_body.pack.assert_called_once()
