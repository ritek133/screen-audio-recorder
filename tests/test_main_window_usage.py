"""MainWindow の残存容量表示ロジックのテスト（ADR-006 案B）.

tkinter / DISPLAY が使えない環境ではスキップする（既存 test_memo_list_view.py の
取り扱いに倣う）。tkinter を実際に生成せず、_apply_usage / refresh_usage の
状態遷移を StringVar 相当のスタブで検証する。
"""

from __future__ import annotations

import pytest

# tkinter が import できない/DISPLAY が無い環境ではスキップする。
tk = pytest.importorskip("tkinter")

try:
    _root_probe = tk.Tk()
    _root_probe.destroy()
    _TK_AVAILABLE = True
except Exception:
    _TK_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _TK_AVAILABLE, reason="tkinter/DISPLAY が利用できないためスキップ"
)

from screen_audio_recorder.gui.main_window import MainWindow  # noqa: E402
from screen_audio_recorder.models import AwsSettings, UsageInfo  # noqa: E402


class _FakeVar:
    """tkinter.StringVar の最小スタブ."""

    def __init__(self, value: str = "") -> None:
        self._value = value

    def set(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value


def _make_window_stub(aws_settings=None) -> MainWindow:
    """tkinter を生成せずに MainWindow の残量表示に必要な最小状態を組み立てる."""
    win = object.__new__(MainWindow)
    win._aws_settings = aws_settings
    # 残存容量はメイン下部のステータス欄に 1 行で表示する（単一の StringVar）。
    win._usage_status_var = _FakeVar()

    # root.after を即時実行するスタブに差し替える。
    class _FakeRoot:
        def after(self, _delay, func):
            func()

    win._root = _FakeRoot()
    return win


class TestApplyUsage:
    """_apply_usage の表示反映テスト."""

    def test_success_updates_labels(self) -> None:
        """正常な UsageInfo で残量・上限・リセットが表示される."""
        win = _make_window_stub()
        usage = UsageInfo(
            daily_token_limit=500000,
            remaining_tokens=498500,
            daily_transcribe_job_limit=10,
            remaining_transcribe_jobs=7,
            reset_at="2026-09-25T00:00:00+00:00",
        )
        win._apply_usage(usage)

        status = win._usage_status_var.get()
        assert "498500" in status
        assert "500000" in status
        assert "7" in status
        assert "2026-09-25" in status

    def test_error_shows_fallback(self) -> None:
        """error 付き UsageInfo は『取得できませんでした』表示になる."""
        win = _make_window_stub()
        win._apply_usage(UsageInfo(error="失敗"))

        assert "取得できませんでした" in win._usage_status_var.get()

    def test_transcribe_disabled_shows_out_of_scope(self) -> None:
        """Transcribe 無効ユーザーは残文字起こしが『対象外』になる."""
        win = _make_window_stub()
        usage = UsageInfo(
            daily_token_limit=500000,
            remaining_tokens=100,
            remaining_transcribe_jobs=None,
        )
        win._apply_usage(usage)

        assert "対象外" in win._usage_status_var.get()


class TestRefreshUsage:
    """refresh_usage の分岐テスト."""

    def test_unset_endpoint_shows_not_configured(self) -> None:
        """エンドポイント未設定時は『未設定』表示にとどまる（取得しない）."""
        win = _make_window_stub(aws_settings=AwsSettings(usage_api_endpoint=""))
        win.refresh_usage()

        assert "未設定" in win._usage_status_var.get()

    def test_none_aws_settings_shows_not_configured(self) -> None:
        """aws_settings が None のときも未設定表示."""
        win = _make_window_stub(aws_settings=None)
        win.refresh_usage()

        assert "未設定" in win._usage_status_var.get()

    def test_on_memo_saved_triggers_refresh_usage(self, mocker) -> None:
        """文字起こし・LLM 要約完了時（_on_memo_saved）に refresh_usage が呼ばれる.

        recorder_controller は「文字起こし→LLM 要約→メモ保存」完了後に
        _on_memo_saved を GUI スレッドで 1 回呼ぶ。ここで残量を再取得することで
        「文字起こし・LLM 要約時」の自動更新を実現する。実装を revert すると
        refresh_usage が呼ばれなくなり、このテストは失敗する。
        """
        win = _make_window_stub()
        win._memo_list_view = mocker.Mock()
        win._status_var = _FakeVar()
        refresh_spy = mocker.patch.object(win, "refresh_usage")

        win._on_memo_saved()

        refresh_spy.assert_called_once()
        # メモ一覧更新など既存挙動も維持されていること。
        win._memo_list_view.refresh.assert_called_once()

    def test_background_fetch_updates_labels(self, mocker) -> None:
        """バックグラウンド取得完了で StringVar が更新される（fetch をモック）."""
        aws_settings = AwsSettings(
            usage_api_endpoint="https://x.execute-api.ap-northeast-1.amazonaws.com/prod/usage"
        )
        win = _make_window_stub(aws_settings=aws_settings)

        usage = UsageInfo(
            daily_token_limit=500000,
            remaining_tokens=498500,
            remaining_transcribe_jobs=None,
            reset_at="2026-09-25T00:00:00+00:00",
        )
        mocker.patch(
            "screen_audio_recorder.usage_client.fetch_usage", return_value=usage
        )

        win.refresh_usage()

        # daemon スレッドの完了を待つ。
        import time

        for _ in range(50):
            if "498500" in win._usage_status_var.get():
                break
            time.sleep(0.02)

        assert "498500" in win._usage_status_var.get()
