"""HtmlExporter: メモを自己完結 HTML として出力するモジュール.

ADR-003 で採用した案B（一覧/詳細 2ペイン・全文折り畳み）を出力テンプレートとし、
メモデータを HTML 内に埋め込んだ単一ファイルを生成する。生成物はダブルクリックで
開けるため、ローカルサーバーやインターネット公開を必要としない。

ADR-004 参照。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from screen_audio_recorder.models import ExportSettings, Memo

logger = logging.getLogger(__name__)


class HtmlExporter:
    """メモ一覧を自己完結 HTML ファイルに出力するクラス."""

    def export(
        self,
        memos: list[Memo],
        output_path: Path,
        settings: ExportSettings | None = None,
    ) -> None:
        """メモを HTML ファイルへ出力する（原子的書き込み）.

        本文・要約がいずれも空のメモは除外する（ADR-003 と一貫）。
        既定では ``output_file``（ローカルパス）を HTML に含めない。

        Args:
            memos: 出力対象のメモリスト
            output_path: 出力先 HTML ファイルパス
            settings: エクスポート設定（None の場合は既定 ExportSettings を使用）
        """
        if settings is None:
            settings = ExportSettings()

        payload = self._build_payload(memos, settings)
        html = self._render_html(payload)
        self._atomic_write(output_path, html)
        logger.info(
            "HTML を出力しました: %s（%d 件）", output_path, len(payload["memos"])
        )

    # ------------------------------------------------------------------
    # 内部実装
    # ------------------------------------------------------------------

    def _build_payload(
        self, memos: list[Memo], settings: ExportSettings
    ) -> dict:
        """HTML に埋め込む JSON ペイロードを構築する."""
        items = []
        for m in memos:
            body = m.body or ""
            summary = m.summary or ""
            # 本文・要約がいずれも空のメモは除外
            if not body.strip() and not summary.strip():
                continue

            item = {
                "id": m.id,
                "created_at": self._format_dt(m.created_at),
                "theme": m.theme or "",
                "summary": summary,
                "body": body,
            }
            # 既定では output_file（ローカルパス）を含めない（プライバシー保護）
            if settings.include_output_file_path and m.output_file is not None:
                item["output_file"] = str(m.output_file)
            items.append(item)

        return {
            "generated_at": self._format_dt(datetime.now(tz=timezone.utc)),
            "count": len(items),
            "memos": items,
        }

    @staticmethod
    def _format_dt(dt: datetime) -> str:
        """datetime を ISO 8601（末尾 Z）の UTC 文字列にする."""
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _embed_json(payload: dict) -> str:
        """JSON を <script> に安全に埋め込める文字列へ変換する.

        ``</script>`` や HTML コメント開始などでスクリプトタグを閉じられない
        ように、危険なシーケンスをエスケープする。
        """
        text = json.dumps(payload, ensure_ascii=False)
        # </ を \\u003c/ に、<!-- を無害化してタグ破壊を防ぐ
        text = text.replace("<", "\\u003c").replace(">", "\\u003e")
        text = text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        return text

    def _render_html(self, payload: dict) -> str:
        """自己完結 HTML 文字列を生成する（案B: 2ペイン・全文折り畳み）."""
        data_json = self._embed_json(payload)
        generated = payload.get("generated_at", "")
        return _HTML_TEMPLATE.replace("__DATA_JSON__", data_json).replace(
            "__GENERATED_AT__", generated
        )

    @staticmethod
    def _atomic_write(output_path: Path, content: str) -> None:
        """一時ファイルへ書いてから置換する（原子的書き込み）.

        閲覧中のファイルが書き込み途中で壊れることを防ぐ。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(output_path.parent), suffix=".tmp", prefix=".memo-export-"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_name, str(output_path))
        except Exception:
            # 失敗時は一時ファイルを掃除する
            try:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# HTML テンプレート（案B: 一覧/詳細 2ペイン・全文折り畳み）
# データは __DATA_JSON__ に埋め込む。
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>録音メモ</title>
<style>
  :root { --sidebar:#f4f5f7; --ink:#1f2933; --muted:#6b7280; --accent:#0f766e; --border:#e5e7eb; }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body { font-family: system-ui, "Segoe UI", "Hiragino Kaku Gothic ProN", Meiryo, sans-serif;
         color: var(--ink); line-height: 1.75; display: flex; flex-direction: column; }
  .topbar { height: 56px; display: flex; align-items: center; gap: 14px; padding: 0 18px;
            background: var(--accent); color: #fff; font-weight: 600; flex: none; }
  .topbar .grow { flex: 1; }
  .topbar .gen { font-weight: normal; font-size: .75rem; opacity: .85; }
  .topbar input[type=search] { width: 240px; max-width: 40vw; padding: 8px 12px; border: none;
                               border-radius: 8px; font-size: .9rem; }
  .layout { flex: 1; display: flex; min-height: 0; }
  aside { width: 360px; flex: none; background: var(--sidebar); border-right: 1px solid var(--border);
          overflow-y: auto; padding: 10px; }
  .listcount { color: var(--muted); font-size: .78rem; padding: 6px 10px 10px; }
  .item { padding: 12px 14px; border-radius: 10px; cursor: pointer; margin-bottom: 6px; }
  .item:hover { background: #e9ebef; }
  .item.active { background: #d7f0ec; }
  .item h3 { margin: 0 0 6px; font-size: .95rem;
             display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .item p { margin: 0; font-size: .8rem; color: var(--muted);
            display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .item .date { font-size: .7rem; color: var(--accent); }
  .more { width: 100%; padding: 10px; border: 1px dashed var(--border); background: #fff;
          border-radius: 8px; cursor: pointer; color: var(--accent); font-size: .85rem; }
  main { flex: 1; overflow-y: auto; padding: 36px 48px; }
  main h1 { margin-top: 0; }
  main .date { color: var(--muted); font-size: .85rem; margin-bottom: 4px; }
  main .len { color: var(--muted); font-size: .78rem; margin-bottom: 20px; }
  main .section-label { font-size: .78rem; color: var(--accent); text-transform: uppercase;
                        letter-spacing: .05em; margin: 24px 0 4px; }
  main .summary-box { background: #f0fdfa; border-left: 3px solid var(--accent); padding: 12px 16px;
                      border-radius: 4px; white-space: pre-wrap; }
  main details.fulltext { margin-top: 8px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  main details.fulltext > summary { cursor: pointer; list-style: none; padding: 12px 16px; background: #f9fafb;
    font-size: .82rem; color: var(--accent); text-transform: uppercase; letter-spacing: .05em;
    display: flex; align-items: center; gap: 8px; user-select: none; }
  main details.fulltext > summary::-webkit-details-marker { display: none; }
  main details.fulltext > summary::before { content: "\\25B6"; font-size: .7rem; transition: transform .15s ease; }
  main details.fulltext[open] > summary::before { transform: rotate(90deg); }
  main details.fulltext > summary .hint { margin-left: auto; color: var(--muted); text-transform: none; letter-spacing: 0; }
  main details.fulltext .body { padding: 16px; white-space: pre-wrap; }
  .placeholder, .state { color: var(--muted); padding: 12px; }
  @media (max-width: 720px) {
    .layout { flex-direction: column; }
    aside { width: 100%; height: 42%; border-right: none; border-bottom: 1px solid var(--border); }
    main { padding: 24px; }
    .topbar input[type=search] { width: 140px; }
  }
</style>
</head>
<body>
<div class="topbar">
  <span>録音メモ</span>
  <span class="gen">生成: __GENERATED_AT__</span>
  <span class="grow"></span>
  <input type="search" id="search" placeholder="検索..." />
</div>
<div class="layout">
  <aside id="aside">
    <div class="listcount" id="listcount"></div>
    <div id="list"></div>
  </aside>
  <main id="content">
    <p class="placeholder">左の一覧から選ぶと、ここに要約と全文が表示されます。</p>
  </main>
</div>

<script id="memo-data" type="application/json">__DATA_JSON__</script>
<script>
  // 埋め込みデータ（memos.json 由来）を読み込む。ネットワーク・サーバー不要。
  const DATA = JSON.parse(document.getElementById("memo-data").textContent);
  const CHUNK = 50;

  const listEl = document.getElementById("list");
  const listcount = document.getElementById("listcount");
  const content = document.getElementById("content");
  const search = document.getElementById("search");

  let all = [];
  let filtered = [];
  let shownCount = 0;
  let activeId = null;

  const fmtDate = iso => { if (!iso) return ""; const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString("ja-JP"); };
  const esc = s => (s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const title = m => (m.theme && m.theme.trim()) ? m.theme : "無題";

  function applyFilter() {
    const q = search.value.trim().toLowerCase();
    filtered = q
      ? all.filter(m => (title(m) + " " + (m.summary || "")).toLowerCase().includes(q))
      : all;
    shownCount = 0;
    listEl.innerHTML = "";
    listcount.textContent = `全 ${all.length} 件中 ${filtered.length} 件`;
    if (filtered.length === 0) {
      listEl.innerHTML = '<div class="state">該当するメモがありません。</div>';
      return;
    }
    appendChunk();
  }

  function appendChunk() {
    const end = Math.min(shownCount + CHUNK, filtered.length);
    const frag = document.createDocumentFragment();
    for (let i = shownCount; i < end; i++) {
      const m = filtered[i];
      const summary = (m.summary && m.summary.trim()) ? m.summary : "(要約なし)";
      const el = document.createElement("div");
      el.className = "item" + (m.id === activeId ? " active" : "");
      el.innerHTML = `<span class="date">${esc(fmtDate(m.created_at))}</span>
                      <h3>${esc(title(m))}</h3><p>${esc(summary)}</p>`;
      el.addEventListener("click", () => select(m, el));
      frag.appendChild(el);
    }
    const oldMore = listEl.querySelector(".more");
    if (oldMore) oldMore.remove();
    listEl.appendChild(frag);
    shownCount = end;
    if (shownCount < filtered.length) {
      const more = document.createElement("button");
      more.className = "more";
      more.textContent = `もっと見る（残り ${filtered.length - shownCount} 件）`;
      more.onclick = appendChunk;
      listEl.appendChild(more);
    }
  }

  function select(m, el) {
    activeId = m.id;
    listEl.querySelectorAll(".item").forEach(x => x.classList.remove("active"));
    if (el) el.classList.add("active");
    const summary = (m.summary && m.summary.trim()) ? m.summary : "(要約なし)";
    const body = (m.body && m.body.trim()) ? m.body : "(全文なし)";
    content.innerHTML = `
      <h1>${esc(title(m))}</h1>
      <div class="date">${esc(fmtDate(m.created_at))}</div>
      <div class="len">要約 ${summary.length.toLocaleString()} 字 / 全文 ${body.length.toLocaleString()} 字</div>
      <div class="section-label">要約</div>
      <div class="summary-box">${esc(summary)}</div>
      <details class="fulltext">
        <summary>全文<span class="hint">${body.length.toLocaleString()} 字 · クリックで表示</span></summary>
        <div class="body">${esc(body)}</div>
      </details>`;
    content.scrollTop = 0;
  }

  let searchTimer;
  search.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(applyFilter, 200); });

  all = Array.isArray(DATA.memos) ? DATA.memos : [];
  applyFilter();
</script>
</body>
</html>
"""
