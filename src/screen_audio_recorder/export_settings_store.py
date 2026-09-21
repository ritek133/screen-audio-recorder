"""メモエクスポート設定の永続化管理モジュール.

設定を ``~/Documents/screen-audio-recorder/export_settings.json`` に
JSON 形式で保存・読み込みする。ADR-004 参照。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from screen_audio_recorder.models import ExportSettings

logger = logging.getLogger(__name__)

_RELATIVE_DATA_DIR = Path("Documents") / "screen-audio-recorder"
_SETTINGS_FILENAME = "export_settings.json"

# HTML の既定出力先（output_dir が空のときに解決する）
_DEFAULT_EXPORT_SUBDIR = "export"
_DEFAULT_HTML_FILENAME = "memo-viewer.html"


def get_default_settings_path() -> Path:
    """デフォルトの設定ファイルパスを返す."""
    return Path.home() / _RELATIVE_DATA_DIR / _SETTINGS_FILENAME


def get_default_export_dir() -> Path:
    """HTML の既定出力ディレクトリを返す.

    ``ExportSettings.output_dir`` が空文字列のときに使用する。
    """
    return Path.home() / _RELATIVE_DATA_DIR / _DEFAULT_EXPORT_SUBDIR


def resolve_output_html_path(settings: ExportSettings) -> Path:
    """設定から出力先の HTML ファイルパスを解決する.

    ``output_dir`` が空なら既定ディレクトリを使う。
    ディレクトリを指している場合は既定のファイル名を付与する。

    Args:
        settings: エクスポート設定

    Returns:
        出力先 HTML ファイルの絶対パス
    """
    if settings.output_dir.strip():
        base = Path(settings.output_dir.strip())
    else:
        base = get_default_export_dir()

    # 拡張子が .html/.htm ならファイル指定とみなし、そのまま使う
    if base.suffix.lower() in (".html", ".htm"):
        return base
    return base / _DEFAULT_HTML_FILENAME


def load_export_settings(path: Path | None = None) -> ExportSettings:
    """設定ファイルから ExportSettings を読み込む.

    ファイルが存在しない場合やパースに失敗した場合はデフォルト設定を返す。

    Args:
        path: 設定ファイルのパス。None の場合はデフォルトパスを使用。

    Returns:
        読み込んだ ExportSettings オブジェクト
    """
    if path is None:
        path = get_default_settings_path()

    if not path.exists():
        return ExportSettings()

    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "エクスポート設定ファイルの読み込みに失敗しました: %s。デフォルト設定を使用します。",
            exc,
        )
        return ExportSettings()

    if not isinstance(data, dict):
        return ExportSettings()

    return ExportSettings(
        html_enabled=bool(data.get("html_enabled", False)),
        output_dir=str(data.get("output_dir", "")),
        include_output_file_path=bool(data.get("include_output_file_path", False)),
    )


def save_export_settings(settings: ExportSettings, path: Path | None = None) -> None:
    """ExportSettings を設定ファイルに保存する.

    Args:
        settings: 保存する ExportSettings オブジェクト
        path: 設定ファイルのパス。None の場合はデフォルトパスを使用。
    """
    if path is None:
        path = get_default_settings_path()

    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "html_enabled": settings.html_enabled,
        "output_dir": settings.output_dir,
        "include_output_file_path": settings.include_output_file_path,
    }
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    logger.info("エクスポート設定を保存しました: %s", path)
