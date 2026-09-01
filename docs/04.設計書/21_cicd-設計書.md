# CI/CD パイプライン設計書

## 1. ワークフロー構成

GitHub Actions ワークフローを2つに分離する。

| ファイル | 用途 | トリガー |
|---------|------|---------|
| `.github/workflows/ci.yml` | テスト実行 + セキュリティチェック | PR 作成・更新（main 向け） |
| `.github/workflows/release.yml` | ビルド & リリース | タグ push（`v*`） |

### 分離理由

- CI は PR ごとに高頻度で実行される → 軽量にする
- CD はリリース時のみ実行 → Windows runner + PyInstaller で重い処理を含む
- トリガー条件が異なるため、1ファイルにまとめると条件分岐が複雑になる

---

## 2. CI ワークフロー設計（ci.yml）

### 2.1 トリガー

```yaml
on:
  pull_request:
    branches: [main]
```

### 2.2 ジョブ構成

```
job: test
  runs-on: windows-latest
  steps:
    1. リポジトリチェックアウト
    2. Python 3.10 セットアップ
    3. 依存インストール（pip install -e ".[dev]"）
    4. pytest 実行

job: security
  runs-on: ubuntu-latest
  permissions:
    contents: read
    pull-requests: read
  steps:
    1. リポジトリチェックアウト（全履歴）
    2. gitleaks によるシークレットスキャン（PR差分のみ）
    3. カスタムスクリプトによる追加チェック（個人情報・ローカルパス検出）
```

### 2.3 設計判断

| 項目 | 判断 | 理由 |
|------|------|------|
| OS | windows-latest | 当初は「OS 非依存のロジックテスト」との想定で ubuntu-latest を採用したが、実行時依存の dxcam / PyAudioWPatch が Windows 専用で Linux 用 wheel を提供しないため、ubuntu では `pip install -e ".[dev]"` が失敗する。CI 検証（タスク8.1）でこの不具合を確認し、windows-latest へ変更した。Release ワークフローも windows-latest であり一貫する |
| Python バージョン | 3.10 固定 | pyproject.toml の requires-python と一致。マトリクスは不要（デスクトップアプリのため） |
| キャッシュ | pip キャッシュを使用 | 依存インストールの高速化 |
| ジョブ分離 | test と security を並列実行 | 互いに依存しないため並列化で CI 時間を短縮 |
| OS 変更の経緯 | ubuntu-latest → windows-latest | dxcam / PyAudioWPatch は Windows 専用依存であり Linux では導入不可。テストコード自体は OS 非依存でも、依存インストール段階で失敗するため Windows runner が必須 |

---

## 2A. セキュリティチェック設計（ci.yml 内 security ジョブ）

### 2A.1 ツール選定

| ツール | 用途 | 選定理由 |
|--------|------|---------|
| gitleaks | シークレット検出 | GitHub Actions 公式マーケットプレイスで提供。高速。AWS キー、API トークン、秘密鍵等のパターンを内蔵 |
| カスタムスクリプト | 個人情報・ローカルパス検出 | gitleaks がカバーしないプロジェクト固有のパターンを補完 |

### 2A.2 gitleaks の設定

```yaml
- uses: gitleaks/gitleaks-action@v2
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- gitleaks-action は PR のコミット一覧を GitHub API 経由で取得するため、`GITHUB_TOKEN` に `contents: read` と `pull-requests: read` の権限が必要。security ジョブに `permissions` を宣言していないと権限不足で 403（`Resource not accessible by integration`）が発生する。CI 検証（タスク8.1）でこの不具合を確認したため、security ジョブに以下の `permissions` を宣言する（SEC-6）:

```yaml
job: security
  permissions:
    contents: read
    pull-requests: read
```

- 上記の permissions 宣言でも 403 が解消しない場合、リポジトリ側で Actions のトークン権限が制限されている可能性がある。その場合は リポジトリ Settings > Actions > General > Workflow permissions を「Read and write permissions」に変更する。
- PR の差分コミットのみをスキャン（デフォルト動作）
- 検出対象パターン（内蔵）:
  - AWS Access Key ID（`AKIA...`）
  - AWS Secret Access Key
  - GitHub Token / Personal Access Token
  - 秘密鍵ファイル内容（`-----BEGIN.*PRIVATE KEY-----`）
  - 一般的な API キーパターン
  - `.env` ファイル内のキーバリューペア

### 2A.3 カスタムチェックスクリプト

PR の差分ファイルに対して以下のパターンを grep で検出する:

| 検出項目 | パターン例 | 除外対象 |
|---------|-----------|---------|
| メールアドレス | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | `example.com`, `placeholder` を含むもの |
| Windows ローカルパス | `[A-Z]:\\Users\\[^\\]+\\` | テスト用のモック値、コメント内のドキュメント例 |
| Unix ローカルパス | `/home/[a-zA-Z0-9_]+/` | テスト用のモック値 |
| 電話番号（日本） | `0[0-9]{1,4}-[0-9]{1,4}-[0-9]{3,4}` | — |
| 日本のマイナンバー | `\d{4}\s?\d{4}\s?\d{4}` | 明らかにバージョン番号等の文脈を除外 |

### 2A.4 除外ルール（false positive 対策）

以下は検出対象外とする:

- `.gitignore` ファイル自体
- テストコード内のモック値・ダミーデータ（`tests/` 配下）
- ドキュメント内のプレースホルダー例（`YOUR_API_KEY`, `your@email.com`）
- `gitleaks.toml` で明示的に許可したパス・パターン

### 2A.5 gitleaks 設定ファイル

プロジェクトルートに `.gitleaks.toml` を配置し、プロジェクト固有の除外ルールを定義:

```toml
[allowlist]
paths = [
    '''tests/.*''',
    '''docs/.*''',
    '''.gitleaks.toml''',
]
```

### 2A.6 失敗時の動作

- gitleaks またはカスタムチェックが検出項目を見つけた場合、ジョブを失敗させる
- PR のステータスチェックとして `security` を表示
- 検出内容は GitHub Actions のログに出力（PR コメントへの自動投稿は行わない）

---

## 3. Release ワークフロー設計（release.yml）

### 3.1 トリガー

```yaml
on:
  push:
    tags:
      - 'v*'
```

### 3.2 ジョブ構成

```
job: release
  runs-on: windows-latest
  steps:
    1. リポジトリチェックアウト
    2. Python 3.10 セットアップ
    3. 依存インストール（pip install -e ".[dev]"）
    4. pytest 実行（ビルド前ゲート）
    5. PyInstaller インストール
    6. PyInstaller ビルド実行
    7. ビルド成果物の後処理
    8. GitHub Release 作成 & アセットアップロード
```

### 3.3 設計判断

| 項目 | 判断 | 理由 |
|------|------|------|
| OS | windows-latest | PyInstaller で Windows exe を生成するため必須 |
| テスト再実行 | する | タグ push は PR マージとは別タイミングで行われる可能性があるため、安全弁として再実行 |
| 1ジョブ構成 | 単一ジョブ | ジョブ間で成果物を受け渡す必要がなく、シンプルに保つ |

---

## 4. ビルド後処理の設計

### 4.1 バージョン番号の取得

```
タグ名: v0.2.0
    ↓ 'v' プレフィックスを除去
バージョン: 0.2.0
```

GitHub Actions では `${{ github.ref_name }}` でタグ名を取得可能。

### 4.2 処理フロー

```
dist/screen-audio-recorder/
├── screen-audio-recorder.exe
└── _internal/
    └── ...

    ↓ 後処理

artifacts/
├── screen-audio-recorder-v0.2.0.exe        ← exe をリネームしてコピー
└── screen-audio-recorder-v0.2.0-full.zip   ← dist/screen-audio-recorder/ の内容を圧縮
```

### 4.3 zip 作成ロジック

```powershell
# dist/screen-audio-recorder/ の「中身」を zip 化
# zip のルートに exe と _internal/ が直接並ぶ構造にする
Compress-Archive -Path "dist/screen-audio-recorder/*" -DestinationPath "artifacts/screen-audio-recorder-v0.2.0-full.zip"
```

### 4.4 exe リネームロジック

```powershell
Copy-Item "dist/screen-audio-recorder/screen-audio-recorder.exe" "artifacts/screen-audio-recorder-v0.2.0.exe"
```

---

## 5. リリース作成の設計

### 5.1 使用アクション

`softprops/action-gh-release` を使用する。

- GitHub 公式ではないが、最も広く使われているリリースアクション
- タグからリリース作成 + アセットアップロードを1ステップで実行可能
- `GITHUB_TOKEN` のみで動作（追加シークレット不要）

### 5.2 リリース設定

| 項目 | 設定値 |
|------|--------|
| name | `Screen Audio Recorder ${{ github.ref_name }}` |
| tag | `${{ github.ref_name }}`（例: `v0.2.0`） |
| draft | `false` |
| prerelease | `false` |
| generate_release_notes | `true`（前回タグからの差分を自動生成） |
| files | `artifacts/screen-audio-recorder-v*.exe`, `artifacts/screen-audio-recorder-v*-full.zip` |

### 5.3 リリースノート

GitHub の自動生成機能を使用。前回リリースタグからの PR/コミット一覧が自動的に含まれる。  
必要に応じて手動でリリース後に編集可能。

---

## 6. ブランチ保護設定（GitHub リポジトリ設定）

GitHub Actions の設定ファイルでは制御できないため、リポジトリの Settings で手動設定する。

### 6.1 設定手順

1. GitHub リポジトリ → Settings → Branches
2. Branch protection rule を追加
3. Branch name pattern: `main`
4. 以下を有効化:
   - ☑ Require a pull request before merging
     - ☑ Require approvals: 1
   - ☑ Require status checks to pass before merging
     - ☑ Require branches to be up to date before merging
     - Status checks: `test`（ci.yml のテストジョブ名）
     - Status checks: `security`（ci.yml のセキュリティチェックジョブ名）
   - ☑ Do not allow bypassing the above settings（オーナーにも適用する場合）

### 6.2 注意事項

- ステータスチェック名（`test`, `security`）は ci.yml のジョブ名と一致させる必要がある
- 初回は CI ワークフローが1回以上実行された後でないとステータスチェックの候補に表示されない

---

## 7. ファイル構成（新規追加）

```
.github/
└── workflows/
    ├── ci.yml          # PR テスト & セキュリティチェックワークフロー
    └── release.yml     # ビルド & リリースワークフロー
.gitleaks.toml          # gitleaks 除外設定
```

---

## 8. シークレット・権限

| シークレット | 用途 | 設定方法 |
|-------------|------|---------|
| `GITHUB_TOKEN` | リリース作成・アセットアップロード | 自動提供（追加設定不要） |

### permissions 設定

Release ワークフロー（release.yml）:

```yaml
permissions:
  contents: write  # リリース作成・アセットアップロードに必要
```

CI ワークフロー（ci.yml）の security ジョブ:

```yaml
permissions:
  contents: read        # リポジトリ内容の読み取り
  pull-requests: read   # gitleaks-action が PR コミット一覧を取得するために必要
```

- security ジョブに permissions を宣言しないと、gitleaks-action が PR コミット取得時に 403（`Resource not accessible by integration`）で失敗する（SEC-6）。

---

## 9. エラーハンドリング

| 段階 | 失敗時の動作 |
|------|-------------|
| テスト失敗 | ワークフロー停止。リリースは作成されない |
| ビルド失敗 | ワークフロー停止。リリースは作成されない |
| 後処理失敗 | ワークフロー停止。リリースは作成されない |
| リリース作成失敗 | GitHub の通知で開発者に伝達。手動で再実行可能 |

### 再実行

GitHub Actions の UI から「Re-run all jobs」でワークフロー全体を再実行可能。  
タグを削除・再作成する必要はない。

---

## 10. 将来の拡張候補（スコープ外）

以下は今回のスコープ外だが、将来的に追加可能:

- コード署名（Authenticode）の追加
- VirusTotal へのアップロード（誤検知対策）
- Changelog の自動生成（conventional commits）
- バージョン一致チェック（タグ / pyproject.toml / __init__.py の整合性検証）
