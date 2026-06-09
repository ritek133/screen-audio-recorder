"""llama-server バイナリを自動ダウンロードするスクリプト.

llama.cpp の公式リリースから Windows 用 llama-server.exe をダウンロードし、
_internal/llama-server.exe に配置する。

使い方:
    python scripts/download_llama_server.py
"""

from __future__ import annotations

import io
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

# llama.cpp GitHub リリース API
_RELEASES_API = "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"

# 出力先
_OUTPUT_DIR = Path(__file__).parent.parent / "_internal"
_OUTPUT_PATH = _OUTPUT_DIR / "llama-server.exe"

# アプリデータディレクトリ（GUI からのダウンロード用）
_APP_BIN_DIR = Path.home() / "Documents" / "screen-audio-recorder" / "bin"
_APP_OUTPUT_PATH = _APP_BIN_DIR / "llama-server.exe"


def _get_latest_release_url() -> str:
    """最新リリースから Windows 用 zip の URL を取得する."""
    req = urllib.request.Request(
        _RELEASES_API,
        headers={"User-Agent": "screen-audio-recorder"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    for asset in data.get("assets", []):
        name = asset["name"].lower()
        # Windows x64 用のバイナリを探す（CUDA なし版）
        if "win" in name and "x64" in name and "vulkan" not in name and "cuda" not in name and name.endswith(".zip"):
            return asset["browser_download_url"]

    # フォールバック: win を含む最初の zip
    for asset in data.get("assets", []):
        name = asset["name"].lower()
        if "win" in name and name.endswith(".zip"):
            return asset["browser_download_url"]

    raise RuntimeError("Windows 用の llama.cpp リリースが見つかりません")


def download_llama_server(dest_dir: Path | None = None) -> Path:
    """llama-server.exe をダウンロードして配置する.

    Args:
        dest_dir: 出力先ディレクトリ。None の場合は _internal/ に配置。

    Returns:
        llama-server.exe の絶対パス
    """
    if dest_dir is None:
        dest_dir = _OUTPUT_DIR
    output_path = dest_dir / "llama-server.exe"

    if output_path.exists():
        print(f"llama-server.exe は既に存在します: {output_path}")
        return output_path

    dest_dir.mkdir(parents=True, exist_ok=True)

    print("最新リリース情報を取得中...")
    url = _get_latest_release_url()
    print(f"ダウンロード中: {url}")
    print("（数分かかる場合があります）")

    req = urllib.request.Request(url, headers={"User-Agent": "screen-audio-recorder"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = resp.read()

    print("ダウンロード完了。展開中...")

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # zip 内の llama-server.exe を探す
        server_entry = None
        for name in zf.namelist():
            basename = name.rsplit("/", 1)[-1] if "/" in name else name
            if basename == "llama-server.exe":
                server_entry = name
                break

        if server_entry is None:
            raise FileNotFoundError(
                "zip 内に llama-server.exe が見つかりません。"
                f"zip の内容: {zf.namelist()[:20]}"
            )

        # llama-server.exe と同じディレクトリにある全ファイルを展開（DLL が必要）
        server_dir = server_entry.rsplit("/", 1)[0] + "/" if "/" in server_entry else ""
        extracted = []
        for name in zf.namelist():
            if not name.startswith(server_dir):
                continue
            basename = name[len(server_dir):]
            if not basename or "/" in basename:
                continue
            target = dest_dir / basename
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(basename)

        if "llama-server.exe" not in extracted:
            raise FileNotFoundError("llama-server.exe の展開に失敗しました")

    print(f"llama-server.exe + DLL を配置しました: {output_path}")
    print(f"展開ファイル数: {len(extracted)}")
    return output_path


def download_to_app_dir() -> Path:
    """アプリデータディレクトリにダウンロードする（GUI 用）."""
    return download_llama_server(dest_dir=_APP_BIN_DIR)


if __name__ == "__main__":
    download_llama_server()
