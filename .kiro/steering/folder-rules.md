---
inclusion: auto
---

# プロジェクト フォルダルール — Screen Audio Recorder

このプロジェクトのフォルダ構成ルール。新規ファイル・フォルダ追加時に従うこと。

## フォルダ構成の基本原則

1. **番号プレフィックスで整理する** — フォルダの並び順と依存関係を明示する
2. **レイヤー別に分離する** — アプリ・インフラ・スクリプト・ドキュメント・資材を混在させない
3. **テストデータはアプリ近くに配置する** — テスト対象と入出力データを近接させる

## 現在のフォルダ構成

```
work-type-0/
├── src/                          # メインアプリケーション実装
│   └── screen_audio_recorder/    # メインパッケージ
│       └── gui/                  # GUI レイヤー（tkinter）
├── infra/                        # インフラ構成（AWS CloudFormation）
│   ├── templates/                # CFn テンプレート（番号プレフィックス付き）
│   │   ├── 01_network.yaml      # VPC・サブネット
│   │   ├── 11_vllm-server.yaml  # vLLM GPU サーバー
│   │   └── 12_saas-resources.yaml # Bedrock/Transcribe IAM
│   └── parameters/               # 環境別パラメータ
├── scripts/                      # ユーティリティスクリプト
│   ├── download_ffmpeg.py
│   └── download_llama_server.py
├── docs/                         # ドキュメント
│   ├── 01.操作説明書/            # ユーザーマニュアル
│   ├── 02.ブログ/               # 技術ブログ記事
│   └── 03.技術記録/             # トラブルシュート・社内資料
├── _internal/                    # 外部バイナリ（llama-server, ffmpeg）
├── tests/                        # ユニットテスト（pytest + hypothesis）
├── dist/                         # ビルド成果物（PyInstaller 出力）
├── build/                        # ビルド中間ファイル
├── .kiro/                        # Kiro設定・ステアリング・スペック
├── .venv/                        # Python 仮想環境
├── pyproject.toml                # プロジェクト設定
├── conftest.py                   # pytest 共通フィクスチャ
└── screen_audio_recorder.spec    # PyInstaller ビルド仕様
```

## フォルダ別ルール

### `src/screen_audio_recorder/` — メインアプリケーション

- Python パッケージとして構成（`__init__.py` 必須）
- GUI は `gui/` サブパッケージにまとめる
- 新規モジュール追加時は既存の命名規則（snake_case）に従う
- 機能追加時はモデル定義を `models.py` に集約する

### `infra/` — インフラ構成

- CloudFormation テンプレートは `templates/` に配置する
- ファイル名: `<リソース種別>.yaml` 形式
- 依存関係がある場合は Cross-Stack References（Export/Import）を使用する
- 環境別パラメータは `parameters/` に `<環境名>.json` で配置する
- `README.md` にデプロイ手順を記載する
- 実際のシークレット（`.env`）はコミット禁止

### `scripts/` — ユーティリティスクリプト

- 単発実行の自動化スクリプトを配置する
- ファイル名で用途が分かるように命名する（例: `download_ffmpeg.py`）
- スクリプトは `if __name__ == "__main__":` ガードを含める

### `docs/` — ドキュメント

- 操作説明書: `user-manual.md`
- ブログ記事: `blog-<タイトル>.md` 形式
- トラブルシュート記録: `<種別>-troubleshooting-history.md`
- 新規ドキュメント追加時は種別をファイル名に含める

### `_internal/` — 外部バイナリ・ツール

- 外部ツールのバイナリを配置する（llama-server, ffmpeg 等）
- `.gitignore` に含める（大きなバイナリはコミット対象外）
- ダウンロードスクリプトは `scripts/` に対応するものを用意する

### `tests/` — ユニットテスト

- ファイル名は `test_<モジュール名>.py` 形式にする
- テストフレームワーク: pytest + hypothesis（Property-Based Testing）
- テストフィクスチャはルートの `conftest.py` に共通定義する
- インテグレーションテストには `@pytest.mark.integration` マーカーを付ける

## 命名規則

| 対象 | 規則 | 例 |
|------|------|-----|
| Python ファイル | snake_case | `audio_capture.py` |
| Python クラス | PascalCase | `RecorderController` |
| テストファイル | `test_<対象>.py` | `test_transcriber.py` |
| IaC テンプレート | kebab-case `.yaml` | `vllm-server.yaml` |
| ドキュメント | kebab-case `.md` | `user-manual.md` |
| ステアリング | kebab-case `.md` | `folder-rules.md` |
| パラメータファイル | `<環境名>.json` | `dev.json` |

## 新規ファイル/フォルダ追加時のルール

1. Python モジュールには必ず `__init__.py` を含める
2. テスト追加時は対応するモジュール名に合わせる
3. `.gitignore` に `.venv/`, `__pycache__/`, `.hypothesis/`, `_internal/`, `dist/`, `build/` が含まれていることを確認する
4. 新規外部バイナリを追加する場合は対応するダウンロードスクリプトも用意する
5. 新規 AWS リソースを追加する場合は `infra/templates/` にテンプレートを追加し、`infra/README.md` を更新する
6. 一時的な出力ファイル（`test_output.txt` 等）はコミット対象外とする
