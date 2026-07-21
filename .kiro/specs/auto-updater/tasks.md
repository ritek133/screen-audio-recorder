# Implementation Plan: Auto-Updater

## Overview

GitHub Releases ベースの自動更新機能を実装する。ハイブリッド配布方式（exe 単体 / zip フル更新）、ダウンロード進捗表示、ロールバック機能を含む。

## Tasks

- [x] 1. データモデルと例外クラスの実装
  - `src/screen_audio_recorder/updater_models.py` を作成する
  - `Version` データクラス（major, minor, patch、`__lt__`, `__eq__`, `__str__`）を実装する
  - `UpdateType` 列挙型（EXE_ONLY, FULL）を実装する
  - `UpdateState` 列挙型（IDLE, CHECKING, UPDATE_AVAILABLE, UP_TO_DATE, DOWNLOADING, APPLYING, COMPLETED, ERROR）を実装する
  - `AssetInfo` データクラス（name, size, download_url）を実装する
  - `ReleaseInfo` データクラス（tag_name, version, release_notes, assets, update_type, target_asset）を実装する
  - `UpdateStatus` データクラス（state, message, version, error）を実装する
  - `DownloadProgress` データクラス（downloaded_bytes, total_bytes, speed_bytes_per_sec, elapsed_seconds + percent/eta_seconds/downloaded_mb/total_mb/speed_mb_s プロパティ）を実装する
  - `BackupInfo` データクラス（backup_path, version, update_type, created_at）を実装する
  - `UpdateError`, `UpdateCheckError`, `DownloadError`, `DownloadCancelledError`, `ApplyError`, `RollbackError` 例外クラス階層を実装する

- [x] 2. VersionParser の実装
  - `src/screen_audio_recorder/updater.py` を作成し `VersionParser` クラスを実装する
  - `parse()` 静的メソッド: "v"/"V" プレフィックス除去、MAJOR.MINOR.PATCH 解析、プレリリースサフィックス検出時に None を返す
  - `compare()` 静的メソッド: MAJOR → MINOR → PATCH の順に数値比較、戻り値 -1/0/1
  - 不正なバージョン文字列に対して None を返す
  - `logging.getLogger(__name__)` でロガーを取得し、不正バージョン検出時に WARNING ログを出力する

- [x] 3. VersionParser のテスト
  - `tests/test_updater.py` を作成する
  - `parse()` の正常系テスト: "0.1.0", "v1.2.3", "V10.20.30"
  - `parse()` の異常系テスト: "abc", "1.2", "1.2.3.4", "1.2.3-beta", ""
  - `compare()` のテスト: 大小比較、等値、各桁の優先順位
  - Property 1（推移律）プロパティベーステスト: hypothesis 200例
  - Property 2（反射律）プロパティベーステスト: hypothesis 100例
  - Property 4（"v" プレフィックス正規化）プロパティベーステスト: hypothesis 100例

- [x] 4. GitHubClient の実装
  - `updater.py` に `GitHubClient` クラスを追加する
  - `fetch_latest_release()`: urllib.request + ssl で HTTPS 通信、30秒タイムアウト、JSON パース、アセット判定
  - `download_asset()`: 8KB チャンク読み込み、on_progress コールバック、cancel_event チェック、600秒タイムアウト
  - INFO/DEBUG/ERROR ログを設計書のログセクションに従い出力する

- [x] 5. GitHubClient のテスト
  - `tests/test_updater.py` に追加する
  - `fetch_latest_release()` モックテスト: zip+exe リリース→FULL判定、exe のみ→EXE_ONLY 判定
  - 異常系: タイムアウト、HTTP 404、不正 JSON
  - `download_asset()` モックテスト: 進捗コールバック、キャンセル、サイズ不一致

- [x] 6. UpdateApplier の実装
  - `updater.py` に `UpdateApplier` クラスを追加する
  - `create_backup()`: 通常更新は `*.exe.bak`、フル更新は `app-backup-vX.Y.Z` にリネーム
  - `generate_update_script()`: 通常更新/フル更新用バッチテンプレートを一時ディレクトリに生成
  - `generate_rollback_script()`: ロールバック用バッチスクリプトを生成
  - `launch_script_and_exit()`: subprocess.Popen でスクリプト起動、sys.exit(0) 実行
  - `find_backup()` / `cleanup_old_backups()` を実装する
  - INFO/DEBUG/ERROR ログを出力する

- [x] 7. UpdateApplier のテスト
  - `tests/test_updater.py` に追加する
  - `create_backup()` テスト: 通常更新/フル更新のリネーム命名規則確認
  - `create_backup()` 失敗テスト: ApplyError 発生確認
  - `generate_update_script()` / `generate_rollback_script()` テスト: バッチファイル内容確認
  - `find_backup()` テスト: あり/なし
  - `cleanup_old_backups()` テスト: 削除確認

- [x] 8. Updater クラスの実装
  - `updater.py` に `Updater` クラスを追加する
  - `check_for_update()`: バックグラウンドスレッドで GitHubClient → VersionParser → コールバック通知
  - `download_and_apply()`: ディスク容量チェック → ダウンロード → サイズ検証 → zip展開（フル更新時）→ zip構造検証 → バックアップ → スクリプト生成 → 起動
  - `cancel_download()`: threading.Event でダウンロード中断
  - `rollback()`: ロールバックスクリプト生成 → 起動
  - `find_backup()` / `cleanup_old_backups()` を UpdateApplier に委譲

- [x] 9. Updater クラスのテスト
  - `tests/test_updater.py` に追加する
  - `check_for_update()`: モックで更新あり/なし/エラーのコールバック確認
  - `download_and_apply()`: モックダウンロード → バックアップ作成確認
  - ディスク容量不足テスト: shutil.disk_usage モック → エラーコールバック
  - `cancel_download()` / `rollback()` テスト

- [x] 10. UpdateProgressDialog の実装
  - `src/screen_audio_recorder/gui/update_progress_dialog.py` を作成する
  - tk.Toplevel ベースのモーダルダイアログを実装する
  - プログレスバー（ttk.Progressbar）、サイズラベル、速度ラベル、残り時間ラベル、キャンセルボタンを配置する
  - `update_progress(progress)` メソッド: 各ラベルとプログレスバーを更新する
  - `close()` メソッド: ダイアログを破棄する
  - 500ms ごとの GUI 更新ロジック（root.after ベース）を実装する

- [x] 11. AboutTab の拡張
  - `src/screen_audio_recorder/gui/about_tab.py` を修正する
  - `__init__()` に `updater` と `is_recording` パラメータを追加する
  - 「更新を確認」ボタン、ステータス表示エリア、「前のバージョンに戻す」ボタンを追加する
  - ステータスの色分け表示（グレー/緑/赤/青）を実装する
  - 録画中のボタングレーアウトとツールチップを実装する
  - `_on_check_update()` / `_on_status_changed()` / `_on_rollback()` を実装する

- [x] 12. MainWindow と main.py の統合
  - `main_window.py`: Updater インスタンス生成、AboutTab への注入、WM_DELETE_WINDOW ハンドラ追加
  - `main.py`: _REPO_OWNER / _REPO_NAME 定数定義、Updater 初期化、起動時バックアップクリーンアップ

- [x] 13. AboutTab のテスト
  - `tests/test_about_tab.py` を作成する
  - ボタン初期状態テスト、録画中無効化テスト
  - ステータスラベル遷移テスト（CHECKING → UPDATE_AVAILABLE / UP_TO_DATE / ERROR）
  - ロールバックボタンの表示/非表示テスト

- [x] 14. 統合テストとドキュメント更新
  - 手動テスト: exe ビルド後に GitHub Releases API 接続確認
  - 手動テスト: ダウンロード進捗リアルタイム表示確認
  - 手動テスト: バッチスクリプトによる exe 置き換え → 再起動確認
  - 手動テスト: ロールバック機能確認
  - `docs/user-manual.md` に自動更新の使い方を追加
  - `README.md` にリリース手順（アセット命名規則）を追加

## Task Dependency Graph

```json
{
  "waves": [
    {
      "name": "Wave 1: Foundation",
      "tasks": [1],
      "description": "データモデルと例外クラス（全タスクの前提）"
    },
    {
      "name": "Wave 2: Core Components",
      "tasks": [2, 4, 6],
      "description": "VersionParser, GitHubClient, UpdateApplier（並行実装可能）"
    },
    {
      "name": "Wave 3: Core Tests",
      "tasks": [3, 5, 7],
      "description": "各コアコンポーネントのテスト（並行実施可能）"
    },
    {
      "name": "Wave 4: Updater Integration",
      "tasks": [8, 9],
      "description": "Updater クラスの実装とテスト"
    },
    {
      "name": "Wave 5: GUI Implementation",
      "tasks": [10, 11],
      "description": "UpdateProgressDialog と AboutTab 拡張"
    },
    {
      "name": "Wave 6: Application Integration",
      "tasks": [12, 13],
      "description": "MainWindow/main.py の統合と AboutTab テスト"
    },
    {
      "name": "Wave 7: Final Validation",
      "tasks": [14],
      "description": "統合テストとドキュメント更新"
    }
  ]
}
```

## Notes

- Task 1 はすべてのタスクの前提条件。データモデルが定まらないと他の実装が進められない。
- Task 2, 4, 6 は並行して実装可能（それぞれ独立したクラス）。
- Task 8 は Task 2, 4, 6 の完了後に着手する（すべてのコンポーネントを統合するため）。
- Task 10, 11 は GUI 実装のため、Updater クラス（Task 8）のインターフェースが確定してから着手する。
- Task 14 は PyInstaller ビルド環境が必要なため、最後に実施する。
