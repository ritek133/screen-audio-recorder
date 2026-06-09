"""MemoStore: メモの永続化管理モジュール.

メモデータを ``~/.screen-audio-recorder/memos.json`` に JSON 形式で保存・管理する。
``filelock`` ライブラリによる排他制御で並行アクセスを安全に処理する。
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from screen_audio_recorder.models import Memo, MemoPage

# JSON スキーマバージョン
_SCHEMA_VERSION = 1

# データファイルのデフォルトパス（ホームディレクトリ相対）
_RELATIVE_DATA_DIR = Path("Documents") / "screen-audio-recorder"
_DATA_FILENAME = "memos.json"


class MemoStore:
    """メモの作成・取得・削除を管理するクラス.

    データは ``~/.screen-audio-recorder/memos.json`` に JSON 形式で永続化される。
    ``filelock`` による排他制御で複数プロセスからの同時アクセスを安全に処理する。

    JSON スキーマ::

        {
            "version": 1,
            "memos": [
                {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "created_at": "2024-01-15T10:30:00Z",
                    "theme": "会議メモ",
                    "body": "本日の会議では...",
                    "output_file": "/path/to/recording.mp4"
                }
            ]
        }

    要件 8.1: メモを作成日時・テーマ・本文・OutputFile パスとともに保存する。
    要件 8.2: メモをローカルファイルシステム上のユーザーホームディレクトリ配下に保存する。
    要件 8.3: 保存済みメモを削除する機能を提供する。
    要件 9.1: 保存済みの全メモを作成日時の降順で返す。
    要件 9.5: 表示件数が 100 件を超えた場合にページネーションを適用する。
    """

    def __init__(self, data_path: Path | None = None) -> None:
        """MemoStore を初期化する.

        Args:
            data_path: データファイルのパス。省略時は
                ``~/.screen-audio-recorder/memos.json`` を使用する。
        """
        if data_path is None:
            data_path = Path.home() / _RELATIVE_DATA_DIR / _DATA_FILENAME

        self._data_path = data_path
        self._lock_path = data_path.with_suffix(".json.lock")

        # データディレクトリを自動作成
        self._data_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def data_path(self) -> Path:
        """データファイルのパスを返す."""
        return self._data_path

    # ------------------------------------------------------------------
    # パブリック API
    # ------------------------------------------------------------------

    def create(self, text: str, theme: str, output_file: Path, summary: str = "") -> Memo:
        """メモを作成し保存する.

        UUID4 で一意な ID を生成し、UTC タイムスタンプを付与してメモを作成する。

        Args:
            text: 文字起こし全文（メモの本文）
            theme: メモのテーマ（10 文字以内を推奨）
            output_file: 対応する録画・録音ファイルの絶対パス
            summary: 内容要約（デフォルト: 空文字列）

        Returns:
            作成された Memo オブジェクト

        要件 8.1: メモを作成日時・テーマ・本文・OutputFile パスとともに保存する。
        """
        memo = Memo(
            id=str(uuid.uuid4()),
            created_at=datetime.now(tz=timezone.utc),
            theme=theme,
            body=text,
            summary=summary,
            output_file=output_file,
        )

        with FileLock(str(self._lock_path)):
            data = self._load_raw()
            data["memos"].append(_memo_to_dict(memo))
            self._save_raw(data)

        return memo

    def get_all(self, page: int = 1, page_size: int = 50) -> MemoPage:
        """メモを作成日時の降順でページネーション付きで返す.

        Args:
            page: ページ番号（1 始まり）
            page_size: 1 ページあたりの件数（デフォルト 50）

        Returns:
            ページネーション情報付きの MemoPage オブジェクト

        要件 9.1: 保存済みの全メモを作成日時の降順で返す。
        要件 9.5: 表示件数が 100 件を超えた場合にページネーションを適用する。
        """
        with FileLock(str(self._lock_path)):
            data = self._load_raw()

        all_memos = [_dict_to_memo(d) for d in data["memos"]]

        # 作成日時の降順でソート
        all_memos.sort(key=lambda m: m.created_at, reverse=True)

        total = len(all_memos)
        total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 1

        # ページ番号を有効範囲にクランプ
        page = max(1, min(page, total_pages))

        start = (page - 1) * page_size
        end = start + page_size
        page_memos = all_memos[start:end]

        return MemoPage(
            memos=page_memos,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def get_by_id(self, memo_id: str) -> Memo | None:
        """ID でメモを取得する.

        Args:
            memo_id: 検索するメモの UUID 文字列

        Returns:
            見つかった場合は Memo オブジェクト、見つからない場合は None

        要件 8.1: 保存済みメモを ID で取得できる。
        """
        with FileLock(str(self._lock_path)):
            data = self._load_raw()

        for d in data["memos"]:
            if d["id"] == memo_id:
                return _dict_to_memo(d)
        return None

    def delete(self, memo_id: str) -> None:
        """メモを削除する."""
        with FileLock(str(self._lock_path)):
            data = self._load_raw()
            original_count = len(data["memos"])
            data["memos"] = [d for d in data["memos"] if d["id"] != memo_id]
            if len(data["memos"]) != original_count:
                self._save_raw(data)

    def update_theme(self, memo_id: str, new_theme: str) -> None:
        """メモのテーマを更新する.

        Args:
            memo_id: 更新するメモの UUID 文字列
            new_theme: 新しいテーマ文字列
        """
        with FileLock(str(self._lock_path)):
            data = self._load_raw()
            for d in data["memos"]:
                if d["id"] == memo_id:
                    d["theme"] = new_theme
                    self._save_raw(data)
                    return

    def update_memo(self, memo_id: str, body: str, theme: str, summary: str) -> None:
        """メモの本文・テーマ・要約を更新する.

        Args:
            memo_id: 更新するメモの UUID 文字列
            body: 新しい本文
            theme: 新しいテーマ
            summary: 新しい要約
        """
        with FileLock(str(self._lock_path)):
            data = self._load_raw()
            for d in data["memos"]:
                if d["id"] == memo_id:
                    d["body"] = body
                    d["theme"] = theme
                    d["summary"] = summary
                    self._save_raw(data)
                    return

    # ------------------------------------------------------------------
    # プライベートヘルパー
    # ------------------------------------------------------------------

    def _load_raw(self) -> dict:
        """JSON ファイルを読み込んで辞書として返す.

        ファイルが存在しない場合は空のデータ構造を返す。
        ファイルが壊れている場合は空のデータ構造で上書きする。

        Returns:
            ``{"version": 1, "memos": [...]}`` 形式の辞書
        """
        if not self._data_path.exists():
            return {"version": _SCHEMA_VERSION, "memos": []}

        try:
            text = self._data_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (json.JSONDecodeError, OSError):
            # ファイルが壊れている場合は空データで初期化
            return {"version": _SCHEMA_VERSION, "memos": []}

        # スキーマバージョンチェック（将来のマイグレーション用）
        if not isinstance(data, dict) or "memos" not in data:
            return {"version": _SCHEMA_VERSION, "memos": []}

        return data

    def _save_raw(self, data: dict) -> None:
        """辞書を JSON ファイルに書き込む.

        Args:
            data: ``{"version": 1, "memos": [...]}`` 形式の辞書
        """
        text = json.dumps(data, ensure_ascii=False, indent=2)
        self._data_path.write_text(text, encoding="utf-8")


# ------------------------------------------------------------------
# シリアライズ / デシリアライズ ヘルパー
# ------------------------------------------------------------------


def _memo_to_dict(memo: Memo) -> dict:
    """Memo オブジェクトを JSON シリアライズ可能な辞書に変換する.

    ``created_at`` は ISO 8601 形式（末尾 ``Z``）の UTC 文字列に変換する。
    ``output_file`` は文字列に変換する。

    Args:
        memo: 変換する Memo オブジェクト

    Returns:
        JSON シリアライズ可能な辞書
    """
    # UTC に変換して ISO 8601 形式（末尾 Z）にフォーマット
    dt = memo.created_at
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    created_at_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "id": memo.id,
        "created_at": created_at_str,
        "theme": memo.theme,
        "body": memo.body,
        "summary": memo.summary,
        "output_file": str(memo.output_file),
    }


def _dict_to_memo(d: dict) -> Memo:
    """辞書を Memo オブジェクトに変換する.

    ``created_at`` は ISO 8601 形式の文字列から UTC datetime に変換する。
    ``output_file`` は Path オブジェクトに変換する。

    Args:
        d: JSON から読み込んだ辞書

    Returns:
        Memo オブジェクト
    """
    created_at_str: str = d["created_at"]

    # "Z" サフィックスを "+00:00" に置換して fromisoformat で解析
    if created_at_str.endswith("Z"):
        created_at_str = created_at_str[:-1] + "+00:00"

    created_at = datetime.fromisoformat(created_at_str)

    # タイムゾーン情報がない場合は UTC として扱う
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return Memo(
        id=d["id"],
        created_at=created_at,
        theme=d["theme"],
        body=d["body"],
        summary=d.get("summary", ""),
        output_file=Path(d["output_file"]),
    )
