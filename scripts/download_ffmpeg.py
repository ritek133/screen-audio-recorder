"""ffmpeg バイナリを自動ダウンロードするスクリプト.

gyan.dev から Windows 用 ffmpeg essentials ビルドをダウンロードし、
_internal/ffmpeg.exe に配置する。

使い方:
    python scripts/download_ffmpeg.py
"""

from __future__ import annotations

import io
import shutil
import urllib.request
import zipfile
from pathlib import Path

# ダウンロード URL（gyan.dev の essentials ビルド、軽量版）
_FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# 出力先
_OUTPUT_DIR = Path(__file__).parent.parent / "_internal"
_OUTPUT_PATH = _OUTPUT_DIR / "ffmpeg.exe"


def download_ffmpeg() -> Path:
    """ffmpeg.exe をダウンロードして _internal/ に配置する.

    Returns:
        ffmpeg.exe の絶対パス
    """
    if _OUTPUT_PATH.exists():
        print(f"ffmpeg.exe は既に存在します: {_OUTPUT_PATH}")
        return _OUTPUT_PATH

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"ffmpeg をダウンロード中: {_FFMPEG_URL}")
    print("（約 80MB、数分かかる場合があります）")

    req = urllib.request.Request(_FFMPEG_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = resp.read()

    print("ダウンロード完了。展開中...")

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # zip 内の ffmpeg.exe を探す
        ffmpeg_entry = None
        for name in zf.namelist():
            if name.endswith("bin/ffmpeg.exe"):
                ffmpeg_entry = name
                break

        if ffmpeg_entry is None:
            raise FileNotFoundError("zip 内に ffmpeg.exe が見つかりません")

        # ffmpeg.exe を抽出
        with zf.open(ffmpeg_entry) as src, open(_OUTPUT_PATH, "wb") as dst:
            shutil.copyfileobj(src, dst)

    print(f"ffmpeg.exe を配置しました: {_OUTPUT_PATH}")
    return _OUTPUT_PATH


if __name__ == "__main__":
    download_ffmpeg()
