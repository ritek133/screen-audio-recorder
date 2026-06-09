"""pytest 設定ファイル: src ディレクトリをパスに追加する."""

import sys
from pathlib import Path

# src ディレクトリをモジュール検索パスに追加
sys.path.insert(0, str(Path(__file__).parent / "src"))
