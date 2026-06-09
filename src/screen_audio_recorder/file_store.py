"""FileStore: 録画ファイルの出力先管理モジュール."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


class FileStore:
    """録画ファイルの保存先ディレクトリとファイル名を管理するクラス.

    すべての出力ファイルは ``~/.screen-audio-recorder/recordings/`` 配下に保存される。
    ディレクトリが存在しない場合は自動的に作成される。

    要件 1.3: ユーザーのホームディレクトリ配下にのみファイルを書き込む。
    要件 8.2: メモをローカルファイルシステム上のユーザーホームディレクトリ配下に保存する。
    """

    _RELATIVE_DIR = Path("Documents") / "screen-audio-recorder" / "recordings"

    def __init__(self) -> None:
        """FileStore を初期化し、録画ディレクトリを自動作成する."""
        self._base_dir = Path.home() / self._RELATIVE_DIR
        self._base_dir.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        """録画ファイルの保存先ディレクトリを返す.

        Returns:
            ``~/.screen-audio-recorder/recordings/`` の絶対パス
        """
        return self._base_dir

    def get_output_path(self, extension: str) -> Path:
        """タイムスタンプベースの出力ファイルパスを生成して返す.

        ファイル名形式: ``YYYY-MM-DD_HH-MM-SS.<extension>``
        例: ``2024-01-15_10-30-00.mp4``

        生成されるパスは必ず ``pathlib.Path.home()`` 配下であることを保証する。

        Args:
            extension: ファイル拡張子（例: ``"mp4"``, ``"mp3"``, ``"wav"``）。
                       先頭のドットは省略可（``"mp4"`` と ``".mp4"`` は同一）。

        Returns:
            タイムスタンプベースの出力ファイルの絶対パス

        Raises:
            ValueError: 生成されたパスが ``Path.home()`` 配下でない場合
        """
        # 先頭のドットを正規化
        ext = extension.lstrip(".")
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{timestamp}.{ext}"
        output_path = self._base_dir / filename

        # 書き込みパスが Path.home() 配下であることを保証する
        home = Path.home()
        try:
            output_path.relative_to(home)
        except ValueError as exc:
            raise ValueError(
                f"出力パス {output_path!r} が Path.home() ({home!r}) 配下にありません。"
            ) from exc

        return output_path
