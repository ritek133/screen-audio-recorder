"""MemoListView: メモを時間軸順に一覧表示する UI コンポーネント.

tkinter.ttk.Treeview でメモ一覧を表示し、
ページネーション・詳細表示・OutputFile 再生機能を提供する。

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_audio_recorder.memo_store import MemoStore
    from screen_audio_recorder.models import Memo

logger = logging.getLogger(__name__)

# 1 ページあたりの表示件数
_PAGE_SIZE = 50

# 本文プレビューの最大文字数
_PREVIEW_MAX_CHARS = 50


class MemoListView:
    """メモを時間軸順に一覧表示する UI コンポーネント.

    作成日時の降順でメモを表示し、ページネーション・詳細表示・
    OutputFile 再生機能を提供する。

    Attributes:
        _memo_store: メモストア
        _current_page: 現在のページ番号（1 始まり）
        _total_pages: 総ページ数
        frame: 外部から参照可能なルートフレーム
    """

    def __init__(self, parent: tk.Widget, memo_store: MemoStore, text_post_processor=None, transcriber=None, root=None) -> None:
        """MemoListView を初期化する.

        Args:
            parent: 親ウィジェット
            memo_store: メモストア
            text_post_processor: TextPostProcessor インスタンス（再処理用）
            transcriber: Transcriber インスタンス（再文字起こし用）
            root: tkinter ルートウィンドウ（スレッド通知用）
        """
        self._memo_store = memo_store
        self._text_post_processor = text_post_processor
        self._transcriber = transcriber
        self._root = root
        self._current_page = 1
        self._total_pages = 1
        self._memos: list[Memo] = []

        self.frame = ttk.LabelFrame(parent, text="メモ一覧", padding=6)
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # パブリック API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """メモ一覧を再読み込みして表示を更新する."""
        try:
            page = self._memo_store.get_all(
                page=self._current_page,
                page_size=_PAGE_SIZE,
            )
            self._memos = page.memos
            self._total_pages = page.total_pages
            self._populate_tree()
            self._update_pagination_buttons()
        except Exception:
            logger.exception("メモ一覧の読み込みに失敗しました。")

    @staticmethod
    def get_preview_text(body: str) -> str:
        """本文の先頭 50 文字を返す（50 文字未満は全文）.

        Args:
            body: メモの本文

        Returns:
            先頭 50 文字（50 文字未満の場合は全文）

        **Validates: Requirements 9.2 (Property 14)**
        """
        return body[:_PREVIEW_MAX_CHARS]

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """UI コンポーネントを構築・配置する.

        2ペイン横並びレイアウト（ADR-001 案3）:
        - 左ペイン: メモ一覧（Treeview） + ページネーション + 操作ボタン
        - 右ペイン: 要約 + 全文（縦積み）
        """
        # --- Treeview の行の高さを設定（日本語フォントが切れないように）---
        style = ttk.Style()
        style.configure("MemoList.Treeview", rowheight=28, font=("", 10))
        style.configure("MemoList.Treeview.Heading", font=("", 10, "bold"))

        # --- 2ペイン横並び（PanedWindow HORIZONTAL）---
        paned = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # ==============================================================
        # 左ペイン: メモ一覧 + ページネーション + 操作ボタン
        # ==============================================================
        left_frame = ttk.Frame(paned)

        # --- Treeview（メモ一覧）---
        tree_frame = ttk.Frame(left_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("created_at", "theme")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="MemoList.Treeview",
        )

        # カラムヘッダー設定（コンパクト: 日時+テーマのみ）
        self._tree.heading("created_at", text="作成日時")
        self._tree.heading("theme", text="テーマ")

        self._tree.column("created_at", width=150, minwidth=120)
        self._tree.column("theme", width=100, minwidth=70)

        # スクロールバー
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)

        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 選択イベント
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        # ダブルクリックでテーマ編集
        self._tree.bind("<Double-1>", self._on_double_click)

        # --- ページネーション ---
        page_frame = ttk.Frame(left_frame)
        page_frame.pack(fill=tk.X, pady=(4, 0))

        self._prev_btn = ttk.Button(
            page_frame,
            text="◀ 前",
            command=self._on_prev_page,
            state=tk.DISABLED,
        )
        self._prev_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._page_label = ttk.Label(page_frame, text="1 / 1")
        self._page_label.pack(side=tk.LEFT, padx=(0, 4))

        self._next_btn = ttk.Button(
            page_frame,
            text="次 ▶",
            command=self._on_next_page,
            state=tk.DISABLED,
        )
        self._next_btn.pack(side=tk.LEFT)

        # --- 操作ボタン ---
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, pady=(4, 0))

        self._play_btn = ttk.Button(
            btn_frame,
            text="▶ 再生",
            command=self._on_play,
            state=tk.DISABLED,
        )
        self._play_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._delete_btn = ttk.Button(
            btn_frame,
            text="削除",
            command=self._on_delete,
            state=tk.DISABLED,
        )
        self._delete_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._reprocess_btn = ttk.Button(
            btn_frame,
            text="🔄 再処理",
            command=self._on_reprocess,
            state=tk.DISABLED,
        )
        self._reprocess_btn.pack(side=tk.LEFT)

        self._retranscribe_btn = ttk.Button(
            btn_frame,
            text="🎙 再文字起こし",
            command=self._on_retranscribe,
            state=tk.DISABLED,
        )
        self._retranscribe_btn.pack(side=tk.LEFT, padx=(4, 0))

        paned.add(left_frame, weight=1)

        # ==============================================================
        # 右ペイン: 要約 + 全文（縦積み）
        # ==============================================================
        right_frame = ttk.Frame(paned)

        # 右ペイン内を縦に分割
        right_paned = ttk.PanedWindow(right_frame, orient=tk.VERTICAL)
        right_paned.pack(fill=tk.BOTH, expand=True)

        # --- 要約ペイン ---
        summary_frame = ttk.LabelFrame(right_paned, text="要約", padding=4)

        self._summary_text = tk.Text(
            summary_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            background="#f5f5f5",
        )
        summary_scroll = ttk.Scrollbar(
            summary_frame, orient=tk.VERTICAL, command=self._summary_text.yview
        )
        self._summary_text.configure(yscrollcommand=summary_scroll.set)
        self._summary_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        summary_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        right_paned.add(summary_frame, weight=1)

        # --- 全文ペイン ---
        detail_frame = ttk.LabelFrame(right_paned, text="全文", padding=4)

        self._detail_text = tk.Text(
            detail_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        detail_scroll = ttk.Scrollbar(
            detail_frame, orient=tk.VERTICAL, command=self._detail_text.yview
        )
        self._detail_text.configure(yscrollcommand=detail_scroll.set)
        self._detail_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        right_paned.add(detail_frame, weight=2)

        paned.add(right_frame, weight=2)

    # ------------------------------------------------------------------
    # データ表示
    # ------------------------------------------------------------------

    def _populate_tree(self) -> None:
        """Treeview にメモデータを設定する.

        要件 9.1: 作成日時の降順で表示（MemoStore.get_all() が降順で返す）
        要件 9.2: 作成日時・テーマを表示（全文は右ペインで表示）
        """
        # 既存の行をクリア
        for item in self._tree.get_children():
            self._tree.delete(item)

        for memo in self._memos:
            # UTC → JST（日本時間）に変換して表示
            jst = memo.created_at.astimezone(
                __import__("datetime").timezone(__import__("datetime").timedelta(hours=9))
            )
            created_at_str = jst.strftime("%Y-%m-%d %H:%M:%S")
            self._tree.insert(
                "",
                tk.END,
                iid=memo.id,
                values=(created_at_str, memo.theme),
            )

    def _update_pagination_buttons(self) -> None:
        """ページネーションボタンの状態を更新する.

        要件 9.5: 100 件超でページネーションを適用
        """
        self._page_label.config(
            text=f"{self._current_page} / {self._total_pages}"
        )
        self._prev_btn.config(
            state=tk.NORMAL if self._current_page > 1 else tk.DISABLED
        )
        self._next_btn.config(
            state=tk.NORMAL if self._current_page < self._total_pages else tk.DISABLED
        )

    # ------------------------------------------------------------------
    # イベントハンドラ
    # ------------------------------------------------------------------

    def _on_select(self, event: tk.Event) -> None:
        """メモ選択イベントハンドラ."""
        selected = self._tree.selection()
        if not selected:
            return

        memo_id = selected[0]
        memo = self._find_memo_by_id(memo_id)
        if memo is None:
            return

        # 要約を表示
        self._summary_text.config(state=tk.NORMAL)
        self._summary_text.delete("1.0", tk.END)
        self._summary_text.insert("1.0", memo.summary if memo.summary else "（要約なし）")
        self._summary_text.config(state=tk.DISABLED)

        # 全文を詳細ペインに表示
        self._detail_text.config(state=tk.NORMAL)
        self._detail_text.delete("1.0", tk.END)
        self._detail_text.insert("1.0", memo.body)
        self._detail_text.config(state=tk.DISABLED)

        # 再生・削除・再処理ボタンを有効化
        self._play_btn.config(state=tk.NORMAL)
        self._delete_btn.config(state=tk.NORMAL)
        self._reprocess_btn.config(
            state=tk.NORMAL if self._text_post_processor is not None else tk.DISABLED
        )
        # 再文字起こしボタン: Transcriber があり、output_file が存在する場合のみ有効
        retranscribe_enabled = (
            self._transcriber is not None
            and memo.output_file is not None
            and memo.output_file.exists()
        )
        self._retranscribe_btn.config(
            state=tk.NORMAL if retranscribe_enabled else tk.DISABLED
        )

    def _on_double_click(self, event: tk.Event) -> None:
        """ダブルクリックでテーマを編集する."""
        selected = self._tree.selection()
        if not selected:
            return

        memo_id = selected[0]
        memo = self._find_memo_by_id(memo_id)
        if memo is None:
            return

        # テーマ編集ダイアログ
        from tkinter import simpledialog
        new_theme = simpledialog.askstring(
            "テーマ編集",
            "新しいテーマを入力してください（10文字以内）:",
            initialvalue=memo.theme,
            parent=self._tree,
        )
        if new_theme is not None and new_theme.strip():
            new_theme = new_theme.strip()[:10]  # 10文字以内に制限
            # MemoStore のデータを更新
            try:
                self._memo_store.update_theme(memo_id, new_theme)
                self.refresh()
                logger.info("テーマを更新しました: %s → %s", memo.theme, new_theme)
            except Exception:
                logger.exception("テーマの更新に失敗しました。")

    def _on_play(self) -> None:
        """再生ボタンのイベントハンドラ.

        OS のデフォルトプレイヤーで OutputFile を再生する。

        要件 9.4: 対応する OutputFile の再生を開始できる
        """
        selected = self._tree.selection()
        if not selected:
            return

        memo_id = selected[0]
        memo = self._find_memo_by_id(memo_id)
        if memo is None:
            return

        output_file = memo.output_file
        if not output_file.exists():
            logger.warning("OutputFile が見つかりません: %s", output_file)
            return

        try:
            if sys.platform == "win32":
                subprocess.Popen(["start", "", str(output_file)], shell=True)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(output_file)])
            else:
                subprocess.Popen(["xdg-open", str(output_file)])
        except Exception:
            logger.exception("OutputFile の再生に失敗しました: %s", output_file)

    def _on_delete(self) -> None:
        """削除ボタンのイベントハンドラ。メモと対応する録画/録音ファイルも削除する。"""
        selected = self._tree.selection()
        if not selected:
            return

        memo_id = selected[0]
        memo = self._find_memo_by_id(memo_id)

        try:
            # 対応する録画/録音ファイルを削除
            if memo is not None and memo.output_file:
                try:
                    output_path = memo.output_file
                    if output_path.exists():
                        output_path.unlink()
                        logger.info("録画/録音ファイルを削除しました: %s", output_path)
                except Exception:
                    logger.exception("録画/録音ファイルの削除に失敗しました: %s", memo.output_file)

            # メモを削除
            self._memo_store.delete(memo_id)
            self.refresh()
            # 詳細ペインをクリア
            self._summary_text.config(state=tk.NORMAL)
            self._summary_text.delete("1.0", tk.END)
            self._summary_text.config(state=tk.DISABLED)
            self._detail_text.config(state=tk.NORMAL)
            self._detail_text.delete("1.0", tk.END)
            self._detail_text.config(state=tk.DISABLED)
            self._play_btn.config(state=tk.DISABLED)
            self._delete_btn.config(state=tk.DISABLED)
            self._reprocess_btn.config(state=tk.DISABLED)
        except Exception:
            logger.exception("メモの削除に失敗しました: %s", memo_id)

    def _on_prev_page(self) -> None:
        """前ページボタンのイベントハンドラ."""
        if self._current_page > 1:
            self._current_page -= 1
            self.refresh()

    def _on_next_page(self) -> None:
        """次ページボタンのイベントハンドラ."""
        if self._current_page < self._total_pages:
            self._current_page += 1
            self.refresh()

    def _on_reprocess(self) -> None:
        """再処理ボタンのイベントハンドラ。選択中のメモを LLM で再処理する."""
        selected = self._tree.selection()
        if not selected:
            return

        memo_id = selected[0]
        memo = self._find_memo_by_id(memo_id)
        if memo is None:
            return

        if self._text_post_processor is None:
            return

        if not memo.body:
            logger.warning("本文が空のため再処理できません。")
            return

        # ボタンを無効化して処理中表示
        self._reprocess_btn.config(state=tk.DISABLED, text="処理中...")

        def _worker():
            try:
                result = self._text_post_processor.process(memo.body)
                # メモを更新
                self._memo_store.update_memo(
                    memo_id=memo.id,
                    body=result.corrected_text,
                    theme=result.theme,
                    summary=result.summary,
                )
                if result.used_llm:
                    logger.info("メモ再処理完了（LLM 使用）: %s", memo.id)
                else:
                    logger.info("メモ再処理完了（フォールバック）: %s", memo.id)
            except Exception:
                logger.exception("メモの再処理に失敗しました: %s", memo.id)
            finally:
                # GUI スレッドで更新
                if self._root is not None:
                    self._root.after_idle(self._on_reprocess_done)
                else:
                    self._on_reprocess_done()

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _on_reprocess_done(self) -> None:
        """再処理完了時の GUI 更新."""
        self._reprocess_btn.config(text="🔄 再処理")
        self.refresh()

    def _on_retranscribe(self) -> None:
        """再文字起こしボタンのイベントハンドラ。選択中のメモの音声を再度文字起こしする."""
        selected = self._tree.selection()
        if not selected:
            return

        memo_id = selected[0]
        memo = self._find_memo_by_id(memo_id)
        if memo is None:
            return

        if self._transcriber is None:
            return

        if memo.output_file is None or not memo.output_file.exists():
            logger.warning("音声ファイルが見つかりません: %s", memo.output_file)
            return

        # ボタンを無効化して処理中表示
        self._retranscribe_btn.config(state=tk.DISABLED, text="文字起こし中...")

        def _worker():
            try:
                # 音声ファイルを再度文字起こし
                result = self._transcriber.transcribe(memo.output_file)

                if result.error:
                    logger.error("再文字起こしに失敗しました: %s", result.error)
                    return

                text = result.text

                # TextPostProcessor が利用可能な場合は LLM で後処理
                if self._text_post_processor is not None and text:
                    post_result = self._text_post_processor.process(text)
                    corrected_text = post_result.corrected_text
                    summary = post_result.summary
                    theme = post_result.theme
                else:
                    corrected_text = text
                    summary = ""
                    theme = memo.theme  # テーマは既存のものを保持

                # メモを更新
                self._memo_store.update_memo(
                    memo_id=memo.id,
                    body=corrected_text,
                    theme=theme,
                    summary=summary,
                )
                logger.info("再文字起こし完了: %s", memo.id)
            except Exception:
                logger.exception("再文字起こしに失敗しました: %s", memo.id)
            finally:
                # GUI スレッドで更新
                if self._root is not None:
                    self._root.after_idle(self._on_retranscribe_done)
                else:
                    self._on_retranscribe_done()

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _on_retranscribe_done(self) -> None:
        """再文字起こし完了時の GUI 更新."""
        self._retranscribe_btn.config(text="🎙 再文字起こし")
        self.refresh()

    # ------------------------------------------------------------------
    # ヘルパー
    # ------------------------------------------------------------------

    def _find_memo_by_id(self, memo_id: str) -> Memo | None:
        """現在のページからメモを ID で検索する."""
        for memo in self._memos:
            if memo.id == memo_id:
                return memo
        return None
