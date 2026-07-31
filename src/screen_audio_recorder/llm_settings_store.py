"""LLM 設定の永続化管理モジュール.

LLM 設定・文字起こし設定・AWS 設定を
``~/Documents/screen-audio-recorder/llm_settings.json`` に
JSON 形式で保存・読み込みする。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from screen_audio_recorder.models import (
    DEFAULT_PROMPT_FIX_TEXT,
    DEFAULT_PROMPT_SUMMARIZE,
    DEFAULT_PROMPT_THEME,
    AwsAuthMethod,
    AwsSettings,
    LlmBackend,
    LlmSettings,
    TranscriberBackend,
    TranscriberSettings,
)

logger = logging.getLogger(__name__)

_RELATIVE_DATA_DIR = Path("Documents") / "screen-audio-recorder"
_SETTINGS_FILENAME = "llm_settings.json"


def get_default_settings_path() -> Path:
    """デフォルトの設定ファイルパスを返す."""
    return Path.home() / _RELATIVE_DATA_DIR / _SETTINGS_FILENAME


def load_settings(path: Path | None = None) -> LlmSettings:
    """設定ファイルから LlmSettings を読み込む.

    ファイルが存在しない場合やパースに失敗した場合はデフォルト設定を返す。

    Args:
        path: 設定ファイルのパス。None の場合はデフォルトパスを使用。

    Returns:
        読み込んだ LlmSettings オブジェクト
    """
    if path is None:
        path = get_default_settings_path()

    if not path.exists():
        logger.info("LLM 設定ファイルが見つかりません。デフォルト設定を使用します: %s", path)
        return LlmSettings()

    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("LLM 設定ファイルの読み込みに失敗しました: %s。デフォルト設定を使用します。", exc)
        return LlmSettings()

    return _dict_to_settings(data)


def load_all_settings(
    path: Path | None = None,
) -> tuple[LlmSettings, TranscriberSettings, AwsSettings]:
    """設定ファイルから全設定を読み込む.

    Args:
        path: 設定ファイルのパス。None の場合はデフォルトパスを使用。

    Returns:
        (LlmSettings, TranscriberSettings, AwsSettings) のタプル
    """
    if path is None:
        path = get_default_settings_path()

    if not path.exists():
        logger.info("設定ファイルが見つかりません。デフォルト設定を使用します: %s", path)
        return LlmSettings(), TranscriberSettings(), AwsSettings()

    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("設定ファイルの読み込みに失敗しました: %s。デフォルト設定を使用します。", exc)
        return LlmSettings(), TranscriberSettings(), AwsSettings()

    llm_settings = _dict_to_settings(data)
    transcriber_settings = _dict_to_transcriber_settings(data.get("transcriber", {}))
    aws_settings = _dict_to_aws_settings(data.get("aws", {}))

    return llm_settings, transcriber_settings, aws_settings


def save_settings(settings: LlmSettings, path: Path | None = None) -> None:
    """LlmSettings を設定ファイルに保存する.

    Args:
        settings: 保存する LlmSettings オブジェクト
        path: 設定ファイルのパス。None の場合はデフォルトパスを使用。
    """
    if path is None:
        path = get_default_settings_path()

    path.parent.mkdir(parents=True, exist_ok=True)

    data = _settings_to_dict(settings)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    logger.info("LLM 設定を保存しました: %s", path)


def save_all_settings(
    llm_settings: LlmSettings,
    transcriber_settings: TranscriberSettings,
    aws_settings: AwsSettings,
    path: Path | None = None,
) -> None:
    """全設定を設定ファイルに保存する.

    Args:
        llm_settings: LLM 設定
        transcriber_settings: 文字起こし設定
        aws_settings: AWS 接続設定
        path: 設定ファイルのパス。None の場合はデフォルトパスを使用。
    """
    if path is None:
        path = get_default_settings_path()

    path.parent.mkdir(parents=True, exist_ok=True)

    data = _settings_to_dict(llm_settings)
    data["transcriber"] = _transcriber_settings_to_dict(transcriber_settings)
    data["aws"] = _aws_settings_to_dict(aws_settings)

    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    logger.info("全設定を保存しました: %s", path)


def _settings_to_dict(settings: LlmSettings) -> dict:
    """LlmSettings を辞書に変換する."""
    return {
        "backend": settings.backend.value,
        "local_model_path": settings.local_model_path,
        "api_endpoint": settings.api_endpoint,
        "api_key": settings.api_key,
        "prompt_fix_text": settings.prompt_fix_text,
        "prompt_summarize": settings.prompt_summarize,
        "prompt_theme": settings.prompt_theme,
        "max_tokens": settings.max_tokens,
        "temperature": settings.temperature,
        "ctx_size": settings.ctx_size,
        "timeout_seconds": settings.timeout_seconds,
        "whisper_model_size": settings.whisper_model_size,
        "bedrock_model_id": settings.bedrock_model_id,
    }


def _dict_to_settings(data: dict) -> LlmSettings:
    """辞書を LlmSettings に変換する."""
    backend_str = data.get("backend", "local")
    try:
        backend = LlmBackend(backend_str)
    except ValueError:
        backend = LlmBackend.LOCAL

    return LlmSettings(
        backend=backend,
        local_model_path=data.get("local_model_path", ""),
        api_endpoint=data.get("api_endpoint", "http://localhost:8080/v1/chat/completions"),
        api_key=data.get("api_key", ""),
        prompt_fix_text=data.get("prompt_fix_text", DEFAULT_PROMPT_FIX_TEXT),
        prompt_summarize=data.get("prompt_summarize", DEFAULT_PROMPT_SUMMARIZE),
        prompt_theme=data.get("prompt_theme", DEFAULT_PROMPT_THEME),
        max_tokens=data.get("max_tokens", 1024),
        temperature=data.get("temperature", 0.3),
        ctx_size=data.get("ctx_size", 8192),
        timeout_seconds=data.get("timeout_seconds", 600),
        whisper_model_size=data.get("whisper_model_size", "small"),
        bedrock_model_id=data.get(
            "bedrock_model_id", "anthropic.claude-3-haiku-20240307-v1:0"
        ),
    )


def _transcriber_settings_to_dict(settings: TranscriberSettings) -> dict:
    """TranscriberSettings を辞書に変換する."""
    return {
        "backend": settings.backend.value,
        "whisper_model_size": settings.whisper_model_size,
        "vllm_endpoint": settings.vllm_endpoint,
        "vllm_model_name": settings.vllm_model_name,
        "aws_transcribe_language": settings.aws_transcribe_language,
    }


def _dict_to_transcriber_settings(data: dict) -> TranscriberSettings:
    """辞書を TranscriberSettings に変換する."""
    backend_str = data.get("backend", "local")
    try:
        backend = TranscriberBackend(backend_str)
    except ValueError:
        backend = TranscriberBackend.LOCAL

    return TranscriberSettings(
        backend=backend,
        whisper_model_size=data.get("whisper_model_size", "small"),
        vllm_endpoint=data.get("vllm_endpoint", ""),
        vllm_model_name=data.get("vllm_model_name", "whisper-large-v3"),
        aws_transcribe_language=data.get("aws_transcribe_language", "ja-JP"),
    )


def _aws_settings_to_dict(settings: AwsSettings) -> dict:
    """AwsSettings を辞書に変換する."""
    return {
        "auth_method": settings.auth_method.value,
        "region": settings.region,
        "profile_name": settings.profile_name,
        "access_key_id": settings.access_key_id,
        "secret_access_key": settings.secret_access_key,
        "session_token": settings.session_token,
    }


def _dict_to_aws_settings(data: dict) -> AwsSettings:
    """辞書を AwsSettings に変換する."""
    auth_str = data.get("auth_method", "profile")
    try:
        auth_method = AwsAuthMethod(auth_str)
    except ValueError:
        auth_method = AwsAuthMethod.PROFILE

    return AwsSettings(
        auth_method=auth_method,
        region=data.get("region", "ap-northeast-1"),
        profile_name=data.get("profile_name", ""),
        access_key_id=data.get("access_key_id", ""),
        secret_access_key=data.get("secret_access_key", ""),
        session_token=data.get("session_token", ""),
    )
