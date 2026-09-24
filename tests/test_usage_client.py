"""usage_client.fetch_usage のユニットテスト（ADR-006 案B）.

実ネットワーク・実 AWS へ接続せず、boto3 / botocore の署名・送信部分は
全てモックする。Windows 専用依存や tkinter は import しない。
"""

from __future__ import annotations

import json

from screen_audio_recorder import usage_client
from screen_audio_recorder.models import AwsSettings, UsageInfo


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


_VALID_BODY = {
    "monthly_token_limit": 500000,
    "used_tokens": 1500,
    "remaining_tokens": 498500,
    "monthly_transcribe_job_limit": 10,
    "used_transcribe_jobs": 3,
    "remaining_transcribe_jobs": 7,
    "period_start": "2026-09-01T00:00:00+00:00",
    "reset_at": "2026-10-01T00:00:00+00:00",
    "retrieved_at": "2026-09-24T10:00:00+00:00",
}


def _settings_with_endpoint() -> AwsSettings:
    """usage_api_endpoint を設定した AwsSettings を返す."""
    return AwsSettings(
        usage_api_endpoint="https://x.execute-api.ap-northeast-1.amazonaws.com/prod/usage"
    )


def _patch_boto_layers(mocker, *, status_code: int = 200, body: str | None = None):
    """boto3 / botocore の署名・送信レイヤをモックする.

    Args:
        mocker: pytest-mock フィクスチャ。
        status_code: 送信レスポンスの HTTP ステータス。
        body: レスポンス本文（JSON 文字列）。None なら有効な JSON を使う。
    """
    # boto3 は利用可能扱いにする。
    mocker.patch(
        "screen_audio_recorder.aws_utils.is_boto3_available", return_value=True
    )

    # セッションと認証情報をモック。
    fake_credentials = mocker.MagicMock()
    fake_credentials.get_frozen_credentials.return_value = mocker.MagicMock()
    fake_session = mocker.MagicMock()
    fake_session.get_credentials.return_value = fake_credentials
    fake_session.region_name = "ap-northeast-1"
    mocker.patch(
        "screen_audio_recorder.aws_utils.create_boto3_session",
        return_value=fake_session,
    )

    # SigV4Auth / AWSRequest をモック（署名処理を無害化）。
    mocker.patch("botocore.auth.SigV4Auth")
    fake_request = mocker.MagicMock()
    fake_request.prepare.return_value = mocker.MagicMock()
    mocker.patch("botocore.awsrequest.AWSRequest", return_value=fake_request)

    # HTTP 送信をモックし、指定のレスポンスを返す。
    fake_response = mocker.MagicMock()
    fake_response.status_code = status_code
    fake_response.text = body if body is not None else json.dumps(_VALID_BODY)
    fake_http = mocker.MagicMock()
    fake_http.send.return_value = fake_response
    mocker.patch("botocore.httpsession.URLLib3Session", return_value=fake_http)

    return fake_http


# ---------------------------------------------------------------------------
# (a) エンドポイント未設定
# ---------------------------------------------------------------------------


class TestEndpointNotConfigured:
    """usage_api_endpoint 未設定時のテスト."""

    def test_empty_endpoint_returns_error(self) -> None:
        """エンドポイント空 → error 付き UsageInfo を返し例外を送出しない."""
        result = usage_client.fetch_usage(AwsSettings(usage_api_endpoint=""))
        assert isinstance(result, UsageInfo)
        assert result.error is not None
        assert result.remaining_tokens is None

    def test_whitespace_endpoint_returns_error(self) -> None:
        """空白のみのエンドポイントも未設定扱いで error になる."""
        result = usage_client.fetch_usage(AwsSettings(usage_api_endpoint="   "))
        assert result.error is not None


# ---------------------------------------------------------------------------
# (b) 正常応答
# ---------------------------------------------------------------------------


class TestSuccessfulFetch:
    """正常 JSON → UsageInfo マッピングのテスト."""

    def test_maps_all_fields(self, mocker) -> None:
        """200 応答の JSON が UsageInfo の各フィールドへ正しくマッピングされる."""
        _patch_boto_layers(mocker, status_code=200)

        result = usage_client.fetch_usage(_settings_with_endpoint())

        assert result.error is None
        assert result.monthly_token_limit == 500000
        assert result.used_tokens == 1500
        assert result.remaining_tokens == 498500
        assert result.monthly_transcribe_job_limit == 10
        assert result.used_transcribe_jobs == 3
        assert result.remaining_transcribe_jobs == 7
        assert result.period_start == "2026-09-01T00:00:00+00:00"
        assert result.reset_at == "2026-10-01T00:00:00+00:00"
        assert result.retrieved_at == "2026-09-24T10:00:00+00:00"

    def test_transcribe_disabled_nulls(self, mocker) -> None:
        """Transcribe 無効ユーザーの null 項目が None として保持される."""
        body = dict(_VALID_BODY)
        body["monthly_transcribe_job_limit"] = None
        body["used_transcribe_jobs"] = None
        body["remaining_transcribe_jobs"] = None
        _patch_boto_layers(mocker, status_code=200, body=json.dumps(body))

        result = usage_client.fetch_usage(_settings_with_endpoint())

        assert result.error is None
        assert result.remaining_tokens == 498500
        assert result.monthly_transcribe_job_limit is None
        assert result.used_transcribe_jobs is None
        assert result.remaining_transcribe_jobs is None

    def test_uses_sigv4_signing(self, mocker) -> None:
        """SigV4 署名が 'execute-api' サービスに対して行われる."""
        _patch_boto_layers(mocker, status_code=200)
        sigv4 = mocker.patch("botocore.auth.SigV4Auth")

        usage_client.fetch_usage(_settings_with_endpoint())

        # SigV4Auth の第 2 引数（サービス名）が 'execute-api' であること。
        assert sigv4.call_args is not None
        args = sigv4.call_args.args
        assert args[1] == "execute-api"


# ---------------------------------------------------------------------------
# (c) 非 200 / 例外
# ---------------------------------------------------------------------------


class TestFailureFetch:
    """非 200 応答・例外時のテスト."""

    def test_non_200_returns_error(self, mocker) -> None:
        """非 200 応答 → error 付き UsageInfo を返し例外を送出しない."""
        _patch_boto_layers(mocker, status_code=403, body="Forbidden")

        result = usage_client.fetch_usage(_settings_with_endpoint())

        assert result.error is not None
        assert result.remaining_tokens is None

    def test_exception_during_send_returns_error(self, mocker) -> None:
        """送信中の例外 → error 付き UsageInfo を返し例外を送出しない."""
        mocker.patch(
            "screen_audio_recorder.aws_utils.is_boto3_available", return_value=True
        )
        fake_session = mocker.MagicMock()
        fake_session.get_credentials.side_effect = RuntimeError("boom")
        mocker.patch(
            "screen_audio_recorder.aws_utils.create_boto3_session",
            return_value=fake_session,
        )

        result = usage_client.fetch_usage(_settings_with_endpoint())

        assert result.error is not None

    def test_invalid_json_returns_error(self, mocker) -> None:
        """不正な JSON 本文 → error 付き UsageInfo を返す."""
        _patch_boto_layers(mocker, status_code=200, body="not-json")

        result = usage_client.fetch_usage(_settings_with_endpoint())

        assert result.error is not None

    def test_boto3_unavailable_returns_error(self, mocker) -> None:
        """boto3 未導入 → error 付き UsageInfo を返す."""
        mocker.patch(
            "screen_audio_recorder.aws_utils.is_boto3_available", return_value=False
        )

        result = usage_client.fetch_usage(_settings_with_endpoint())

        assert result.error is not None
        assert result.remaining_tokens is None

    def test_no_credentials_returns_error(self, mocker) -> None:
        """認証情報が None → error 付き UsageInfo を返す."""
        mocker.patch(
            "screen_audio_recorder.aws_utils.is_boto3_available", return_value=True
        )
        fake_session = mocker.MagicMock()
        fake_session.get_credentials.return_value = None
        mocker.patch(
            "screen_audio_recorder.aws_utils.create_boto3_session",
            return_value=fake_session,
        )

        result = usage_client.fetch_usage(_settings_with_endpoint())

        assert result.error is not None
