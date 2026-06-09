"""アプリケーション全般設定の永続化管理モジュール.

設定を ``~/Documents/screen-audio-recorder/app_settings.json`` に
JSON 形式で保存・読み込みする。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from screen_audio_recorder.models import AppSettings

logger = logging.getLogger(__name__)

_RELATIVE_DATA_DIR = Path("Documents") / "screen-audio-recorder"
_SETTINGS_FILENAME = "app_settings.json"


def get_default_settings_path() -> Path:
    """デフォルトの設定ファイルパスを返す."""
    return Path.home() / _RELATIVE_DATA_DIR / _SETTINGS_FILENAME


def load_app_settings(path: Path | None = None) -> AppSettings:
    """設定ファイルから AppSettings を読み込む.

    ファイルが存在しない場合やパースに失敗した場合はデフォルト設定を返す。

    Args:
        path: 設定ファイルのパス。None の場合はデフォルトパスを使用。

    Returns:
        読み込んだ AppSettings オブジェクト
    """
    if path is None:
        path = get_default_settings_path()

    if not path.exists():
        return AppSettings()

    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("アプリ設定ファイルの読み込みに失敗しました: %s。デフォルト設定を使用します。", exc)
        return AppSettings()

    return AppSettings(
        verbose_logging=data.get("verbose_logging", False),
    )


def save_app_settings(settings: AppSettings, path: Path | None = None) -> None:
    """AppSettings を設定ファイルに保存する.

    Args:
        settings: 保存する AppSettings オブジェクト
        path: 設定ファイルのパス。None の場合はデフォルトパスを使用。
    """
    if path is None:
        path = get_default_settings_path()

    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "verbose_logging": settings.verbose_logging,
    }
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    logger.info("アプリ設定を保存しました: %s", path)
