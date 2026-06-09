"""LlmClient: ローカル LLM またはオンプレ API 経由でテキスト生成を行うクライアント.

ローカルモード: ``llama-server`` (llama.cpp) をサブプロセスとして起動し、
OpenAI 互換 API 経由で推論する。pip install 不要、PyInstaller 互換。
API モード: 外部の OpenAI 互換 API に標準ライブラリで POST。

**Validates: Requirements 10.4, 10.5**
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from screen_audio_recorder.models import LlmBackend, LlmSettings

logger = logging.getLogger(__name__)

# llama-server のローカルポート
_LOCAL_SERVER_PORT = 18088
_LOCAL_SERVER_HOST = "127.0.0.1"
_LOCAL_ENDPOINT = f"http://{_LOCAL_SERVER_HOST}:{_LOCAL_SERVER_PORT}/v1/chat/completions"
_LOCAL_HEALTH = f"http://{_LOCAL_SERVER_HOST}:{_LOCAL_SERVER_PORT}/health"

# llama-server の起動タイムアウト（秒）
_SERVER_START_TIMEOUT = 120


def _find_llama_server() -> str | None:
    """llama-server 実行ファイルのパスを探す.

    検索順序:
        1. _internal/llama-server.exe（PyInstaller バンドル）
        2. アプリデータディレクトリ ~/Documents/screen-audio-recorder/bin/llama-server.exe
        3. PATH 上の llama-server
    """
    # 1. PyInstaller バンドル内
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "llama-server.exe"
        if bundled.exists():
            return str(bundled)
        # --onedir モードの場合
        bundled = Path(sys.executable).parent / "_internal" / "llama-server.exe"
        if bundled.exists():
            return str(bundled)

    # プロジェクトルートの _internal/
    project_internal = Path(__file__).parent.parent.parent / "_internal" / "llama-server.exe"
    if project_internal.exists():
        return str(project_internal)

    # 2. アプリデータディレクトリ
    app_bin = Path.home() / "Documents" / "screen-audio-recorder" / "bin" / "llama-server.exe"
    if app_bin.exists():
        return str(app_bin)

    # 3. PATH 上
    import shutil
    found = shutil.which("llama-server")
    if found:
        return found

    return None


class LlmClient:
    """ローカル LLM またはオンプレ API 経由でテキスト生成を行うクライアント.

    ローカルモードでは llama-server をサブプロセスとして起動し、
    OpenAI 互換 API（localhost）経由で推論する。
    API モードでは外部エンドポイントに直接 POST する。

    Attributes:
        _settings: 現在の LLM 設定
        _server_process: ローカルモード時の llama-server プロセス
        _available: LLM が利用可能かどうか
        _endpoint: 推論に使用する API エンドポイント URL
    """

    def __init__(self, settings: LlmSettings) -> None:
        self._settings = settings
        self._server_process: subprocess.Popen | None = None
        self._available = False
        self._endpoint: str = ""
        self._initialize()

    def _initialize(self) -> None:
        """設定に基づいてクライアントを初期化する."""
        self._stop_server()
        self._available = False
        self._endpoint = ""

        if self._settings.backend == LlmBackend.LOCAL:
            self._init_local()
        else:
            self._init_api()

    def _init_local(self) -> None:
        """ローカル llama-server を起動する."""
        model_path = self._settings.local_model_path
        if not model_path:
            logger.warning(
                "ローカルモデルのパスが設定されていません。"
                "LLM 設定タブで GGUF モデルファイルを指定するか、"
                "「モデルをダウンロード」ボタンでモデルを取得してください。"
            )
            return

        if not os.path.isfile(model_path):
            logger.error("指定されたモデルファイルが見つかりません: %s", model_path)
            return

        server_path = _find_llama_server()
        if server_path is None:
            logger.warning(
                "llama-server が見つかりません。"
                "LLM 設定タブの「llama-server をダウンロード」ボタンで取得するか、"
                "_internal/llama-server.exe に配置してください。"
            )
            return

        try:
            logger.info(
                "llama-server を起動中: %s (モデル: %s, ポート: %d)",
                server_path, model_path, _LOCAL_SERVER_PORT,
            )
            # CREATE_NO_WINDOW でコンソールウィンドウを非表示にする
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            # llama-server と同じディレクトリにある DLL を見つけられるよう
            # PATH に追加する（Visual C++ ランタイム等）
            env = os.environ.copy()
            server_dir = os.path.dirname(server_path)
            env["PATH"] = server_dir + os.pathsep + env.get("PATH", "")

            self._server_process = subprocess.Popen(
                [
                    server_path,
                    "--model", model_path,
                    "--host", _LOCAL_SERVER_HOST,
                    "--port", str(_LOCAL_SERVER_PORT),
                    "--ctx-size", str(self._settings.ctx_size),
                    "--threads", "4",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
                env=env,
            )

            # サーバーの起動を待つ
            if self._wait_for_server():
                self._available = True
                self._endpoint = _LOCAL_ENDPOINT
                logger.info("llama-server が起動しました（PID: %d）", self._server_process.pid)
            else:
                # 失敗時に stderr を読み取ってログに出力
                self._log_server_output()
                logger.error("llama-server の起動がタイムアウトしました。")
                self._stop_server()

        except Exception as exc:
            logger.error("llama-server の起動に失敗しました: %s", exc)
            self._stop_server()

    def _log_server_output(self) -> None:
        """llama-server の stdout/stderr をログに出力する."""
        if self._server_process is None:
            return
        try:
            # 非ブロッキングで読み取り（プロセスが終了している場合のみ）
            if self._server_process.poll() is not None:
                stdout, stderr = self._server_process.communicate(timeout=5)
            else:
                stdout = b""
                stderr = b""
                # PIPE から読めるだけ読む
                try:
                    import selectors
                except ImportError:
                    return

            if stdout:
                for line in stdout.decode("utf-8", errors="replace").strip().splitlines()[:20]:
                    logger.debug("llama-server stdout: %s", line)
            if stderr:
                for line in stderr.decode("utf-8", errors="replace").strip().splitlines()[:20]:
                    logger.error("llama-server stderr: %s", line)
        except Exception as exc:
            logger.debug("llama-server 出力の読み取りに失敗: %s", exc)

    def _wait_for_server(self) -> bool:
        """llama-server の起動完了を待つ."""
        start = time.monotonic()
        while time.monotonic() - start < _SERVER_START_TIMEOUT:
            # プロセスが終了していないか確認
            if self._server_process is not None and self._server_process.poll() is not None:
                rc = self._server_process.returncode
                # 終了コードを分かりやすく表示
                if rc == 0xC0000135 or rc == -1073741515:
                    logger.error(
                        "llama-server が DLL 不足で異常終了しました（終了コード: %d / 0x%X）。"
                        "llama-server.exe と同じフォルダに必要な DLL が揃っているか確認してください。"
                        "Visual C++ 再頒布可能パッケージのインストールも試してください。",
                        rc, rc & 0xFFFFFFFF,
                    )
                else:
                    logger.error(
                        "llama-server が異常終了しました（終了コード: %d）",
                        rc,
                    )
                self._log_server_output()
                return False

            try:
                req = urllib.request.Request(_LOCAL_HEALTH, method="GET")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    body = resp.read().decode("utf-8")
                    # llama-server の /health は {"status":"ok"} を返す
                    if "ok" in body.lower():
                        return True
                    # モデルロード中の場合は "loading model" が返る
                    logger.debug("llama-server 応答: %s", body)
            except (urllib.error.URLError, OSError):
                pass

            time.sleep(1.0)

        return False

    def _stop_server(self) -> None:
        """llama-server プロセスを停止する."""
        if self._server_process is not None:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=5)
                logger.info("llama-server を停止しました。")
            except Exception:
                try:
                    self._server_process.kill()
                except Exception:
                    pass
            self._server_process = None

    def _init_api(self) -> None:
        """API モードを初期化する."""
        endpoint = self._settings.api_endpoint
        if not endpoint:
            logger.warning("API エンドポイントが設定されていません。")
            return

        self._endpoint = endpoint
        self._available = True
        logger.info("API モードで初期化しました。エンドポイント: %s", endpoint)

    @property
    def available(self) -> bool:
        """LLM が利用可能かどうかを返す."""
        return self._available

    def reload(self, settings: LlmSettings) -> None:
        """設定変更時にクライアントを再初期化する."""
        self._settings = settings
        self._initialize()

    def shutdown(self) -> None:
        """クライアントをシャットダウンし、ローカルサーバーを停止する."""
        self._stop_server()
        self._available = False

    def generate(self, prompt: str) -> str | None:
        """プロンプトを送信してテキストを生成する.

        ローカルモード・API モードともに OpenAI 互換 API で通信する。
        """
        if not self._available or not self._endpoint:
            return None

        return self._call_api(prompt)

    def _call_api(self, prompt: str) -> str | None:
        """OpenAI 互換 API でテキスト生成する."""
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": "あなたは日本語のテキスト処理アシスタントです。必ず日本語で回答してください。",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self._settings.max_tokens,
            "temperature": self._settings.temperature,
        }

        headers = {"Content-Type": "application/json"}
        if self._settings.api_key:
            headers["Authorization"] = f"Bearer {self._settings.api_key}"

        try:
            data = json.dumps(payload).encode("utf-8")
            logger.debug(
                "API リクエスト送信: endpoint=%s, payload_size=%d bytes, prompt_len=%d chars",
                self._endpoint, len(data), len(prompt),
            )
            req = urllib.request.Request(
                self._endpoint,
                data=data,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._settings.timeout_seconds) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            choices = body.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
            return None
        except urllib.error.HTTPError as exc:
            # 400 等の HTTP エラー時にレスポンスボディを読んで原因を特定する
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            logger.error(
                "API 推論 HTTP エラー: status=%d, reason=%s, body=%s, prompt_len=%d chars",
                exc.code, exc.reason, error_body[:500], len(prompt),
            )
            return None
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            logger.error("API 推論に失敗しました: %s", exc)
            return None
        except Exception as exc:
            logger.error("API 推論で予期しないエラーが発生しました: %s", exc)
            return None
