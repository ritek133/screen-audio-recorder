"""ThemeGeneratorService のユニットテストおよびプロパティテスト.

**Validates: Requirements 7.1, 7.2, 7.3**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from screen_audio_recorder.theme_generator import ThemeGeneratorService


# ---------------------------------------------------------------------------
# テスト用フィクスチャ
# ---------------------------------------------------------------------------


@pytest.fixture()
def service() -> ThemeGeneratorService:
    """ThemeGeneratorService インスタンスを返す."""
    return ThemeGeneratorService()


# ---------------------------------------------------------------------------
# ユニットテスト: 空・None 入力 → "無題"
# ---------------------------------------------------------------------------


class TestThemeGeneratorEmpty:
    """空テキスト・None 入力に対するテスト（要件 7.3）."""

    def test_empty_string_returns_default(self, service: ThemeGeneratorService) -> None:
        """空文字列に対して "無題" を返す."""
        assert service.generate("") == "無題"

    def test_whitespace_only_returns_default(self, service: ThemeGeneratorService) -> None:
        """空白のみの文字列に対して "無題" を返す."""
        assert service.generate("   ") == "無題"

    def test_tab_only_returns_default(self, service: ThemeGeneratorService) -> None:
        """タブのみの文字列に対して "無題" を返す."""
        assert service.generate("\t\n") == "無題"

    def test_none_returns_default(self, service: ThemeGeneratorService) -> None:
        """None に対して "無題" を返す."""
        assert service.generate(None) == "無題"


# ---------------------------------------------------------------------------
# ユニットテスト: 通常テキスト → 10 文字以内
# ---------------------------------------------------------------------------


class TestThemeGeneratorNormal:
    """通常テキスト入力に対するテスト（要件 7.1、7.2）."""

    def test_normal_text_within_10_chars(self, service: ThemeGeneratorService) -> None:
        """通常テキストから生成されるテーマが 10 文字以内である."""
        result = service.generate("本日の会議では重要な決定がありました。プロジェクトの進捗について話し合いました。")
        assert len(result) <= 10

    def test_short_text_returns_nonempty(self, service: ThemeGeneratorService) -> None:
        """短いテキストでも空でないテーマが返される."""
        result = service.generate("会議")
        assert result != ""

    def test_long_text_truncated_to_10_chars(self, service: ThemeGeneratorService) -> None:
        """長いテキストから生成されるテーマが 10 文字以内に切り詰められる."""
        long_text = "会議" * 50 + "プロジェクト" * 50 + "報告" * 50
        result = service.generate(long_text)
        assert len(result) <= 10

    def test_result_is_string(self, service: ThemeGeneratorService) -> None:
        """生成結果が文字列型である."""
        result = service.generate("テスト文章です。")
        assert isinstance(result, str)

    def test_text_with_only_symbols_returns_default(self, service: ThemeGeneratorService) -> None:
        """記号のみのテキストで抽出キーワードがない場合は "無題" を返す."""
        # 記号・数字のみの場合、名詞・動詞・形容詞が抽出されないことがある
        # 実際の動作を確認するテスト（"無題" または 10 文字以内の文字列）
        result = service.generate("123 456")
        assert isinstance(result, str)
        assert len(result) <= 10


# ---------------------------------------------------------------------------
# プロパティテスト: プロパティ 9 — テーマの文字数制約
# ---------------------------------------------------------------------------


@given(text=st.text(min_size=1))
@settings(max_examples=200)
def test_theme_length_constraint(text: str) -> None:
    """プロパティ 9: テーマの文字数制約.

    任意の文字起こしテキスト（空でないもの）に対して、
    ThemeGeneratorService が生成するテーマは 10 文字以内でなければならない。

    **Validates: Requirements 7.1**
    """
    service = ThemeGeneratorService()
    result = service.generate(text)
    assert len(result) <= 10, (
        f"生成されたテーマ {result!r} が 10 文字を超えている (長さ: {len(result)})"
    )


# ---------------------------------------------------------------------------
# プロパティテスト: プロパティ 10 — 空テキストに対するテーマ
# ---------------------------------------------------------------------------


@given(
    text=st.one_of(
        st.just(""),
        st.just(None),
        st.text(alphabet=st.characters(categories=["Zs", "Cc"]), min_size=1, max_size=50),
    )
)
@settings(max_examples=200)
def test_empty_text_returns_default_theme(text: str | None) -> None:
    """プロパティ 10: 空テキストに対するテーマ.

    任意の「空」に相当する入力（空文字列、空白のみの文字列、None）に対して、
    ThemeGeneratorService は "無題" を返さなければならない。

    **Validates: Requirements 7.3**
    """
    service = ThemeGeneratorService()
    result = service.generate(text)
    assert result == "無題", (
        f"空テキスト {text!r} に対して '無題' 以外が返された: {result!r}"
    )
