"""llm_settings_store の AWS 設定永続化テスト.

特に ADR-006 で追加した ``usage_api_endpoint`` の保存・読み込み往復と、
旧形式 JSON（``usage_api_endpoint`` 無し）からの後方互換読み込みを検証する。
Windows 専用依存や tkinter を import しない構成とする。
"""

from __future__ import annotations

import json

from screen_audio_recorder.llm_settings_store import (
    _aws_settings_to_dict,
    _dict_to_aws_settings,
    load_all_settings,
    save_all_settings,
)
from screen_audio_recorder.models import (
    AwsAuthMethod,
    AwsSettings,
    LlmSettings,
    TranscriberSettings,
)


class TestUsageApiEndpointRoundTrip:
    """usage_api_endpoint の save→load 往復テスト."""

    def test_dict_round_trip(self) -> None:
        """辞書変換の往復で usage_api_endpoint が保持される."""
        url = "https://abc123.execute-api.ap-northeast-1.amazonaws.com/prod/usage"
        original = AwsSettings(usage_api_endpoint=url)
        restored = _dict_to_aws_settings(_aws_settings_to_dict(original))
        assert restored.usage_api_endpoint == url

    def test_dict_contains_endpoint_key(self) -> None:
        """辞書化した結果に usage_api_endpoint キーが含まれる."""
        data = _aws_settings_to_dict(AwsSettings(usage_api_endpoint="https://x/usage"))
        assert data["usage_api_endpoint"] == "https://x/usage"

    def test_file_round_trip(self, tmp_path) -> None:
        """設定ファイルへの保存→読み込みで usage_api_endpoint が保持される."""
        url = "https://file.execute-api.ap-northeast-1.amazonaws.com/prod/usage"
        aws_settings = AwsSettings(
            auth_method=AwsAuthMethod.ACCESS_KEY,
            region="ap-northeast-1",
            usage_api_endpoint=url,
        )
        path = tmp_path / "llm_settings.json"

        save_all_settings(
            LlmSettings(),
            TranscriberSettings(),
            aws_settings,
            path=path,
        )

        _, _, loaded_aws = load_all_settings(path=path)
        assert loaded_aws.usage_api_endpoint == url
        assert loaded_aws.auth_method == AwsAuthMethod.ACCESS_KEY


class TestBackwardCompatibility:
    """旧形式 JSON（usage_api_endpoint 無し）からの後方互換読み込みテスト."""

    def test_dict_without_endpoint_defaults_empty(self) -> None:
        """usage_api_endpoint キーが無い辞書はデフォルト空文字で読める."""
        legacy = {
            "auth_method": "profile",
            "region": "ap-northeast-1",
            "profile_name": "",
            "access_key_id": "",
            "secret_access_key": "",
            "session_token": "",
        }
        restored = _dict_to_aws_settings(legacy)
        assert restored.usage_api_endpoint == ""

    def test_legacy_file_loads_with_empty_endpoint(self, tmp_path) -> None:
        """旧形式の設定ファイルでも usage_api_endpoint は空文字で読める."""
        path = tmp_path / "llm_settings.json"
        legacy_data = {
            "backend": "local",
            "aws": {
                "auth_method": "profile",
                "region": "ap-northeast-1",
            },
        }
        path.write_text(json.dumps(legacy_data), encoding="utf-8")

        _, _, loaded_aws = load_all_settings(path=path)
        assert loaded_aws.usage_api_endpoint == ""
        assert loaded_aws.region == "ap-northeast-1"
