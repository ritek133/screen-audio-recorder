"""HtmlExporter のユニットテスト."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from screen_audio_recorder.export.html_exporter import HtmlExporter
from screen_audio_recorder.models import ExportSettings, Memo


def _memo(
    memo_id: str,
    theme: str = "テーマ",
    body: str = "本文テキスト",
    summary: str = "要約テキスト",
    output_file: str = "C:/Users/tester/rec.wav",
) -> Memo:
    return Memo(
        id=memo_id,
        created_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
        theme=theme,
        body=body,
        summary=summary,
        output_file=Path(output_file),
    )


def _extract_payload(html: str) -> dict:
    """埋め込み JSON を取り出してパースする."""
    m = re.search(
        r'<script id="memo-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert m is not None
    text = m.group(1)
    # _embed_json の < > エスケープを戻す
    text = text.replace("\\u003c", "<").replace("\\u003e", ">")
    return json.loads(text)


def test_export_creates_file(tmp_path: Path) -> None:
    out = tmp_path / "out.html"
    HtmlExporter().export([_memo("a1")], out)
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_empty_memos_are_excluded(tmp_path: Path) -> None:
    out = tmp_path / "out.html"
    memos = [
        _memo("a1", body="本文あり", summary="要約あり"),
        _memo("a2", body="", summary=""),  # 除外対象
        _memo("a3", body="本文のみ", summary=""),
    ]
    HtmlExporter().export(memos, out)
    payload = _extract_payload(out.read_text(encoding="utf-8"))
    ids = [m["id"] for m in payload["memos"]]
    assert ids == ["a1", "a3"]
    assert payload["count"] == 2


def test_output_file_excluded_by_default(tmp_path: Path) -> None:
    out = tmp_path / "out.html"
    HtmlExporter().export([_memo("a1", output_file="C:/Users/secret/x.wav")], out)
    html = out.read_text(encoding="utf-8")
    assert "secret" not in html
    payload = _extract_payload(html)
    assert "output_file" not in payload["memos"][0]


def test_output_file_included_when_enabled(tmp_path: Path) -> None:
    out = tmp_path / "out.html"
    settings = ExportSettings(include_output_file_path=True)
    HtmlExporter().export([_memo("a1", output_file="C:/rec/x.wav")], out, settings)
    payload = _extract_payload(out.read_text(encoding="utf-8"))
    assert payload["memos"][0]["output_file"] == "C:\\rec\\x.wav" or payload[
        "memos"
    ][0]["output_file"] == "C:/rec/x.wav"


def test_script_tag_breakout_is_escaped(tmp_path: Path) -> None:
    """本文に </script> が含まれても HTML が壊れない."""
    out = tmp_path / "out.html"
    HtmlExporter().export(
        [_memo("a1", body="悪意 </script><script>alert(1)</script>")], out
    )
    html = out.read_text(encoding="utf-8")
    # 生の </script> がデータ script 内に出てこない（エスケープされている）
    payload = _extract_payload(html)
    assert "</script>" in payload["memos"][0]["body"]  # 復元後は元通り
    # データ script ブロックが 1 つだけ（breakout していない）
    assert html.count('id="memo-data"') == 1


def test_atomic_write_no_leftover_tmp(tmp_path: Path) -> None:
    out = tmp_path / "out.html"
    HtmlExporter().export([_memo("a1")], out)
    leftovers = list(tmp_path.glob(".memo-export-*"))
    assert leftovers == []


def test_export_overwrites_existing(tmp_path: Path) -> None:
    out = tmp_path / "out.html"
    HtmlExporter().export([_memo("a1", theme="古い")], out)
    HtmlExporter().export([_memo("a1", theme="新しい")], out)
    payload = _extract_payload(out.read_text(encoding="utf-8"))
    assert payload["memos"][0]["theme"] == "新しい"
