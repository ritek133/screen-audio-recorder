"""TextPostProcessor のユニットテスト.

主に長文の後処理で全文が失われないことを検証する:
- _split_into_chunks が連結で元テキストを復元できること
- _fix_text がチャンク分割しても全文（長さ）を保持すること
- 一部チャンクの LLM 整形が失敗しても、そのチャンクの元テキストが残ること
- _summarize が長文入力を安全な文字数に制限すること

**Validates: 文字起こし後半欠落バグの修正（チャンク分割による全文保持）**
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from screen_audio_recorder.models import LlmSettings
from screen_audio_recorder.text_post_processor import (
    _MAX_CHUNK_CHAR_SIZE,
    _MIN_CHUNK_CHAR_SIZE,
    _SUMMARY_MAX_INPUT_CHARS,
    TextPostProcessor,
    _split_into_chunks,
)


# ---------------------------------------------------------------------------
# テスト用フィクスチャ / ヘルパー
# ---------------------------------------------------------------------------


def _make_processor(
    llm_client: MagicMock, max_tokens: int | None = None
) -> TextPostProcessor:
    """モックした LlmClient から TextPostProcessor を生成する."""
    theme_fallback = MagicMock()
    theme_fallback.generate.return_value = "フォールバック"
    if max_tokens is None:
        settings = LlmSettings()
    else:
        settings = LlmSettings(max_tokens=max_tokens)
    return TextPostProcessor(
        llm_client=llm_client,
        theme_generator_fallback=theme_fallback,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# _split_into_chunks のテスト
# ---------------------------------------------------------------------------


class TestSplitIntoChunks:
    """_split_into_chunks の分割挙動を検証する."""

    def test_empty_returns_empty_list(self) -> None:
        assert _split_into_chunks("", 100) == []

    def test_short_text_single_chunk(self) -> None:
        text = "これは短い文章です。"
        assert _split_into_chunks(text, 100) == [text]

    def test_chunks_concatenate_to_original(self) -> None:
        """分割したチャンクを連結すると元テキストに一致する（文字欠落なし）."""
        text = "".join(f"文{i}です。" for i in range(200))
        chunks = _split_into_chunks(text, 100)
        assert len(chunks) > 1
        assert "".join(chunks) == text

    def test_each_chunk_prefers_sentence_boundary(self) -> None:
        """各チャンクは（最後を除き）文境界で終わる傾向にある."""
        text = "".join(f"あいうえお。" for _ in range(50))
        chunks = _split_into_chunks(text, 30)
        # 最後のチャンク以外は句点で終わっているはず
        for chunk in chunks[:-1]:
            assert chunk.endswith("。")

    def test_single_long_sentence_not_split_internally(self) -> None:
        """境界のない 1 文が chunk_size を超えても内部では分割しない."""
        text = "あ" * 500  # 句点なし
        chunks = _split_into_chunks(text, 100)
        assert chunks == [text]

    def test_non_positive_chunk_size_returns_whole(self) -> None:
        text = "テスト。テスト。"
        assert _split_into_chunks(text, 0) == [text]


# ---------------------------------------------------------------------------
# _fix_text のテスト
# ---------------------------------------------------------------------------


class TestFixTextFullTranscript:
    """長文整形で全文が保持されることを検証する."""

    def test_llm_unavailable_returns_original(self) -> None:
        llm = MagicMock()
        llm.available = False
        processor = _make_processor(llm)
        text = "整形されない文章です。"
        assert processor._fix_text(text) == text

    def test_short_text_single_call(self) -> None:
        """短文は 1 回の LLM 呼び出しで処理される."""
        llm = MagicMock()
        llm.available = True
        llm.generate.return_value = "整形済みテキスト。"
        processor = _make_processor(llm)

        result = processor._fix_text("元テキスト。")

        assert result == "整形済みテキスト。"
        assert llm.generate.call_count == 1

    def test_long_text_is_chunked(self) -> None:
        """長文は複数チャンクに分割され、複数回 LLM が呼ばれる."""
        llm = MagicMock()
        llm.available = True
        # LLM は入力をそのまま返す（＝整形しても長さが変わらない想定）
        llm.generate.side_effect = lambda prompt: prompt.split("\n\n")[-1]
        processor = _make_processor(llm)

        text = "".join(f"文{i}です。" for i in range(500))
        result = processor._fix_text(text)

        assert llm.generate.call_count > 1
        # 全文が保持される（連結して元テキストと一致）
        assert result == text

    def test_failed_chunk_keeps_original_segment(self) -> None:
        """一部チャンクの整形が失敗しても、そのチャンクの元テキストが残り全文が失われない."""
        llm = MagicMock()
        llm.available = True

        call_count = {"n": 0}

        def _generate(prompt: str) -> str | None:
            call_count["n"] += 1
            # 2 回目の呼び出し（2 チャンク目）だけ失敗させる
            if call_count["n"] == 2:
                return None
            return prompt.split("\n\n")[-1]

        llm.generate.side_effect = _generate
        processor = _make_processor(llm)

        text = "".join(f"文{i}です。" for i in range(500))
        result = processor._fix_text(text)

        # チャンク失敗時も元テキストを使うので、全文の長さは保持される
        assert len(result) == len(text)
        assert result == text


# ---------------------------------------------------------------------------
# _summarize のテスト
# ---------------------------------------------------------------------------


class TestSummarizeInputLimit:
    """要約入力が長文時に制限されることを検証する."""

    def test_long_input_is_truncated_for_summary(self) -> None:
        llm = MagicMock()
        llm.available = True
        captured = {}

        def _generate(prompt: str) -> str:
            captured["prompt"] = prompt
            return "要約結果。"

        llm.generate.side_effect = _generate
        processor = _make_processor(llm)

        text = "あ" * (_SUMMARY_MAX_INPUT_CHARS + 5000)
        processor._summarize(text)

        # プロンプトに含まれる本文部分が上限文字数以下に制限されている
        body = captured["prompt"].split("\n\n")[-1]
        assert len(body) <= _SUMMARY_MAX_INPUT_CHARS


# ---------------------------------------------------------------------------
# チャンクサイズの動的算出テスト
# ---------------------------------------------------------------------------


class TestComputeChunkCharSize:
    """max_tokens からチャンク文字数を動的算出することを検証する."""

    def test_larger_max_tokens_gives_larger_chunk(self) -> None:
        """max_tokens が大きいほどチャンクサイズも大きくなる（単調増加）."""
        llm = MagicMock()
        llm.available = True
        small = _make_processor(llm, max_tokens=1024)._compute_chunk_char_size()
        large = _make_processor(llm, max_tokens=5000)._compute_chunk_char_size()
        assert large > small

    def test_clamped_to_min(self) -> None:
        """max_tokens が極端に小さくても下限を下回らない."""
        llm = MagicMock()
        llm.available = True
        size = _make_processor(llm, max_tokens=1)._compute_chunk_char_size()
        assert size == _MIN_CHUNK_CHAR_SIZE

    def test_clamped_to_max(self) -> None:
        """max_tokens が極端に大きくても上限を超えない."""
        llm = MagicMock()
        llm.available = True
        size = _make_processor(llm, max_tokens=1_000_000)._compute_chunk_char_size()
        assert size == _MAX_CHUNK_CHAR_SIZE

    def test_zero_max_tokens_falls_back_to_min(self) -> None:
        """max_tokens が 0 以下でも下限にフォールバックする."""
        llm = MagicMock()
        llm.available = True
        size = _make_processor(llm, max_tokens=0)._compute_chunk_char_size()
        assert size == _MIN_CHUNK_CHAR_SIZE

    def test_computed_size_within_bounds(self) -> None:
        """算出結果は常に下限〜上限の範囲に収まる."""
        llm = MagicMock()
        llm.available = True
        for max_tokens in (1, 512, 1024, 4096, 5000, 65536):
            size = _make_processor(
                llm, max_tokens=max_tokens
            )._compute_chunk_char_size()
            assert _MIN_CHUNK_CHAR_SIZE <= size <= _MAX_CHUNK_CHAR_SIZE


def test_chunk_bounds_are_sane() -> None:
    """チャンクサイズの下限・上限が正で、下限 < 上限であること."""
    assert 0 < _MIN_CHUNK_CHAR_SIZE < _MAX_CHUNK_CHAR_SIZE
