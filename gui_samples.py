"""GUI改善サンプル画面.

各案のモックアップを並べて表示する。
実行: python gui_samples.py
"""

import tkinter as tk
from tkinter import ttk
import ctypes

# DPI対応
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ダミーデータ
DUMMY_MEMOS = [
    ("2025-07-30 14:23:01", "会議メモ", "本日の会議で決まった内容は以下の通りです。まず、来月のリリー..."),
    ("2025-07-30 10:05:22", "作業記録", "午前中にバグ修正を完了。テスト結果は良好で、デプロイ準備..."),
    ("2025-07-29 16:45:10", "議事録", "プロジェクト進捗確認ミーティング。各チームからの報告事項..."),
    ("2025-07-29 09:30:00", "メモ", "朝のスタンドアップミーティングの内容。タスクの優先順位を..."),
    ("2025-07-28 15:12:33", "設計検討", "新機能のアーキテクチャ検討。マイクロサービス構成について..."),
]


def create_sample_current(parent):
    """現在のレイアウト（参考用）"""
    frame = ttk.Frame(parent, padding=8)
    frame.pack(fill=tk.BOTH, expand=True)

    # タイトル
    ttk.Label(frame, text="【現在】標準レイアウト", font=("", 11, "bold")).pack(anchor=tk.W)

    # コントロールパネル
    ctrl = ttk.LabelFrame(frame, text="録画コントロール", padding=6)
    ctrl.pack(fill=tk.X, pady=(4, 6))

    mode_f = ttk.Frame(ctrl)
    mode_f.pack(fill=tk.X, pady=(0, 4))
    ttk.Label(mode_f, text="録画モード:").pack(side=tk.LEFT, padx=(0, 6))
    ttk.Radiobutton(mode_f, text="画面 + 音声", value="screen").pack(side=tk.LEFT, padx=(0, 8))
    ttk.Radiobutton(mode_f, text="音声のみ", value="audio").pack(side=tk.LEFT)

    mic_f = ttk.Frame(ctrl)
    mic_f.pack(fill=tk.X, pady=(0, 4))
    ttk.Label(mic_f, text="マイク:").pack(side=tk.LEFT, padx=(0, 6))
    ttk.Combobox(mic_f, values=["マイク (Realtek Audio)"], state="readonly", width=40).pack(
        side=tk.LEFT, fill=tk.X, expand=True
    )

    btn_f = ttk.Frame(ctrl)
    btn_f.pack(fill=tk.X)
    ttk.Button(btn_f, text="録画開始").pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(btn_f, text="録画停止", state=tk.DISABLED).pack(side=tk.LEFT)

    # メモ一覧
    memo_lf = ttk.LabelFrame(frame, text="メモ一覧", padding=6)
    memo_lf.pack(fill=tk.BOTH, expand=True)

    tree = ttk.Treeview(memo_lf, columns=("date", "theme", "preview"), show="headings", height=5)
    tree.heading("date", text="作成日時")
    tree.heading("theme", text="テーマ")
    tree.heading("preview", text="内容（先頭50文字）")
    tree.column("date", width=160)
    tree.column("theme", width=120)
    tree.column("preview", width=400)
    for m in DUMMY_MEMOS:
        tree.insert("", tk.END, values=m)
    tree.pack(fill=tk.BOTH, expand=True)

    # 要約ペイン
    sum_lf = ttk.LabelFrame(memo_lf, text="要約", padding=4)
    sum_lf.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
    sum_txt = tk.Text(sum_lf, wrap=tk.WORD, height=3, bg="#f5f5f5")
    sum_txt.insert("1.0", "本日の会議の要約: リリース日程の確定と各担当者のタスク割り振りを実施。")
    sum_txt.config(state=tk.DISABLED)
    sum_txt.pack(fill=tk.BOTH, expand=True)

    # 全文ペイン
    det_lf = ttk.LabelFrame(memo_lf, text="全文", padding=4)
    det_lf.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
    det_txt = tk.Text(det_lf, wrap=tk.WORD, height=3)
    det_txt.insert("1.0", "本日の会議で決まった内容は以下の通りです。まず、来月のリリース日程は15日に確定しました。")
    det_txt.config(state=tk.DISABLED)
    det_txt.pack(fill=tk.BOTH, expand=True)

    return frame


def create_sample_compact(parent):
    """案1: コンパクトモード"""
    frame = ttk.Frame(parent, padding=4)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="【案1】コンパクトモード", font=("", 11, "bold")).pack(anchor=tk.W)

    # コントロール（1行に凝縮）
    ctrl = ttk.LabelFrame(frame, text="録画コントロール", padding=3)
    ctrl.pack(fill=tk.X, pady=(2, 4))

    row1 = ttk.Frame(ctrl)
    row1.pack(fill=tk.X)
    ttk.Label(row1, text="モード:", font=("", 9)).pack(side=tk.LEFT)
    ttk.Radiobutton(row1, text="画面+音声", value="screen").pack(side=tk.LEFT, padx=2)
    ttk.Radiobutton(row1, text="音声のみ", value="audio").pack(side=tk.LEFT, padx=2)
    ttk.Label(row1, text="  マイク:", font=("", 9)).pack(side=tk.LEFT)
    ttk.Combobox(row1, values=["マイク (Realtek)"], state="readonly", width=20).pack(
        side=tk.LEFT, padx=2
    )
    ttk.Button(row1, text="⏺ 開始").pack(side=tk.LEFT, padx=(8, 2))
    ttk.Button(row1, text="⏹ 停止", state=tk.DISABLED).pack(side=tk.LEFT)

    # メモ一覧（コンパクト）
    memo_lf = ttk.LabelFrame(frame, text="メモ一覧", padding=3)
    memo_lf.pack(fill=tk.BOTH, expand=True)

    style = ttk.Style()
    style.configure("Compact.Treeview", rowheight=22, font=("", 9))

    tree = ttk.Treeview(
        memo_lf, columns=("date", "theme", "preview"), show="headings",
        height=5, style="Compact.Treeview"
    )
    tree.heading("date", text="日時")
    tree.heading("theme", text="テーマ")
    tree.heading("preview", text="内容")
    tree.column("date", width=130, minwidth=100)
    tree.column("theme", width=80, minwidth=60)
    tree.column("preview", width=300, minwidth=150)
    for m in DUMMY_MEMOS:
        tree.insert("", tk.END, values=m)
    tree.pack(fill=tk.BOTH, expand=True)

    # 要約+全文を横並び
    detail_f = ttk.Frame(memo_lf)
    detail_f.pack(fill=tk.BOTH, expand=True, pady=(2, 0))

    sum_lf = ttk.LabelFrame(detail_f, text="要約", padding=2)
    sum_lf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))
    sum_txt = tk.Text(sum_lf, wrap=tk.WORD, height=3, bg="#f5f5f5", font=("", 9))
    sum_txt.insert("1.0", "会議の要約: リリース日程確定、タスク割り振り実施。")
    sum_txt.config(state=tk.DISABLED)
    sum_txt.pack(fill=tk.BOTH, expand=True)

    det_lf = ttk.LabelFrame(detail_f, text="全文", padding=2)
    det_lf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    det_txt = tk.Text(det_lf, wrap=tk.WORD, height=3, font=("", 9))
    det_txt.insert("1.0", "本日の会議で決まった内容は以下の通りです。来月のリリース日程は15日に確定しました。")
    det_txt.config(state=tk.DISABLED)
    det_txt.pack(fill=tk.BOTH, expand=True)

    return frame


def create_sample_twopane(parent):
    """案3: 2ペインレイアウト（左:一覧、右:詳細）"""
    frame = ttk.Frame(parent, padding=4)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="【案3】2ペイン横並びレイアウト", font=("", 11, "bold")).pack(anchor=tk.W)

    # コントロール（コンパクト1行）
    ctrl = ttk.LabelFrame(frame, text="録画コントロール", padding=3)
    ctrl.pack(fill=tk.X, pady=(2, 4))

    row1 = ttk.Frame(ctrl)
    row1.pack(fill=tk.X)
    ttk.Label(row1, text="モード:", font=("", 9)).pack(side=tk.LEFT)
    ttk.Radiobutton(row1, text="画面+音声", value="screen").pack(side=tk.LEFT, padx=2)
    ttk.Radiobutton(row1, text="音声のみ", value="audio").pack(side=tk.LEFT, padx=2)
    ttk.Label(row1, text="  マイク:", font=("", 9)).pack(side=tk.LEFT)
    ttk.Combobox(row1, values=["マイク (Realtek)"], state="readonly", width=20).pack(
        side=tk.LEFT, padx=2
    )
    ttk.Button(row1, text="⏺ 開始").pack(side=tk.LEFT, padx=(8, 2))
    ttk.Button(row1, text="⏹ 停止", state=tk.DISABLED).pack(side=tk.LEFT)

    # 2ペイン（PanedWindow 横方向）
    paned = ttk.PanedWindow(frame, orient=tk.HORIZONTAL)
    paned.pack(fill=tk.BOTH, expand=True)

    # 左ペイン：メモ一覧
    left_f = ttk.LabelFrame(paned, text="メモ一覧", padding=3)

    tree = ttk.Treeview(
        left_f, columns=("date", "theme"), show="headings",
        height=8, style="Compact.Treeview"
    )
    tree.heading("date", text="日時")
    tree.heading("theme", text="テーマ")
    tree.column("date", width=130)
    tree.column("theme", width=80)
    for m in DUMMY_MEMOS:
        tree.insert("", tk.END, values=(m[0], m[1]))
    tree.pack(fill=tk.BOTH, expand=True)

    paned.add(left_f, weight=1)

    # 右ペイン：詳細表示
    right_f = ttk.Frame(paned, padding=3)

    sum_lf = ttk.LabelFrame(right_f, text="要約", padding=3)
    sum_lf.pack(fill=tk.BOTH, expand=True, pady=(0, 2))
    sum_txt = tk.Text(sum_lf, wrap=tk.WORD, height=4, bg="#f5f5f5", font=("", 9))
    sum_txt.insert("1.0", "会議の要約: リリース日程確定、タスク割り振り実施。次回会議は来週月曜に設定。")
    sum_txt.config(state=tk.DISABLED)
    sum_txt.pack(fill=tk.BOTH, expand=True)

    det_lf = ttk.LabelFrame(right_f, text="全文", padding=3)
    det_lf.pack(fill=tk.BOTH, expand=True)
    det_txt = tk.Text(det_lf, wrap=tk.WORD, height=6, font=("", 9))
    det_txt.insert("1.0", "本日の会議で決まった内容は以下の通りです。\n\nまず、来月のリリース日程は15日に確定しました。\n各チームの担当者にタスクを割り振りました。\nテスト期間は10日から14日です。")
    det_txt.config(state=tk.DISABLED)
    det_txt.pack(fill=tk.BOTH, expand=True)

    paned.add(right_f, weight=2)

    return frame


def create_sample_large_font(parent):
    """案4: フォント大きめ（視認性重視）"""
    frame = ttk.Frame(parent, padding=6)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="【案4】大きめフォント（視認性重視）", font=("", 12, "bold")).pack(anchor=tk.W)

    # コントロール
    ctrl = ttk.LabelFrame(frame, text="録画コントロール", padding=6)
    ctrl.pack(fill=tk.X, pady=(4, 6))

    row1 = ttk.Frame(ctrl)
    row1.pack(fill=tk.X)
    ttk.Label(row1, text="モード:", font=("", 11)).pack(side=tk.LEFT)
    ttk.Radiobutton(row1, text="画面+音声", value="screen").pack(side=tk.LEFT, padx=4)
    ttk.Radiobutton(row1, text="音声のみ", value="audio").pack(side=tk.LEFT, padx=4)

    row2 = ttk.Frame(ctrl)
    row2.pack(fill=tk.X, pady=(4, 0))
    ttk.Label(row2, text="マイク:", font=("", 11)).pack(side=tk.LEFT)
    ttk.Combobox(row2, values=["マイク (Realtek Audio)"], state="readonly", width=30).pack(
        side=tk.LEFT, padx=4
    )
    ttk.Button(row2, text="⏺ 録画開始").pack(side=tk.LEFT, padx=(12, 4))
    ttk.Button(row2, text="⏹ 録画停止", state=tk.DISABLED).pack(side=tk.LEFT)

    # メモ一覧（大きめフォント）
    style = ttk.Style()
    style.configure("Large.Treeview", rowheight=32, font=("", 11))
    style.configure("Large.Treeview.Heading", font=("", 11, "bold"))

    memo_lf = ttk.LabelFrame(frame, text="メモ一覧", padding=4)
    memo_lf.pack(fill=tk.BOTH, expand=True)

    tree = ttk.Treeview(
        memo_lf, columns=("date", "theme", "preview"), show="headings",
        height=4, style="Large.Treeview"
    )
    tree.heading("date", text="日時")
    tree.heading("theme", text="テーマ")
    tree.heading("preview", text="内容")
    tree.column("date", width=160)
    tree.column("theme", width=100)
    tree.column("preview", width=350)
    for m in DUMMY_MEMOS:
        tree.insert("", tk.END, values=m)
    tree.pack(fill=tk.BOTH, expand=True)

    # 詳細
    det_lf = ttk.LabelFrame(memo_lf, text="要約 / 全文", padding=4)
    det_lf.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
    det_txt = tk.Text(det_lf, wrap=tk.WORD, height=4, font=("", 11))
    det_txt.insert("1.0", "【要約】会議の要約: リリース日程確定。\n\n【全文】本日の会議で決まった内容は以下の通りです。来月のリリース日程は15日に確定しました。")
    det_txt.config(state=tk.DISABLED)
    det_txt.pack(fill=tk.BOTH, expand=True)

    return frame


def main():
    """サンプルウィンドウを表示する."""
    root = tk.Tk()
    root.title("GUI改善サンプル比較")
    root.geometry("1200x800")
    root.minsize(900, 600)

    # 説明ラベル
    info = ttk.Label(
        root,
        text="各タブで異なるレイアウト案を確認できます。ウィンドウをリサイズして小さいモニターでの見え方も試してください。",
        font=("", 10),
        padding=8,
    )
    info.pack(fill=tk.X)

    # タブで各案を表示
    notebook = ttk.Notebook(root)
    notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    # 現在
    tab_current = ttk.Frame(notebook)
    notebook.add(tab_current, text="現在のレイアウト")
    create_sample_current(tab_current)

    # 案1
    tab_compact = ttk.Frame(notebook)
    notebook.add(tab_compact, text="案1: コンパクト")
    create_sample_compact(tab_compact)

    # 案3
    tab_twopane = ttk.Frame(notebook)
    notebook.add(tab_twopane, text="案3: 2ペイン横並び")
    create_sample_twopane(tab_twopane)

    # 案4
    tab_large = ttk.Frame(notebook)
    notebook.add(tab_large, text="案4: 大きめフォント")
    create_sample_large_font(tab_large)

    root.mainloop()


if __name__ == "__main__":
    main()
