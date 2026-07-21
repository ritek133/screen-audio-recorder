# Screen Audio Recorder

Windows 画面・音声録画 & 自動文字起こしアプリケーション。

管理者権限なしで動作し、画面録画・マイク音声・システム音声の同時録音、ローカル AI による文字起こし、LLM によるテキスト後処理・メモ管理機能を提供します。

---

## プロジェクトフォルダ構成

```
screen-audio-recorder/
├── src/                          # アプリケーションソースコード
│   └── screen_audio_recorder/    # メインパッケージ
│       ├── gui/                  # GUI レイヤー（tkinter）
│       │   ├── __init__.py
│       │   ├── main_window.py        # メインウィンドウ（録画操作・タブ管理）
│       │   ├── memo_list_view.py     # メモ一覧表示（ページネーション・再生・削除）
│       │   ├── region_overlay.py     # 録画領域オーバーレイ（赤枠・ドラッグ・リサイズ）
│       │   ├── llm_settings_tab.py   # LLM 設定タブ（モデル選択・API 設定・プロンプト編集）
│       │   ├── advanced_settings_tab.py  # 詳細設定タブ（ログレベル等）
│       │   ├── about_tab.py         # バージョン情報タブ（更新確認・ロールバック）
│       │   └── update_progress_dialog.py  # 更新ダウンロード進捗ダイアログ
│       ├── __init__.py               # パッケージメタデータ（バージョン・作者情報）
│       ├── main.py                   # エントリーポイント（初期化・コンポーネント結合）
│       ├── recorder_controller.py    # 録画パイプライン制御（開始・停止・スレッド管理）
│       ├── screen_capture.py         # 画面キャプチャ（dxcam/mss）
│       ├── audio_capture.py          # 音声キャプチャ（WASAPI ループバック・マイク）
│       ├── video_encoder.py          # 映像エンコード（ffmpeg・HW エンコーダ自動検出）
│       ├── transcriber.py            # 音声文字起こし（faster-whisper）
│       ├── text_post_processor.py    # テキスト後処理（LLM による修正・要約・テーマ生成）
│       ├── llm_client.py             # LLM 推論クライアント（ローカル/API 対応）
│       ├── theme_generator.py        # テーマ生成（janome 形態素解析フォールバック）
│       ├── memo_store.py             # メモ永続化（JSON ファイル）
│       ├── file_store.py             # 録画ファイル管理（保存パス生成・削除）
│       ├── error_notifier.py         # エラー通知（GUI ダイアログ表示）
│       ├── models.py                 # データモデル定義（dataclass）
│       ├── updater.py                # 自動更新モジュール（GitHub Releases 連携）
│       ├── updater_models.py         # 更新機能のデータモデル定義
│       ├── app_settings_store.py     # アプリ設定の読み書き
│       └── llm_settings_store.py     # LLM 設定の読み書き
│
├── tests/                        # ユニットテスト（pytest）
│   ├── __init__.py
│   ├── test_audio_capture.py         # AudioCapture のテスト
│   ├── test_screen_capture.py        # ScreenCapture のテスト
│   ├── test_video_encoder.py         # VideoEncoder のテスト
│   ├── test_recorder_controller.py   # RecorderController のテスト
│   ├── test_transcriber.py           # Transcriber のテスト
│   ├── test_memo_store.py            # MemoStore のテスト
│   ├── test_memo_list_view.py        # MemoListView のテスト
│   ├── test_file_store.py            # FileStore のテスト
│   ├── test_models.py                # データモデルのテスト
│   ├── test_theme_generator.py       # ThemeGenerator のテスト
│   ├── test_error_notifier.py        # ErrorNotifier のテスト
│   ├── test_updater.py               # Updater（自動更新）のテスト
│   ├── test_about_tab.py             # AboutTab（更新UI）のテスト
│   └── test_update_progress_dialog.py  # UpdateProgressDialog のテスト
│
├── scripts/                      # ユーティリティスクリプト
│   ├── download_ffmpeg.py            # ffmpeg バイナリのダウンロード
│   └── download_llama_server.py      # llama-server のダウンロード
│
├── docs/                         # ドキュメント
│   ├── user-manual.md                # 操作説明書
│   ├── blog-audio-recording-knowledge.md   # 音声録音の技術知見
│   ├── blog-audio-video-sync-solved.md     # 音声映像同期の解決記録
│   └── sync-troubleshooting-history.md     # 同期問題のトラブルシュート履歴
│
├── dist/                         # ビルド成果物（PyInstaller 出力）
│   └── screen-audio-recorder/        # 配布用実行ファイル一式
│       ├── screen-audio-recorder.exe     # 実行ファイル本体
│       └── _internal/                    # 依存ライブラリ・リソース
│
├── build/                        # PyInstaller ビルド中間ファイル
│
├── _internal/                    # 同梱バイナリ（開発時参照用）
│   └── llama-server.exe              # ローカル LLM 推論サーバー
│
├── .kiro/                        # Kiro IDE 設定・仕様書
│   └── specs/screen-audio-recorder/  # 要件定義・設計・タスク
│
├── pyproject.toml                # プロジェクト設定（依存関係・ビルド設定）
├── conftest.py                   # pytest 共通フィクスチャ
├── screen_audio_recorder.spec    # PyInstaller ビルド仕様ファイル
└── README.md                     # このファイル
```

### フォルダ用途まとめ

| フォルダ | 用途 |
|---------|------|
| `src/screen_audio_recorder/` | アプリケーション本体のソースコード |
| `src/screen_audio_recorder/gui/` | tkinter による GUI コンポーネント群 |
| `tests/` | pytest によるユニットテスト |
| `scripts/` | 開発・セットアップ用ユーティリティスクリプト |
| `docs/` | 操作説明書・技術ドキュメント |
| `dist/` | PyInstaller でビルドした配布用バイナリ |
| `build/` | PyInstaller のビルド中間ファイル（自動生成） |
| `_internal/` | 開発時に参照する同梱バイナリ（llama-server 等） |
| `.kiro/` | Kiro IDE の設定ファイル・仕様書 |

---

## 別環境でのセットアップ

リポジトリをクローンした別のWindows環境で開発・実行するための手順です。

### 前提条件

- Windows 10/11（64bit）
- Python 3.10 以上
- インターネット接続（外部バイナリ・モデルのダウンロードに必要）

### 手順

```powershell
# 1. リポジトリのクローン
git clone <リポジトリURL>
cd work-type-0

# 2. 仮想環境の作成と有効化
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. 依存ライブラリのインストール（編集可能モード）
pip install -e ".[dev]"

# 4. 外部バイナリのダウンロード
python scripts/download_ffmpeg.py        # _internal/ffmpeg.exe を取得（約80MB）
python scripts/download_llama_server.py  # _internal/llama-server.exe を取得

# 5. アプリ起動
python -m screen_audio_recorder.main

# 6. テスト実行
pytest
```

### 補足

- **仮想環境**: `.venv` に作成され `.gitignore` に含まれています。仮想環境が有効化されていない場合はフルパスで実行してください: `.\.venv\Scripts\python.exe -m screen_audio_recorder.main`
- **faster-whisper モデル**: 初回の文字起こし実行時に `~/Documents/screen-audio-recorder/models/` へ自動ダウンロードされます（large モデル: 約3GB）
- **llama-server**: LLM テキスト後処理機能を使う場合に必要です。使わない場合はスキップ可能

---

## セットアップ（開発環境・既存）

```powershell
# 仮想環境の有効化
.\.venv\Scripts\Activate.ps1

# 依存関係のインストール
pip install -e ".[dev]"

# テスト実行
pytest

# アプリ起動
python -m screen_audio_recorder.main
```

## ビルド（配布用 exe）

```powershell
# 仮想環境の有効化
.\.venv\Scripts\Activate.ps1

# PyInstaller のインストール（初回のみ）
pip install pyinstaller

# ビルド実行
pyinstaller screen_audio_recorder.spec --noconfirm
```

> **注**: PowerShell で `.\.venv\Scripts\` のパスが認識されない場合はフルパスで実行:
> ```powershell
> & "C:\Users\user2\Dropbox\huangシステム設計書\APP開発\work-type-0\.venv\Scripts\pyinstaller.exe" screen_audio_recorder.spec --noconfirm
> ```

ビルド成果物は `dist/screen-audio-recorder/` に出力されます。

---

## リリース手順

### アセット命名規則

GitHub Releases にアセットをアップロードする際は、以下の命名規則に従ってください:

| 更新種別 | ファイル名パターン | 例 |
|---------|-------------------|-----|
| 通常更新（exe 単体） | `screen-audio-recorder-vX.Y.Z.exe` | `screen-audio-recorder-v0.2.0.exe` |
| フル更新（zip） | `screen-audio-recorder-vX.Y.Z-full.zip` | `screen-audio-recorder-v0.2.0-full.zip` |

### zip ファイルの構造

フル更新用の zip は以下の構造である必要があります（ルート直下に exe と `_internal` が並ぶ）:

```
screen-audio-recorder-v0.2.0-full.zip
├── screen-audio-recorder.exe
└── _internal/
    └── ...
```

### リリースフロー

1. `src/screen_audio_recorder/__init__.py` の `__version__` を更新する
2. `pyproject.toml` の `version` を同じ値に更新する
3. コミット & タグ作成: `git tag v0.2.0`
4. `pyinstaller screen_audio_recorder.spec --noconfirm` でビルド
5. `dist/screen-audio-recorder/` の内容を zip に圧縮（フル更新の場合）
6. GitHub Releases で新しいリリースを作成:
   - タグ: `v0.2.0` （"v" プレフィックス必須）
   - アセット: exe ファイル、必要に応じて zip ファイル
   - リリースノート: 変更内容を記載
7. プレリリースにはしない（プレリリースタグは自動更新の対象外）

### 更新判定ロジック

- zip アセット（`*-full.zip`）が存在する場合: **フル更新** として処理
- exe アセットのみ存在する場合: **通常更新** として処理
- 両方存在する場合: zip（フル更新）が優先される

---

## ドキュメント

- [操作説明書](docs/user-manual.md)
- [音声録音の技術知見](docs/blog-audio-recording-knowledge.md)
- [音声映像同期の解決記録](docs/blog-audio-video-sync-solved.md)
