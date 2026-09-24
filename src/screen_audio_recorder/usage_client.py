"""使用量集約 API クライアント（ADR-006 案B）.

SaaS 利用者ごとの残存容量（残トークン・残文字起こし回数・リセット日時）を、
使用量集約 API（API Gateway + Lambda、IAM 認可 / SigV4 署名）から取得する。

方針:
    - 上限値そのものはアプリに保存せず、Lambda が返す残量・上限・使用量を
      そのまま表示する（差分計算はサーバー側で完結する）。
    - boto3 / botocore はモジュールトップレベルでは import せず、関数内で遅延
      import する（起動最適化 ADR-005 の方針に整合）。
    - エンドポイント未設定・boto3 未導入・例外・非 200 応答のいずれの場合も、
      error 付きの :class:`UsageInfo` を返し、決して例外を送出しない（呼び出し側
      の録画機能等を阻害しないため）。
    - 認証情報やレスポンス全文はログに出力しない。
"""

from __future__ import annotations

import json
import logging

from screen_audio_recorder.models import AwsSettings, UsageInfo

logger = logging.getLogger(__name__)

# HTTP メソッドとサービス名（API Gateway への SigV4 署名に使用）。
_HTTP_METHOD = "GET"
_SERVICE_NAME = "execute-api"


def fetch_usage(aws_settings: AwsSettings) -> UsageInfo:
    """使用量集約 API から残存容量を取得して :class:`UsageInfo` を返す.

    SigV4 署名付きの ``GET`` リクエストを ``usage_api_endpoint`` に送信し、
    レスポンス JSON を :class:`UsageInfo` にマッピングする。

    失敗しうるあらゆるケース（エンドポイント未設定・boto3 未導入・署名失敗・
    通信失敗・非 200 応答・JSON パース失敗）では、例外を送出せず error 付きの
    :class:`UsageInfo` を返す。

    Args:
        aws_settings: AWS 接続設定（``usage_api_endpoint`` を含む）。

    Returns:
        取得した使用量情報。失敗時は ``error`` に理由を格納した
        :class:`UsageInfo`。
    """
    endpoint = (aws_settings.usage_api_endpoint or "").strip()
    if not endpoint:
        return UsageInfo(error="使用量 API のエンドポイントが設定されていません。")

    # boto3 / botocore を遅延 import する（起動最適化 ADR-005）。
    from screen_audio_recorder.aws_utils import create_boto3_session, is_boto3_available

    if not is_boto3_available():
        return UsageInfo(error="boto3 がインストールされていないため使用量を取得できません。")

    try:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest

        session = create_boto3_session(aws_settings)
        credentials = session.get_credentials()
        if credentials is None:
            return UsageInfo(error="AWS 認証情報を取得できませんでした。")

        # 署名用のフローズンクレデンシャルを取得する。
        frozen = credentials.get_frozen_credentials()

        request = AWSRequest(method=_HTTP_METHOD, url=endpoint)
        region = getattr(session, "region_name", None) or aws_settings.region
        SigV4Auth(frozen, _SERVICE_NAME, region).add_auth(request)

        prepared = request.prepare()

        # 送信は botocore の HTTP セッションを使う（余計な依存を増やさない）。
        from botocore.httpsession import URLLib3Session

        http = URLLib3Session()
        response = http.send(prepared)

        status_code = response.status_code
        if status_code != 200:
            logger.warning("使用量 API が非 200 応答を返しました: status=%s", status_code)
            return UsageInfo(error=f"使用量 API がエラーを返しました (HTTP {status_code})。")

        body = response.text
        data = json.loads(body)
        return _map_response(data)
    except Exception as exc:
        # レスポンス全文や認証情報はログに出さず、例外の型・要約のみ記録する。
        logger.warning("使用量の取得に失敗しました: %s", type(exc).__name__)
        return UsageInfo(error="使用量の取得に失敗しました。")


def _map_response(data: dict) -> UsageInfo:
    """使用量 API のレスポンス JSON を :class:`UsageInfo` にマッピングする.

    Args:
        data: Lambda が返した JSON をデコードした辞書。

    Returns:
        マッピング済みの :class:`UsageInfo`。
    """
    return UsageInfo(
        monthly_token_limit=data.get("monthly_token_limit"),
        used_tokens=data.get("used_tokens"),
        remaining_tokens=data.get("remaining_tokens"),
        monthly_transcribe_job_limit=data.get("monthly_transcribe_job_limit"),
        used_transcribe_jobs=data.get("used_transcribe_jobs"),
        remaining_transcribe_jobs=data.get("remaining_transcribe_jobs"),
        period_start=data.get("period_start"),
        reset_at=data.get("reset_at"),
        retrieved_at=data.get("retrieved_at"),
        error=None,
    )
