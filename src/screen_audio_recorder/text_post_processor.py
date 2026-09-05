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

# --- チャンクサイズの動的算出パラメータ ---
#
# テキスト整形では、LLM は入力チャンクとほぼ同量のテキストを出力する。
# そのため 1 チャンクの文字数は「出力トークン上限（max_tokens）に収まる文字数」
# 以下に抑える必要がある。max_tokens からチャンク文字数を動的に算出することで、
# モデル（例: Amazon Nova Micro は出力上限 5,000 トークン）や設定変更に自動追従する。

# 日本語 1 文字あたりのおおよそのトークン数（安全側に大きめに見積もる）。
# 実際は 0.7〜1.5 程度だが、後半欠落を絶対に避けるため 1 文字 = 1 トークンとみなす。
_CHARS_PER_TOKEN = 1.0

# 出力トークン上限のうち、チャンク文字数に割り当てる安全係数。
# LLM が句読点補完で文字を増やす場合や、トークン見積り誤差を吸収するための余裕。
_CHUNK_SAFETY_RATIO = 0.7

# 算出したチャンクサイズの下限・上限（文字数）。
# max_tokens が極端に小さい/大きい場合でも現実的な範囲に収める。
_MIN_CHUNK_CHAR_SIZE = 200
_MAX_CHUNK_CHAR_SIZE = 8000

# 要約に投入するテキストの最大文字数。
# 全文が入力コンテキスト上限を超える場合でも要約処理が破綻しないように、
# 先頭からこの文字数までに制限する（本文自体は corrected_text 側で全文保持する）。
_SUMMARY_MAX_INPUT_CHARS = 6000


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

        長文は LLM の出力トークン上限で後半が切り捨てられるのを防ぐため、
        チャンクに分割して各チャンクを個別に整形し、結果を連結する。
        あるチャンクの LLM 整形が失敗した場合は、そのチャンクの元テキストを
        使用するため、全文が失われることはない。

        Args:
            text: 修正対象テキスト

        Returns:
            修正済みテキスト。LLM が利用不可の場合は元テキスト。
        """
        if not self._llm_client.available:
            return text

        chunk_size = self._compute_chunk_char_size()
        chunks = _split_into_chunks(text, chunk_size)

        # 短文（1 チャンク）の場合は従来どおり 1 回で処理する
        if len(chunks) <= 1:
            return self._fix_text_chunk(text)

        logger.info(
            "テキスト修正を %d チャンクに分割して実行します"
            "（合計 %d 文字 / チャンクサイズ %d 文字 / max_tokens %d）",
            len(chunks),
            len(text),
            chunk_size,
            self._settings.max_tokens,
        )

        fixed_parts: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            fixed = self._fix_text_chunk(chunk)
            if fixed != chunk:
                logger.debug("チャンク %d/%d の整形完了", index, len(chunks))
            else:
                logger.warning(
                    "チャンク %d/%d の整形に失敗したため元テキストを使用します",
                    index,
                    len(chunks),
                )
            fixed_parts.append(fixed)

        result = "".join(fixed_parts)
        logger.info(
            "テキスト修正完了（LLM 使用・%d チャンク）: %d → %d 文字",
            len(chunks),
            len(text),
            len(result),
        )
        return result

    def _fix_text_chunk(self, text: str) -> str:
        """単一チャンクの句読点補完・誤字脱字修正を行う.

        Args:
            text: 修正対象チャンク

        Returns:
            修正済みテキスト。LLM 失敗時は元テキスト。
        """
        prompt = self._settings.prompt_fix_text.format(text=text)
        result = self._llm_client.generate(prompt)

        if result:
            # 元テキストに改行がない場合、LLM が勝手に入れた改行を除去する
            if "\n" not in text.strip():
                result = result.replace("\r\n", "").replace("\n", "")
            result = self._clean_output(result)
            return result

        logger.warning("テキスト修正に失敗しました。元テキストを使用します。")
        return text

    def _compute_chunk_char_size(self) -> int:
        """出力トークン上限（max_tokens）からチャンク文字数を動的に算出する.

        LLM は入力チャンクとほぼ同量のテキストを出力するため、チャンクの文字数を
        出力トークン上限に収まる範囲に抑える必要がある。max_tokens に安全係数を掛け、
        1 文字あたりのトークン見積りで割って文字数へ換算し、下限・上限でクランプする。

        Returns:
            1 チャンクあたりの目安文字数（_MIN_CHUNK_CHAR_SIZE 以上
            _MAX_CHUNK_CHAR_SIZE 以下）。
        """
        max_tokens = self._settings.max_tokens
        # 不正値（0 以下）のフォールバック
        if max_tokens <= 0:
            return _MIN_CHUNK_CHAR_SIZE

        # 出力トークン上限 × 安全係数 → 文字数へ換算
        raw_chars = int(max_tokens * _CHUNK_SAFETY_RATIO / _CHARS_PER_TOKEN)

        # 下限・上限でクランプ
        clamped = max(_MIN_CHUNK_CHAR_SIZE, min(raw_chars, _MAX_CHUNK_CHAR_SIZE))
        return clamped

    def _summarize(self, text: str) -> str:
        """テキストの要約を生成する.

        Args:
            text: 要約対象テキスト

        Returns:
            要約テキスト。LLM 失敗時は空文字列。
        """
        if not self._llm_client.available:
            return ""

        # 全文が入力コンテキスト上限を超える恐れがあるため、要約用途では
        # 先頭から一定文字数までに制限する（本文は corrected_text 側で全文保持する）。
        summary_input = text
        if len(text) > _SUMMARY_MAX_INPUT_CHARS:
            summary_input = text[:_SUMMARY_MAX_INPUT_CHARS]
            logger.info(
                "要約対象が長いため先頭 %d 文字に制限しました（全文 %d 文字）",
                _SUMMARY_MAX_INPUT_CHARS,
                len(text),
            )

        prompt = self._settings.prompt_summarize.format(text=summary_input)
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

        # テーマ生成も入力コンテキスト上限を避けるため先頭から制限する
        theme_input = text[:_SUMMARY_MAX_INPUT_CHARS]

        prompt = self._settings.prompt_theme.format(text=theme_input)
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


# ---------------------------------------------------------------------------
# チャンク分割ユーティリティ
# ---------------------------------------------------------------------------

# 文の区切りとして扱う文字（この直後で分割する）
_SENTENCE_BOUNDARIES = ("。", "！", "？", "\n")


def _split_into_chunks(text: str, chunk_size: int) -> list[str]:
    """テキストを指定文字数を目安にチャンク分割する.

    文の途中で切れるのを避けるため、句点・感嘆符・疑問符・改行などの
    文境界を優先して分割する。1 文が ``chunk_size`` を超える場合は、
    その文をそのまま 1 チャンクとして扱う（文の内部では分割しない）。

    連結すると元テキストと一致するよう、区切り文字や文字の欠落は行わない。

    Args:
        text: 分割対象テキスト
        chunk_size: 1 チャンクあたりの目安文字数（正の値）

    Returns:
        チャンク文字列のリスト。空文字列の場合は空リスト。
    """
    if not text:
        return []
    if chunk_size <= 0:
        return [text]
    if len(text) <= chunk_size:
        return [text]

    # 文境界（境界文字の直後）でセグメントに分割する。
    # 境界文字自体はセグメントに含める（連結で元テキストに戻せるようにするため）。
    segments: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if char in _SENTENCE_BOUNDARIES:
            segments.append(text[start : index + 1])
            start = index + 1
    if start < len(text):
        segments.append(text[start:])

    # セグメントを chunk_size を超えない範囲でまとめる
    chunks: list[str] = []
    current = ""
    for segment in segments:
        if current and len(current) + len(segment) > chunk_size:
            chunks.append(current)
            current = segment
        else:
            current += segment
    if current:
        chunks.append(current)

    return chunks
