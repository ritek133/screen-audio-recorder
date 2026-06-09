"""テーマ自動生成サービス.

文字起こしテキストから形態素解析を用いて 10 文字以内のテーマを生成する。
"""

from __future__ import annotations

from collections import Counter

from janome.tokenizer import Tokenizer

# 形態素解析で抽出する品詞
_TARGET_POS = {"名詞", "動詞", "形容詞"}

# テーマの最大文字数
_MAX_THEME_LENGTH = 10

# 空テキスト時のデフォルトテーマ
_DEFAULT_THEME = "無題"

# Tokenizer はインスタンス生成コストが高いためモジュールレベルで保持
_tokenizer = Tokenizer()


class ThemeGeneratorService:
    """文字起こしテキストからテーマを自動生成するサービス."""

    def generate(self, text: str | None) -> str:
        """文字起こしテキストから 10 文字以内のテーマを生成する.

        形態素解析（janome）で名詞・動詞・形容詞を抽出し、
        出現頻度上位のキーワードを結合してテーマを生成する。
        結合結果が 10 文字を超える場合は先頭 10 文字に切り詰める。

        Args:
            text: 文字起こしテキスト。空文字列・空白のみ・None の場合は "無題" を返す。

        Returns:
            生成されたテーマ文字列（10 文字以内）。
            入力が空の場合は "無題"。
        """
        # 空・空白のみ・None チェック
        if not text or not text.strip():
            return _DEFAULT_THEME

        # 形態素解析してキーワードを抽出
        keywords: list[str] = []
        for token in _tokenizer.tokenize(text):
            # part_of_speech は "名詞,固有名詞,..." のような形式
            pos = token.part_of_speech.split(",")[0]
            if pos in _TARGET_POS:
                surface = token.surface.strip()
                if surface:
                    keywords.append(surface)

        if not keywords:
            return _DEFAULT_THEME

        # 出現頻度の高い順にキーワードを並べ替え
        counter = Counter(keywords)
        # 頻度降順、同頻度の場合は出現順を維持するため stable sort
        sorted_keywords = [word for word, _ in counter.most_common()]

        # キーワードを結合
        theme = "".join(sorted_keywords)

        # 10 文字を超える場合は先頭 10 文字に切り詰め
        return theme[:_MAX_THEME_LENGTH]
