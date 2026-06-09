"""TextPostProcessor: LLM を使用した文字起こしテキストの後処理.

テキスト修正（句読点・誤字脱字）、内容要約、テーマ生成の 3 タスクを実行する。
LLM が利用不可または失敗した場合は、従来の janome ベースのテーマ生成にフォールバックする。

**Validates: Requirements 10.1, 10.2, 10.3, 10.6, 10.7**
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from screen_audio_recorder.models import LlmSettings, PostProcessResult

if TYPE_CHECKING:
    from screen_audio_recorder.llm_client import LlmClient
    from screen_audio_recorder.theme_generator import ThemeGeneratorService

logger = logging.getLogger(__name__)

# テーマの最大文字数
_MAX_THEME_LENGTH = 10

# 空テキスト時のデフォルトテーマ
_DEFAULT_THEME = "無題"


class TextPostProcessor:
    """LLM を使用した文字起こしテキストの後処理サービス.

    3 つのタスクを順次実行する:
        1. テキスト修正（句読点補完・誤字脱字修正）
        2. 要約生成
        3. テーマ生成

    LLM が利用不可または各タスクが失敗した場合のフォールバック:
        - テキスト修正: 元テキストをそのまま使用
        - 要約生成: 空文字列
        - テーマ生成: ThemeGeneratorService（janome ベース）で生成

    Attributes:
        _llm_client: LLM クライアント
        _theme_fallback: フォールバック用テーマ生成サービス
        _settings: LLM 設定（プロンプトテンプレート参照用）
    """

    # プロンプトの指示部分に含まれる典型的なフレーズ（出力に混入した場合に除去する）
    _PROMPT_NOISE_PHRASES = [
        "以下の日本語テキストの内容を3〜5文で簡潔に要約してください。",
        "必ず日本語で出力してください。英語で出力しないでください。",
        "要約のみを出力してください。",
        "以下の日本語テキストの句読点を補完し、誤字脱字を修正してください。",
        "意味を変えず、自然な日本語に整えてください。",
        "必ず日本語で出力してください。修正後のテキストのみを出力してください。",
        "以下の日本語テキストの内容を表す10文字以内の短いテーマ名を1つ生成してください。",
        "日本語で、テーマ名のみを出力してください。",
    ]

    def __init__(
        self,
        llm_client: LlmClient,
        theme_generator_fallback: ThemeGeneratorService,
        settings: LlmSettings,
    ) -> None:
        """TextPostProcessor を初期化する.

        Args:
            llm_client: LLM クライアント
            theme_generator_fallback: フォールバック用テーマ生成サービス
            settings: LLM 設定
        """
        self._llm_client = llm_client
        self._theme_fallback = theme_generator_fallback
        self._settings = settings

    def update_settings(self, settings: LlmSettings) -> None:
        """設定を更新する.

        Args:
            settings: 新しい LLM 設定
        """
        self._settings = settings

    def process(self, text: str) -> PostProcessResult:
        """文字起こしテキストを後処理する.

        Args:
            text: 文字起こし生テキスト

        Returns:
            後処理結果（修正テキスト・要約・テーマ）
        """
        # 空テキストの場合は即座にデフォルト値を返す
        if not text or not text.strip():
            return PostProcessResult(
                corrected_text="",
                summary="",
                theme=_DEFAULT_THEME,
                used_llm=False,
            )

        used_llm = False

        # 1. テキスト修正
        corrected_text = self._fix_text(text)
        if corrected_text != text:
            used_llm = True

        # 2. 要約生成
        summary = self._summarize(corrected_text)
        if summary:
            used_llm = True

        # 3. テーマ生成
        theme = self._generate_theme(corrected_text)
        if theme != self._theme_fallback.generate(corrected_text):
            used_llm = True

        return PostProcessResult(
            corrected_text=corrected_text,
            summary=summary,
            theme=theme,
            used_llm=used_llm,
        )

    def _fix_text(self, text: str) -> str:
        """テキストの句読点補完・誤字脱字修正を行う.

        Args:
            text: 修正対象テキスト

        Returns:
            修正済みテキスト。LLM 失敗時は元テキスト。
        """
        if not self._llm_client.available:
            return text

        prompt = self._settings.prompt_fix_text.format(text=text)
        result = self._llm_client.generate(prompt)

        if result:
            # 元テキストに改行がない場合、LLM が勝手に入れた改行を除去する
            if "\n" not in text.strip():
                result = result.replace("\r\n", "").replace("\n", "")
            result = self._clean_output(result)
            logger.info("テキスト修正完了（LLM 使用）: %d → %d 文字", len(text), len(result))
            return result

        logger.warning("テキスト修正に失敗しました。元テキストを使用します。")
        return text

    def _summarize(self, text: str) -> str:
        """テキストの要約を生成する.

        Args:
            text: 要約対象テキスト

        Returns:
            要約テキスト。LLM 失敗時は空文字列。
        """
        if not self._llm_client.available:
            return ""

        prompt = self._settings.prompt_summarize.format(text=text)
        result = self._llm_client.generate(prompt)

        if result:
            result = self._clean_output(result)
            logger.info("要約生成完了（LLM 使用）: %d 文字", len(result))
            return result

        logger.warning("要約生成に失敗しました。空文字列を使用します。")
        return ""

    def _generate_theme(self, text: str) -> str:
        """テーマを生成する.

        LLM で生成を試み、失敗時は janome ベースのフォールバックを使用する。

        Args:
            text: テーマ生成対象テキスト

        Returns:
            10 文字以内のテーマ文字列
        """
        if not self._llm_client.available:
            return self._theme_fallback.generate(text)

        prompt = self._settings.prompt_theme.format(text=text)
        result = self._llm_client.generate(prompt)

        if result:
            # 10 文字以内に切り詰め
            result = self._clean_output(result)
            theme = result.strip()[:_MAX_THEME_LENGTH]
            if theme:
                logger.info("テーマ生成完了（LLM 使用）: %s", theme)
                return theme

        logger.warning("LLM テーマ生成に失敗しました。janome フォールバックを使用します。")
        return self._theme_fallback.generate(text)

    def _clean_output(self, text: str) -> str:
        """LLM 出力からプロンプト指示文の混入を除去する.

        小さいモデルはプロンプトの指示部分をオウム返しすることがあるため、
        既知のフレーズを除去する。

        Args:
            text: LLM の生出力

        Returns:
            クリーニング済みテキスト
        """
        for phrase in self._PROMPT_NOISE_PHRASES:
            text = text.replace(phrase, "")
        # 除去後に先頭・末尾の余分な空白や改行を整理
        return text.strip()
