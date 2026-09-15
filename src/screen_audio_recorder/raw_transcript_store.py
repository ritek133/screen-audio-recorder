"""RawTranscriptStore: 文字起こし生データの永続化管理モジュール.

LLM 後処理前の文字起こし生テキストを、メモ本文（修正済みテキスト）とは別に
個別の ``.txt`` ファイルとして保存・管理する。

保存先は ``~/Documents/screen-audio-recorder/transcripts/`` 配下で、
録画・録音ファイルのファイル名（拡張子を除く）に対応した名前で保存する。
これにより、メモ 1 件と生データ 1 件が 1 対 1 で対応する。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("screen_audio_recorder")

# 生データ保存先ディレクトリ（ホームディレクトリ相対）
_RELATIVE_DIR = Path("Documents") / "screen-audio-recorder" / "transcripts"

# 生データファイルの拡張子
_TRANSCRIPT_EXTENSION = ".txt"

# ファイル名に使用できない文字を置換するための正規表現（Windows 予約文字を含む）
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class RawTranscriptStore:
    """文字起こし生データを個別ファイルで管理するクラス.

    生テキストを ``~/Documents/screen-audio-recorder/transcripts/<name>.txt`` に
    保存し、保存したファイルの絶対パスを返す。パスから生テキストを読み戻すこともできる。

    録画・録音ファイルのファイル名に対応させることで、メモと生データを
    1 対 1 で紐づける。
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        """RawTranscriptStore を初期化し、保存先ディレクトリを自動作成する.

        Args:
            base_dir: 生データの保存先ディレクトリ。省略時は
                ``~/Documents/screen-audio-recorder/transcripts/`` を使用する。
        """
        if base_dir is None:
            base_dir = Path.home() / _RELATIVE_DIR

        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        """生データの保存先ディレクトリを返す."""
        return self._base_dir

    def save(self, text: str, output_file: Path) -> Path:
        """文字起こし生テキストを個別ファイルに保存し、パスを返す.

        ファイル名は ``output_file`` のファイル名（拡張子を除く）に基づき、
        ``<stem>.txt`` として保存する。生テキストが空文字列でもファイルを作成し、
        メモとの 1 対 1 対応を保つ。

        Args:
            text: 保存する文字起こし生テキスト（LLM 後処理前）。
            output_file: 対応する録画・録音ファイルのパス。ファイル名の
                決定に使用する。

        Returns:
            保存した生データファイルの絶対パス。
        """
        filename = self._build_filename(output_file)
        transcript_path = self._resolve_unique_path(filename)

        transcript_path.write_text(text, encoding="utf-8")
        logger.info(
            "文字起こし生データを保存しました: %s（%d 文字）",
            transcript_path,
            len(text),
        )
        return transcript_path

    def load(self, transcript_path: Path) -> str | None:
        """保存済みの生テキストを読み込む.

        Args:
            transcript_path: 生データファイルのパス。

        Returns:
            読み込んだ生テキスト。ファイルが存在しない、または読み込みに
            失敗した場合は None。
        """
        try:
            return transcript_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(
                "文字起こし生データの読み込みに失敗しました: %s（%s）",
                transcript_path,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # プライベートヘルパー
    # ------------------------------------------------------------------

    def _build_filename(self, output_file: Path) -> str:
        """録画・録音ファイル名から生データファイル名を組み立てる.

        ``output_file`` の stem を用い、ファイル名に使えない文字を ``_`` に
        置換する。stem が空になる場合は ``transcript`` をフォールバックとする。

        Args:
            output_file: 対応する録画・録音ファイルのパス。

        Returns:
            ``<safe_stem>.txt`` 形式のファイル名。
        """
        stem = output_file.stem
        safe_stem = _INVALID_FILENAME_CHARS.sub("_", stem).strip()
        if not safe_stem:
            safe_stem = "transcript"
        return f"{safe_stem}{_TRANSCRIPT_EXTENSION}"

    def _resolve_unique_path(self, filename: str) -> Path:
        """既存ファイルと衝突しない一意なパスを返す.

        同名ファイルが既に存在する場合は ``<stem>_1.txt``、``<stem>_2.txt``
        のように連番を付与する。

        Args:
            filename: 希望するファイル名（``<stem>.txt``）。

        Returns:
            保存先の絶対パス。
        """
        candidate = self._base_dir / filename
        if not candidate.exists():
            return candidate

        stem = candidate.stem
        suffix = candidate.suffix
        counter = 1
        while True:
            candidate = self._base_dir / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1
