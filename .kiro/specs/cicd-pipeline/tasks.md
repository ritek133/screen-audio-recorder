# 実装計画: cicd-pipeline

## 概要

本計画は、CI/CD 要件定義書（`docs/04.設計書/20_cicd-要件定義書.md`）および設計書（`docs/04.設計書/21_cicd-設計書.md`）に基づき、GitHub Actions による CI/CD パイプラインを段階的に構築するためのタスクリストです。

- CI（`ci.yml`）: PR 時にテストとセキュリティチェックを実行
- CD（`release.yml`）: タグ push 時にビルドとリリースを実行

CI と CD は独立して実装可能です。各タスクには要件トレーサビリティ（`_要件: xxx_`）を付記しています。`*` 付きタスクは検証・任意タスクです。

技術スタック: GitHub Actions / pytest / gitleaks / PyInstaller / softprops/action-gh-release

## Tasks

- [x] 1. CI ワークフロー（test ジョブ）の構築
  - `.github/workflows/ci.yml` を新規作成する
  - トリガーを `pull_request` の `branches: [main]` に設定する
  - `test` ジョブを `runs-on: ubuntu-latest` で定義する（OS 非依存のロジックテストのため）
  - ステップ: チェックアウト → Python 3.10 セットアップ → pip キャッシュ有効化 → `pip install -e ".[dev]"` → `pytest` 実行
  - ジョブ名を `test` にする（ブランチ保護のステータスチェック名と一致させる）
  - _要件: CI-1、CI-2、CI-3、CI-4、CI-5、BR-4_

- [ ] 2. セキュリティチェックの構築
  - [x] 2.1 `security` ジョブを `ci.yml` に追加する
    - `test` と並列実行される独立ジョブとして `runs-on: ubuntu-latest` で定義する
    - 全履歴を取得するチェックアウト（`fetch-depth: 0`）を行う
    - `gitleaks/gitleaks-action@v2` を使用し、`env` に `GITHUB_TOKEN` を設定する
    - PR 差分のみをスキャンする（gitleaks のデフォルト動作）
    - ジョブ名を `security` にする
    - _要件: SEC-1、SEC-3、SEC-4、SEC-6、SEC-7、BR-4_

  - [x] 2.2 `.gitleaks.toml` を作成する
    - プロジェクトルートに配置する
    - `allowlist.paths` に `tests/.*`、`docs/.*`、`.gitleaks.toml` を登録する（false positive 対策）
    - _要件: SEC-6_

  - [-] 2.3 カスタムセキュリティチェックスクリプトを作成する
    - PR 差分ファイルに対して以下を grep で検出する:
      - メールアドレス（`example.com`・`placeholder` を含むものは除外）
      - Windows ローカルパス（`C:\Users\...`）
      - Unix ローカルパス（`/home/...`）
      - 電話番号（日本形式）・マイナンバー形式
    - `tests/` 配下・ドキュメントのプレースホルダーを除外する
    - 検出時は exit 1 でジョブを失敗させる
    - `security` ジョブのステップに組み込む
    - _要件: SEC-2、SEC-5、SEC-6_

  - [ ]* 2.4 セキュリティチェックの動作を検証する
    - ダミーの機密情報（ダミー AWS キー・ローカルパス）を含むファイルで `security` ジョブが失敗することを確認する
    - クリーンな差分ではパスすることを確認する
    - **検証対象: SEC-1〜SEC-7**

- [~] 3. Release ワークフロー（骨組み + テストゲート）の構築
  - `.github/workflows/release.yml` を新規作成する
  - トリガーを `push` の `tags: ['v*']` に設定する
  - `release` ジョブを `runs-on: windows-latest` で定義する（PyInstaller で Windows exe を生成するため）
  - `permissions: contents: write` を設定する（リリース作成・アセットアップロードに必要）
  - ステップ前半: チェックアウト → Python 3.10 → `pip install -e ".[dev]"` → `pytest`（ビルド前ゲート）
  - _要件: CD-1、CD-2、CD-5、REL-5_

- [ ] 4. ビルドと後処理の構築
  - [~] 4.1 PyInstaller ビルドステップを追加する
    - PyInstaller をインストールし、`screen_audio_recorder.spec` でビルドする
    - 出力 `dist/screen-audio-recorder/` が生成されることを確認する
    - _要件: CD-3、CD-4_

  - [~] 4.2 ビルド後処理ステップを追加する
    - `${{ github.ref_name }}` からタグを取得し、`v` プレフィックスを除去してバージョン番号を抽出する
    - `artifacts/` ディレクトリを作成する
    - exe を `screen-audio-recorder-vX.Y.Z.exe` にリネームコピーする（`Copy-Item`）
    - `dist/screen-audio-recorder/*` の中身を `screen-audio-recorder-vX.Y.Z-full.zip` に圧縮する（`Compress-Archive`）
    - zip のルート直下に `screen-audio-recorder.exe` と `_internal/` が並ぶ構造にする
    - _要件: POST-1、POST-2、POST-3、POST-4_

- [~] 5. リリース作成の構築
  - `softprops/action-gh-release` を使用してリリース作成ステップを追加する
  - リリース設定: `name` = `Screen Audio Recorder ${{ github.ref_name }}`、`tag` = `${{ github.ref_name }}`
  - `draft: false`、`prerelease: false`（自動更新の対象にするため）
  - `generate_release_notes: true`（前回タグからの差分を自動生成）
  - `files` に exe（`artifacts/screen-audio-recorder-v*.exe`）と zip（`artifacts/screen-audio-recorder-v*-full.zip`）の両方を指定する
  - _要件: REL-1、REL-2、REL-3、REL-4、REL-5_

- [~] 6. 自動更新との命名整合性の確認
  - `updater.py` のリリース検知ロジックを読み、判定パターンを確認する
    - `*-full.zip` → フル更新、`*.exe` → 通常更新、両方あれば zip 優先
  - Release ワークフローの成果物命名（タスク 4.2）が判定ロジックと完全一致することを検証する
  - 不一致があればタスク 4.2 の命名を修正する
  - _要件: 要件定義書 5 章（自動更新との整合性）、前提条件「自動更新との互換性」_

- [~] 7. ブランチ保護設定の手順書化
  - GitHub リポジトリの Settings で行う手動設定のため、手順を `docs/` または README に明記する
    - main への直接 push 禁止（PR 経由のみ）
    - 承認 1 名以上を必須
    - `test`・`security` をステータスチェックとして必須にする
    - 「Require branches to be up to date before merging」を有効化
  - ステータスチェック名は `ci.yml` のジョブ名（`test`、`security`）と一致させる注意点を記載する
  - _要件: BR-1、BR-2、BR-3、BR-4_

- [ ]* 8. パイプライン全体の動作確認
  - [ ]* 8.1 CI ワークフローを検証する
    - テストブランチから main 向け PR を作成し、`test`・`security` ジョブが起動しパスすることを確認する
    - **検証対象: CI-1〜CI-6、SEC-6**

  - [ ]* 8.2 Release ワークフローを検証する
    - テストタグ（例 `v0.0.1-test`）を push し、テスト → ビルド → 後処理 → リリース作成が通ることを確認する
    - 生成された exe・zip の命名と zip 内構造（ルートに exe と `_internal/`）を検証する
    - ビルド時間が 15 分以内であることを確認する
    - 確認後、テストリリースとタグを削除する
    - **検証対象: CD-1〜CD-5、POST-1〜POST-4、REL-1〜REL-5、非機能要件（ビルド時間）**

## スコープ外（将来の拡張候補）

設計書 10 章に基づき、以下は今回のスコープ外とします。

- コード署名（Authenticode）
- VirusTotal へのアップロード（誤検知対策）
- Changelog の自動生成（conventional commits）
- バージョン一致チェック（タグ / pyproject.toml / __init__.py の整合性検証）

## 依存関係メモ

- タスク 1（CI）とタスク 3〜5（CD）は独立して並行実装できます。
- タスク 6（updater 整合性）はタスク 4.2 の成果物命名に直結するため、タスク 4.2 を確定する前に確認すると手戻りを防げます。
- タスク 7（ブランチ保護）はコードで完結せず GitHub 設定に依存します。CI が 1 回以上実行された後でないとステータスチェック候補に表示されない点に注意が必要です。
