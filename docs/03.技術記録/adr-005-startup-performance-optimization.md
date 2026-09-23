# ADR-005: アプリ起動時間の短縮と効率化

## ステータス

提案中（Proposed）

## 日付

2026-09-22

## コンテキスト

アプリの起動が遅いという課題が報告された。効率化の観点でコードベースを調査し、
起動時間に影響する要因を洗い出したうえで、改善方針を定める。

本 ADR は「何が起動を遅くしているか」の調査結果と、「どの順序で改善するか」の
方針を記録する。実装は本 ADR の決定に基づき、後続の PR で段階的に行う。

### 起動フローの調査結果（設計の前提）

エントリーポイントは `src/screen_audio_recorder/main.py` の `main()`。
`root.mainloop()`（イベントループ開始）より**前に**、以下がすべて同期実行される。

1. コンソール非表示・DPI 設定（`ctypes`。軽量）
2. `_setup_logging()`（`app_settings.json` を同期読み込み。軽量）
3. `_ensure_data_dirs()`（データディレクトリを `mkdir`。軽量）
4. 各コンポーネントの import＋インスタンス化
   （AudioCapture / ScreenCapture / VideoEncoder / Transcriber / **LlmClient** /
   TextPostProcessor / ExportManager / RecorderController / Updater / MainWindow）
5. `root.mainloop()`

すでに非同期化されている良い設計もある。

- **Whisper モデルは遅延・バックグラウンドロード**：`main.py` で
  `Transcriber(..., lazy_load=True)` を渡し、実ロードは
  `transcriber.load_model_async(callback=..., root=root)` が daemon スレッドで実行する。
  完了後に `main_window.set_ready()` で録画ボタンを有効化するため、**起動をブロックしない**。
- **Updater は非同期**：更新確認（GitHub API アクセス）は daemon スレッドで実行。
  起動時の `updater.cleanup_old_backups()` はローカル処理のみ。
- **設定 JSON はいずれも小さく軽量**。
- **PyInstaller は `--onedir` + `excludes`**（matplotlib/scipy/pandas/PIL を除外）で、
  onefile より起動が速く、不要ライブラリも同梱していない。

一方で、以下が起動時間のボトルネックとして残っている（影響度順）。

#### 🔴 最優先：llama-server の起動待ちが最大 120 秒間メインスレッドをブロック

- 場所：`src/screen_audio_recorder/llm_client.py`
  `__init__` → `_initialize()` → `_init_local()` → `_wait_for_server()`
- `main.py` で `LlmClient(...)` を**同期構築**している。ローカルバックエンド設定済みの
  ユーザーでは `subprocess.Popen` で llama-server を起動後、`_wait_for_server()` が
  `_SERVER_START_TIMEOUT = 120` 秒を上限に 1 秒間隔でヘルスチェックをポーリングし続ける。
  この間 `root.mainloop()` に到達できず、**ウィンドウが表示されない／固まる**。
- Whisper モデルロードは非同期化済みなのに、LLM 初期化だけが同期のままである点が非対称。

#### 🟠 高優先：重いライブラリのトップレベル import

- `transcriber.py`：`from faster_whisper import WhisperModel`（CTranslate2 ロードを伴い重い）、
  `import boto3`
- `aws_utils.py`：`import boto3` / `botocore`
- `screen_capture.py`：`import dxcam`（DXGI 初期化を伴う）, `import mss`, `import win32api` 等
- `audio_capture.py` / `video_encoder.py`：`import numpy`
- `main.py` はコンポーネントを関数内 import して遅延化を試みているが、**各モジュールが
  トップレベルで重いライブラリを import している**ため効果が相殺されている。特に `boto3` は
  AWS 未使用時、`faster-whisper` はモデルロード前でも import コストが発生する。

#### 🟠 高優先：マイクデバイス列挙が同期実行

- 場所：`gui/main_window.py` `_build_ui()` → `_load_mic_devices()`
  → `audio_capture.list_mic_devices()`
- PyAudio 経由のデバイス列挙は環境によって数百 ms〜秒級の同期 I/O となり、mainloop 前に走る。

#### 🟡 中優先：全 GUI タブを起動時に即時構築

- 場所：`gui/main_window.py` `_build_ui()`
  （録画 / メモ一覧 / LLM 設定 / 詳細設定 / メモ出力設定 / About を一括構築）
- 設定系タブは構築時に設定 JSON を読み込むため、初回表示コストが起動時に集中する。

#### 🟡 中優先：PyInstaller の UPX 圧縮

- 場所：`screen_audio_recorder.spec`（`upx=True`）
- UPX 圧縮は配布サイズを減らす一方、起動時の展開処理でわずかに起動が遅くなる場合がある。

## 決定

起動を高速化するため、以下を**影響度の高い順**に段階的に実装する。方針は
「GUI を最優先で即表示し、重い処理は準備完了まで非同期に回す」こと。

1. **【最優先】llama-server の起動・待機をバックグラウンド化する。**
   - `LlmClient` に非同期初期化パス（例：`initialize_async(callback, root)`）を設け、
     Whisper と同じパターン（daemon スレッド ＋ `root.after`/`after_idle` で GUI 通知）を適用する。
   - `main.py` は `LlmClient` を「未初期化」状態で構築し、mainloop 開始後にバックグラウンドで
     サーバー起動待ちを行う。準備完了までは LLM 依存機能を「準備中」表示にし、
     フォールバック（janome）で動作を継続する。
   - 既存の同期 `_init_local()` / `_wait_for_server()` はロジックを再利用しつつ、
     呼び出し元をスレッド内に移す。

2. **【高優先】重いライブラリを遅延 import に切り替える。**
   - `boto3` / `botocore` を、実際に AWS バックエンドを使う関数内へ**遅延 import** 化する
     （`transcriber.py`, `aws_utils.py`, `llm_client.py`）。
   - `faster-whisper`（および間接的な CTranslate2）と `dxcam` も、使用直前の遅延 import を検討する。
     ※ import 化にあたり PyInstaller の `hiddenimports` を維持し、ビルド後に実ロードできることを確認する。

3. **【高優先】マイクデバイス列挙を非同期化する。**
   - `_load_mic_devices()` をバックグラウンドスレッドで実行し、完了後に
     `root.after`/`after_idle` でコンボボックスへ反映する。列挙中は既定値/プレースホルダを表示。

4. **【中優先】設定系 GUI タブを遅延構築する。**
   - LLM 設定 / 詳細設定 / メモ出力設定 / About タブを、タブ初回選択時に生成する
     （`ttk.Notebook` の `<<NotebookTabChanged>>` を利用）。録画タブとメモ一覧のみ起動時に構築する。

5. **【中優先】UPX の起動時間への影響を実測する。**
   - `upx=False` でビルドし、起動時間と配布サイズのトレードオフを計測して採否を決める。
   - `--onedir` と `excludes`（matplotlib/scipy/pandas/PIL 除外）は起動に好影響のため**維持**する。

### 検証方法

- 改善前後で、以下 2 シナリオの起動時間（プロセス開始〜ウィンドウ表示 / 〜操作可能）を計測する。
  - (A) LLM ローカルバックエンド未設定
  - (B) LLM ローカルバックエンド設定済み（llama-server 起動あり）
- 特に (B) で、ウィンドウ表示が llama-server 起動待ちにブロックされないことを確認する。
- 既存のテスト（`tests/`）が緑であること。非同期化により競合や未初期化アクセスが
  発生しないことを確認する。

## 検討した代替案

- **llama-server を「初回 LLM 使用時」まで起動しない完全遅延化**：起動は最速になるが、
  初回要約時に待たされ体感が悪化する。→ 起動と並行してバックグラウンド起動する本方針を採用。
- **`_SERVER_START_TIMEOUT` を短縮するだけ**：ブロッキング自体は残るため対症療法にすぎず却下。
- **重いモジュールを別プロセス化**：効果はあるが IPC の複雑さが増し、本課題に対して過剰。
  遅延 import ＋ バックグラウンド化で十分と判断。

## 影響範囲

### 変更（想定）

- `src/screen_audio_recorder/llm_client.py`：非同期初期化パスの追加（同期ロジックは再利用）
- `src/screen_audio_recorder/main.py`：`LlmClient` の非同期初期化への結線
- `src/screen_audio_recorder/transcriber.py` / `aws_utils.py`：`boto3` 等の遅延 import 化
- `src/screen_audio_recorder/screen_capture.py`：`dxcam` 等の遅延 import 化（検討）
- `src/screen_audio_recorder/gui/main_window.py`：マイク列挙の非同期化、タブの遅延構築
- `screen_audio_recorder.spec`：UPX の採否（実測後に決定）

### 影響なし（維持）

- Whisper モデルの非同期ロード、Updater の非同期化、`--onedir` + `excludes` 設定。

## 備考

- 本 ADR は調査と方針の記録であり、実装は後続 PR で段階的に行う。
- 実装は影響度順（1→5）に分割し、各段階で起動時間を実測して効果を確認する。
