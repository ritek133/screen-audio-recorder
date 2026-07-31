"""AWS ユーティリティモジュール.

boto3 クライアントの生成を共通化し、認証方式の切り替えを一箇所で管理する。
"""

from __future__ import annotations

import logging
from typing import Any

from screen_audio_recorder.models import AwsAuthMethod, AwsSettings

logger = logging.getLogger(__name__)

try:
    import boto3
    from botocore.config import Config as BotoConfig

    _BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None  # type: ignore[assignment]
    BotoConfig = None  # type: ignore[assignment,misc]
    _BOTO3_AVAILABLE = False


def is_boto3_available() -> bool:
    """boto3 が利用可能かどうかを返す."""
    return _BOTO3_AVAILABLE


def create_boto3_session(aws_settings: AwsSettings) -> Any:
    """AwsSettings に基づいて boto3 Session を作成する.

    Args:
        aws_settings: AWS 接続設定

    Returns:
        boto3.Session インスタンス

    Raises:
        RuntimeError: boto3 が利用不可の場合
    """
    if not _BOTO3_AVAILABLE:
        raise RuntimeError(
            "boto3 がインストールされていません。\n"
            "pip install boto3 を実行してください。"
        )

    if aws_settings.auth_method == AwsAuthMethod.ACCESS_KEY:
        # アクセスキー直接入力
        session_kwargs: dict[str, str] = {
            "region_name": aws_settings.region,
        }
        if aws_settings.access_key_id and aws_settings.secret_access_key:
            session_kwargs["aws_access_key_id"] = aws_settings.access_key_id
            session_kwargs["aws_secret_access_key"] = aws_settings.secret_access_key
            if aws_settings.session_token:
                session_kwargs["aws_session_token"] = aws_settings.session_token

        return boto3.Session(**session_kwargs)
    else:
        # プロファイル / 環境変数 / IAM ロール（boto3 デフォルト）
        session_kwargs = {"region_name": aws_settings.region}
        if aws_settings.profile_name:
            session_kwargs["profile_name"] = aws_settings.profile_name

        return boto3.Session(**session_kwargs)


def create_boto3_client(service_name: str, aws_settings: AwsSettings, **kwargs) -> Any:
    """AwsSettings に基づいて boto3 クライアントを作成する.

    Args:
        service_name: AWS サービス名（例: "transcribe", "bedrock-runtime", "s3"）
        aws_settings: AWS 接続設定
        **kwargs: boto3 client() に渡す追加引数

    Returns:
        boto3 クライアントインスタンス

    Raises:
        RuntimeError: boto3 が利用不可の場合
    """
    session = create_boto3_session(aws_settings)

    # Bedrock は読み取りタイムアウトを長めに設定
    if service_name in ("bedrock-runtime",):
        config = BotoConfig(
            read_timeout=600,
            connect_timeout=10,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        kwargs.setdefault("config", config)

    client = session.client(service_name, **kwargs)
    logger.debug(
        "AWS クライアント作成: service=%s, region=%s, auth=%s",
        service_name,
        aws_settings.region,
        aws_settings.auth_method.value,
    )
    return client
