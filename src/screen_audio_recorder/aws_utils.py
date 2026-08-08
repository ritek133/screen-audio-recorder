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


def _get_ca_bundle() -> str | None:
    """SSL CA バンドルのパスを取得する.

    環境変数 AWS_CA_BUNDLE が設定されていればそれを使い、
    なければ certifi + Windows 証明書ストアのマージ証明書を生成する。
    """
    import os

    # 環境変数で明示指定されていればそれを使用
    if os.environ.get("AWS_CA_BUNDLE"):
        return None  # boto3 が環境変数を自動的に参照する

    # Windows の場合、システム証明書ストアから CA バンドルを生成
    import sys
    if sys.platform != "win32":
        return None

    try:
        import ssl
        import tempfile
        from pathlib import Path

        # キャッシュ先: アプリデータフォルダ
        cache_dir = Path.home() / "Documents" / "screen-audio-recorder"
        cache_dir.mkdir(parents=True, exist_ok=True)
        ca_bundle_path = cache_dir / "ca-bundle.pem"

        # certifi のバンドルを読み込み
        try:
            import certifi
            certifi_certs = Path(certifi.where()).read_text(encoding="utf-8")
        except (ImportError, OSError):
            certifi_certs = ""

        # Windows 証明書ストアから取得
        win_certs = []
        for store_name in ("ROOT", "CA"):
            try:
                for cert, _encoding, _trust in ssl.enum_certificates(store_name):
                    pem = ssl.DER_cert_to_PEM_cert(cert)
                    win_certs.append(pem)
            except (OSError, PermissionError):
                pass

        if win_certs:
            combined = certifi_certs + "\n" + "\n".join(win_certs)
            ca_bundle_path.write_text(combined, encoding="utf-8")
            logger.debug("CA バンドルを生成しました: %s（%d 件のシステム証明書を追加）", ca_bundle_path, len(win_certs))
            return str(ca_bundle_path)

    except Exception as exc:
        logger.debug("CA バンドル生成に失敗: %s", exc)

    return None


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

    # SSL CA バンドルを設定（プロキシ環境対応）
    ca_bundle = _get_ca_bundle()
    if ca_bundle:
        kwargs.setdefault("verify", ca_bundle)

    client = session.client(service_name, **kwargs)
    logger.debug(
        "AWS クライアント作成: service=%s, region=%s, auth=%s",
        service_name,
        aws_settings.region,
        aws_settings.auth_method.value,
    )
    return client
