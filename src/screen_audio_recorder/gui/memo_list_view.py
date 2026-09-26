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

# 全文ペイン表示用の1論理行あたりの最大文字数。
# tkinter.Text は1論理行（改行区切り）が長すぎると表示が途中で打ち切られる
# 既知の制限がある。文字起こし本文は改行がほとんど無く巨大な1行になりやすいため、
# 表示時にこの文字数を上限として改行を挿入し、全文が表示されるようにする。
# （保存データ body 自体は変更しない）
_DISPLAY_LINE_MAX_CHARS = 1000

# 表示用改行を挿入する文の区切り文字（この直後で改行する）
_DISPLAY_SENTENCE_BOUNDARIES = ("。", "！", "？")


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

    def __init__(self, parent: tk.Widget, memo_store: MemoStore, text_post_processor=None, transcriber=None, root=None, raw_transcript_store=None, on_processing_done=None) -> None:
        """MemoListView を初期化する.

        Args:
            parent: 親ウィジェット
            memo_store: メモストア
            text_post_processor: TextPostProcessor インスタンス（再処理用）
            transcriber: Transcriber インスタンス（再文字起こし用）
            root: tkinter ルートウィンドウ（スレッド通知用）
            raw_transcript_store: RawTranscriptStore インスタンス（再文字起こし時の
                生データ保存用）。None の場合は再文字起こし時に生データを保存しない。
            on_processing_done: 再処理・再文字起こしの完了時に呼ばれるコールバック
                （引数なし）。残存容量の再取得など、LLM / Transcribe 使用後の
                後処理に使う。None の場合は何もしない。
        """
        self._memo_store = memo_store
        self._text_post_processor = text_post_processor
        self._transcriber = transcriber
        self._root = root
        self._raw_transcript_store = raw_transcript_store
        self._on_processing_done = on_processing_done
        self._current_page = 1
        self._total_pages = 1
        self._memos: list[Memo] = []

        # 各領域の折りたたみ状態（True=展開, False=折りたたみ）。
        # 前回終了時の状態を app_settings.json から復元する。
        # 読み込みに失敗しても起動を妨げないよう、失敗時は全展開にフォールバックする。
        try:
            from screen_audio_recorder.app_settings_store import load_app_settings

            settings = load_app_settings()
            self._tree_expanded = settings.memo_tree_expanded
            self._summary_expanded = settings.memo_summary_expanded
            self._detail_expanded = settings.memo_detail_expanded
        except Exception:
            logger.debug("メモ領域の折りたたみ状態の読み込みに失敗しました。全展開で表示します。")
            self._tree_expanded = True
            self._summary_expanded = True
            self._detail_expanded = True

        self.frame = ttk.LabelFrame(parent, text="メモ一覧", padding=6)
        self._build_ui()
        self._apply_collapse_state()
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

        # --- メモ一覧（折りたたみ可能）---
        # 折りたたみ用トグルボタン付きヘッダ
        tree_header = ttk.Frame(left_frame)
        tree_header.pack(fill=tk.X)
        self._tree_toggle_btn = ttk.Button(
            tree_header,
            text="▼ 一覧",
            width=8,
            command=self._on_toggle_tree,
        )
        self._tree_toggle_btn.pack(side=tk.LEFT)

        # 折りたたみ対象の中身コンテナ
        tree_frame = ttk.Frame(left_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self._tree_frame = tree_frame

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

        # --- 要約ペイン（折りたたみ可能）---
        summary_frame = ttk.Frame(right_paned)
        self._summary_frame = summary_frame

        # 折りたたみ用トグルボタン付きヘッダ
        summary_header = ttk.Frame(summary_frame)
        summary_header.pack(fill=tk.X)
        self._summary_toggle_btn = ttk.Button(
            summary_header,
            text="▼ 要約",
            width=8,
            command=self._on_toggle_summary,
        )
        self._summary_toggle_btn.pack(side=tk.LEFT)

        # 折りたたみ対象の中身コンテナ
        summary_body = ttk.Frame(summary_frame)
        summary_body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self._summary_body = summary_body

        self._summary_text = tk.Text(
            summary_body,
            wrap=tk.WORD,
            state=tk.DISABLED,
            background="#f5f5f5",
        )
        summary_scroll = ttk.Scrollbar(
            summary_body, orient=tk.VERTICAL, command=self._summary_text.yview
        )
        self._summary_text.configure(yscrollcommand=summary_scroll.set)
        self._summary_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        summary_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        right_paned.add(summary_frame, weight=1)

        # --- 全文ペイン（折りたたみ可能）---
        detail_frame = ttk.Frame(right_paned)
        self._detail_frame = detail_frame

        # 折りたたみ用トグルボタン付きヘッダ
        detail_header = ttk.Frame(detail_frame)
        detail_header.pack(fill=tk.X)
        self._detail_toggle_btn = ttk.Button(
            detail_header,
            text="▼ 全文",
            width=8,
            command=self._on_toggle_detail,
        )
        self._detail_toggle_btn.pack(side=tk.LEFT)

        # 折りたたみ対象の中身コンテナ
        detail_body = ttk.Frame(detail_frame)
        detail_body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self._detail_body = detail_body

        self._detail_text = tk.Text(
            detail_body,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        detail_scroll = ttk.Scrollbar(
            detail_body, orient=tk.VERTICAL, command=self._detail_text.yview
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

    def _apply_tree_visibility(self) -> None:
        """メモ一覧領域の表示状態を現在のフラグに合わせて反映する."""
        if self._tree_expanded:
            self._tree_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
            self._tree_toggle_btn.config(text="▼ 一覧")
        else:
            self._tree_frame.pack_forget()
            self._tree_toggle_btn.config(text="▶ 一覧")

    def _apply_summary_visibility(self) -> None:
        """要約領域の表示状態を現在のフラグに合わせて反映する."""
        if self._summary_expanded:
            self._summary_body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
            self._summary_toggle_btn.config(text="▼ 要約")
        else:
            self._summary_body.pack_forget()
            self._summary_toggle_btn.config(text="▶ 要約")

    def _apply_detail_visibility(self) -> None:
        """全文領域の表示状態を現在のフラグに合わせて反映する."""
        if self._detail_expanded:
            self._detail_body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
            self._detail_toggle_btn.config(text="▼ 全文")
        else:
            self._detail_body.pack_forget()
            self._detail_toggle_btn.config(text="▶ 全文")

    def _apply_collapse_state(self) -> None:
        """起動時に3領域の折りたたみ状態を初期表示へ反映する."""
        self._apply_tree_visibility()
        self._apply_summary_visibility()
        self._apply_detail_visibility()

    def _persist_collapse_state(self) -> None:
        """現在の折りたたみ状態を app_settings.json に保存する.

        他の設定を上書きしないよう、最新設定を読み込んでから該当フィールド
        のみ更新して保存する。保存失敗は GUI 操作を妨げないよう握りつぶす。
        """
        try:
            from screen_audio_recorder.app_settings_store import (
                load_app_settings,
                save_app_settings,
            )

            settings = load_app_settings()
            settings.memo_tree_expanded = self._tree_expanded
            settings.memo_summary_expanded = self._summary_expanded
            settings.memo_detail_expanded = self._detail_expanded
            save_app_settings(settings)
        except Exception:
            logger.debug("メモ領域の折りたたみ状態の保存に失敗しました。")

    def _on_toggle_tree(self) -> None:
        """メモ一覧領域の折りたたみ／展開を切り替える."""
        self._tree_expanded = not self._tree_expanded
        self._apply_tree_visibility()
        self._persist_collapse_state()

    def _on_toggle_summary(self) -> None:
        """要約領域の折りたたみ／展開を切り替える."""
        self._summary_expanded = not self._summary_expanded
        self._apply_summary_visibility()
        self._persist_collapse_state()

    def _on_toggle_detail(self) -> None:
        """全文領域の折りたたみ／展開を切り替える."""
        self._detail_expanded = not self._detail_expanded
        self._apply_detail_visibility()
        self._persist_collapse_state()

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
        # tkinter.Text の1論理行が長すぎると表示が途中で切れるため、
        # 表示用に改行を挿入する（保存データ body 自体は変更しない）。
        self._detail_text.config(state=tk.NORMAL)
        self._detail_text.delete("1.0", tk.END)
        self._detail_text.insert("1.0", format_body_for_display(memo.body))
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
        # LLM 使用後なので残存容量を再取得する（設定されていれば）。
        self._notify_processing_done()

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

                # 文字起こし生データ（LLM 後処理前）を上書き保存する。
                # 初回録画時と同じファイル名（録画ファイル名ベース）で上書きし、
                # メモと生データの 1 対 1 対応を保つ。
                raw_transcript_file = None
                if self._raw_transcript_store is not None:
                    try:
                        raw_transcript_file = self._raw_transcript_store.save(
                            text, memo.output_file, overwrite=True
                        )
                    except Exception:
                        # 生データ保存の失敗はメモ更新を妨げない
                        logger.exception("文字起こし生データの保存に失敗しました: %s", memo.id)

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
                    raw_transcript_file=raw_transcript_file,
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
        # Transcribe / LLM 使用後なので残存容量を再取得する（設定されていれば）。
        self._notify_processing_done()

    def _notify_processing_done(self) -> None:
        """再処理・再文字起こし完了を外部へ通知する（残存容量の再取得用）.

        コールバック未設定時や例外時でも GUI 更新を妨げないよう、失敗は握りつぶす。
        """
        if self._on_processing_done is None:
            return
        try:
            self._on_processing_done()
        except Exception:
            logger.debug("再処理完了通知（残量更新）の呼び出しに失敗しました。")

    # ------------------------------------------------------------------
    # ヘルパー
    # ------------------------------------------------------------------

    def _find_memo_by_id(self, memo_id: str) -> Memo | None:
        """現在のページからメモを ID で検索する."""
        for memo in self._memos:
            if memo.id == memo_id:
                return memo
        return None


# ---------------------------------------------------------------------------
# 表示用ユーティリティ
# ---------------------------------------------------------------------------


def format_body_for_display(
    body: str,
    line_max_chars: int = _DISPLAY_LINE_MAX_CHARS,
) -> str:
    """全文ペイン表示用に、長い本文へ改行を挿入する.

    tkinter.Text は1論理行（改行区切り）が長すぎると表示が途中で打ち切られる
    既知の制限がある。文字起こし本文は句読点や改行が少なく巨大な1行になりやすい
    ため、表示前に以下のルールで改行を挿入して1論理行を短く保つ。

    1. 句点・感嘆符・疑問符（。！？）の直後で改行する（読みやすさ重視）。
    2. それでも1行が ``line_max_chars`` を超える場合は、その位置で強制改行する。

    保存データ（body 本体）は変更せず、あくまで表示用の整形のみを行う。
    元の改行はそのまま尊重する。

    Args:
        body: メモ本文（保存されている生の文字列）。
        line_max_chars: 1論理行あたりの最大文字数（正の値）。

    Returns:
        表示用に改行を挿入した文字列。
    """
    if not body:
        return body
    if line_max_chars <= 0:
        return body

    result_chars: list[str] = []
    current_line_len = 0

    for char in body:
        result_chars.append(char)

        if char == "\n":
            # 既存の改行でカウンタをリセット
            current_line_len = 0
            continue

        current_line_len += 1

        if char in _DISPLAY_SENTENCE_BOUNDARIES:
            # 文の区切りの直後で改行（読みやすさ重視）
            result_chars.append("\n")
            current_line_len = 0
        elif current_line_len >= line_max_chars:
            # 句点が現れないまま上限に達したら強制改行
            result_chars.append("\n")
            current_line_len = 0

    return "".join(result_chars)
