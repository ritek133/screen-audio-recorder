# 実装計画: screen-audio-recorder

## 概要

本計画は、設計書・要件定義書に基づき、screen-audio-recorder を段階的に実装するためのタスクリストです。各タスクは前のタスクの成果物を前提として積み上げ、最終的にすべてのコンポーネントを結合します。

技術スタック: Python + tkinter / dxcam / PyAudioWPatch / ffmpeg-python / faster-whisper / janome / hypothesis + pytest

## Tasks

- [x] 1. プロジェクト構造とコアデータモデルのセットアップ
  - `src/screen_audio_recorder/` ディレクトリ構造を作成する
  - `models.py` に `RecordingRegion`、`AudioChunk`、`TranscribeResult`、`Memo`、`MemoPage`、`RecordingMode` を定義する
  - `RecordingRegion.clamp()` メソッドを実装する（最小 320×240、最大ディスプレイ解像度）
  - `pyproject.toml` または `requirements.txt` に依存ライブラリを記載する（dxcam, PyAudioWPatch, ffmpeg-python, faster-whisper, janome, filelock, hypothesis, pytest）
  - `pytest.ini` または `pyproject.toml` に pytest 設定（`integration` マーカー）を追加する
  - _要件: 1.3、3.2、3.3_

  - [ ]* 1.1 `RecordingRegion.clamp()` のプロパティテストを書く
    - **プロパティ 4: スクロールによる領域サイズ変更**
    - スクロール量（正・負・ゼロ）に対して、clamp 後のサイズが [320×240, display_size] の範囲内に収まることを検証する
    - **検証対象: 要件 3.1、3.2、3.3**

- [ ] 2. ストレージ層の実装（MemoStore・FileStore）
  - [x] 2.1 `FileStore` クラスを実装する
    - `~/.screen-audio-recorder/recordings/` ディレクトリを自動作成する
    - タイムスタンプベースのファイル名（`YYYY-MM-DD_HH-MM-SS`）を生成する
    - 書き込みパスが `pathlib.Path.home()` 配下であることを保証する
    - _要件: 1.3、8.2_

  - [ ]* 2.2 ファイル書き込みパス制約のプロパティテストを書く
    - **プロパティ 1: ファイル書き込みパスの制約**
    - 任意のテキスト・テーマ・ファイル名に対して、生成されるパスが `Path.home()` 配下であることを検証する
    - **検証対象: 要件 1.3、8.2**

  - [x] 2.3 `MemoStore` クラスを実装する
    - `~/.screen-audio-recorder/memos.json` への読み書きを実装する（`filelock` で排他制御）
    - `create(text, theme, output_file)` → `Memo` を実装する（UUID4 で ID 生成、UTC タイムスタンプ）
    - `get_all(page, page_size)` → `MemoPage` を実装する（作成日時降順、ページネーション）
    - `get_by_id(memo_id)` → `Memo | None` を実装する
    - `delete(memo_id)` を実装する
    - JSON スキーマバージョン管理（`"version": 1`）を実装する
    - _要件: 8.1、8.2、8.3、9.1、9.5_

  - [ ]* 2.4 `MemoStore` のラウンドトリップ・プロパティテストを書く
    - **プロパティ 11: メモの保存と読み込みのラウンドトリップ**
    - 任意のメモデータを保存後に読み込み、全フィールドが一致することを検証する
    - **検証対象: 要件 8.1**

  - [ ]* 2.5 `MemoStore.delete()` のプロパティテストを書く
    - **プロパティ 12: メモ削除後の不存在**
    - 削除後に `get_by_id()` が `None` を返すことを検証する
    - **検証対象: 要件 8.3**

  - [ ]* 2.6 `MemoStore.get_all()` ソート順のプロパティテストを書く
    - **プロパティ 13: メモ一覧の降順ソート**
    - 任意の順序で作成した複数メモが作成日時降順で返されることを検証する
    - **検証対象: 要件 9.1**

  - [ ]* 2.7 `MemoStore.get_all()` ページネーションのプロパティテストを書く
    - **プロパティ 16: ページネーション適用**
    - N > 100 件のメモに対して、返却件数が `page_size` 以下かつ `total_pages == ceil(N / page_size)` であることを検証する
    - **検証対象: 要件 9.5**

- [x] 3. チェックポイント — ストレージ層のテストをすべてパスさせる
  - すべてのテストが通ることを確認する。疑問点があればユーザーに確認する。

- [ ] 4. テーマ生成サービスの実装
  - [x] 4.1 `ThemeGeneratorService.generate(text)` を実装する
    - `janome.tokenizer.Tokenizer` で形態素解析し、名詞・動詞・形容詞を抽出する
    - 出現頻度上位キーワードを結合し、10 文字を超える場合は先頭 10 文字に切り詰める
    - 入力が空文字列・空白のみ・`None` の場合は `"無題"` を返す
    - _要件: 7.1、7.2、7.3_

  - [ ]* 4.2 テーマ文字数制約のプロパティテストを書く
    - **プロパティ 9: テーマの文字数制約**
    - 任意の非空テキストに対して、生成テーマが 10 文字以内であることを検証する
    - **検証対象: 要件 7.1**

  - [ ]* 4.3 空テキストに対するテーマのプロパティテストを書く
    - **プロパティ 10: 空テキストに対するテーマ**
    - 空文字列・空白のみ・`None` に対して `"無題"` が返されることを検証する
    - **検証対象: 要件 7.3**

- [ ] 5. 音声キャプチャ層の実装（AudioCapture）
  - [x] 5.1 `AudioCapture` クラスを実装する
    - `PyAudioWPatch` の WASAPI ループバックモードでシステム音声を取得する
    - マイク音声を 44100Hz・16bit・ステレオに統一して取得する
    - システム音声とマイク音声を別々の WAV ファイルに録音し、停止後に ffmpeg でマージする
    - **音量自動調整**: 録音中に各コールバックで RMS を累積追跡し、マージ時にシステム音声の平均 RMS ÷ マイクの平均 RMS でゲインを算出。ffmpeg の `volume` フィルタでマイク音声を増幅してからミックスする（ゲイン上限 50 倍）
    - 1 秒ごとに各ストリームの RMS と dB をログ出力する（デバッグ・診断用）
    - `list_mic_devices()` でデバイス一覧を返す
    - `get_audio_queue()` でミックス済み `AudioChunk` キューを返す
    - マイクデバイス利用不可時は `ErrorNotifier.show_warning()` を呼び出し SystemAudio のみで継続する
    - SystemAudio 取得失敗時は `ErrorNotifier.show_warning()` を呼び出し MicAudio のみで継続する
    - 両デバイス利用不可時は `ErrorNotifier.show_error()` を呼び出し録音を中止する
    - _要件: 4.1、4.2、4.3、4.4、4.5、4.6、4.7、4.8_

  - [ ]* 5.2 音声チャンネル独立性のプロパティテストを書く
    - **プロパティ 5: 音声チャンネルの独立性**
    - MicAudio と SystemAudio が独立したバッファに格納され、ミックス前に互いを上書きしないことを検証する
    - **検証対象: 要件 4.3**

  - [ ]* 5.3 音声ミックス完全性のプロパティテストを書く
    - **プロパティ 6: 音声ミックスの完全性**
    - 任意の MicAudio・SystemAudio バッファに対して、ミックス結果のサンプル数・チャンネル数・サンプルレートが一致し、振幅が [-1.0, 1.0] に収まることを検証する
    - **検証対象: 要件 4.4**

  - [ ]* 5.4 デバイス利用不可時の動作ユニットテストを書く
    - マイクデバイス利用不可時に警告が表示され SystemAudio のみで継続することをモックで検証する
    - SystemAudio 取得失敗時に警告が表示され MicAudio のみで継続することをモックで検証する
    - _要件: 4.5、4.6_

- [ ] 6. 画面キャプチャ層の実装（ScreenCapture）
  - [x] 6.1 `ScreenCapture` クラスを実装する
    - `dxcam` を使用して指定 `RecordingRegion` の映像キャプチャを開始・停止する
    - `dxcam` 利用不可時は `mss` にフォールバックする
    - `time.perf_counter()` で 15fps を保証するフレームレート制御を実装する
    - `get_frame_queue()` でフレームキューを返す
    - `set_region()` でリアルタイム領域変更を実装する
    - `get_preview_frame()` でプレビュー用最新フレームを返す
    - `win32gui.GetWindowRect()` でウィンドウ座標を取得する
    - _要件: 2.1、2.2、2.3、2.4、3.4_

  - [ ]* 6.2 録音のみモードで ScreenCapture が起動しないことのユニットテストを書く
    - `RecordingMode.AUDIO_ONLY` 選択時に `ScreenCapture.start()` が呼ばれないことをモックで検証する
    - _要件: 5.1、5.2_

- [ ] 7. エンコーダの実装（VideoEncoder・ErrorNotifier）
  - [x] 7.1 `ErrorNotifier` クラスを実装する
    - `show_warning(title, message)` と `show_error(title, message)` を実装する
    - すべての通知を `root.after_idle()` 経由で GUI スレッドから呼び出す
    - `~/.screen-audio-recorder/app.log` へのログ記録を `logging` モジュールで実装する
    - _要件: 4.5、4.6、6.4、8.4_

  - [x] 7.2 `VideoEncoder` クラスを実装する
    - `_internal/ffmpeg.exe` を同梱バイナリとして `subprocess.Popen` で起動する
    - `start(output_path, fps, resolution)` で ffmpeg プロセスを起動する
    - `write_frame(frame)` でフレームを ffmpeg の stdin にパイプ書き込みする
    - `write_audio(audio_chunk)` で音声チャンクを ffmpeg の stdin にパイプ書き込みする
    - `finish()` でエンコードを完了し OutputFile パスを返す
    - 映像: H.264 — HW エンコーダ自動検出（h264_nvenc → h264_amf → h264_qsv → libx264 ultrafast フォールバック）
    - 音声（MP4）: AAC 128kbps、音声のみ MP3: 192kbps、WAV: PCM
    - ffmpeg エンコードエラー時は `ErrorNotifier.show_error()` を呼び出し一時ファイルを保持する
    - _要件: 2.5、2.6、5.3_

  - [ ]* 7.3 `VideoEncoder` 出力フォーマットのユニットテストを書く
    - 画面録画モードで MP4/H.264 が出力されることをモックで検証する（プロパティ 2）
    - 録音のみモードで MP3 または WAV が出力されることをモックで検証する（プロパティ 7）
    - _要件: 2.5、5.3_

- [x] 8. チェックポイント — キャプチャ・エンコーダ層のテストをすべてパスさせる
  - すべてのテストが通ることを確認する。疑問点があればユーザーに確認する。

- [ ] 9. 文字起こしワーカーの実装（Transcriber・TranscribeWorker）
  - [x] 9.1 `Transcriber` クラスを実装する
    - `faster-whisper` の `WhisperModel` を `model_size="small"`（デフォルト、ユーザー設定で変更可能）、言語 `ja` で初期化する
    - モデルサイズは `LlmSettings.whisper_model_size` から取得する（tiny/base/small/medium/large）
    - モデルファイルを `~/.screen-audio-recorder/models/` にキャッシュする
    - `transcribe(audio_path)` → `TranscribeResult` を同期実装する
    - `transcribe_async(audio_path, callback)` を別スレッドで実行し、完了後に `root.after_idle()` で GUI スレッドに通知する
    - モデルダウンロード失敗時は `ErrorNotifier.show_error()` を呼び出し文字起こし機能を無効化する
    - 文字起こし失敗時は `ErrorNotifier.show_error()` を呼び出し空テキストで `MemoStore.create()` を呼ぶ
    - _要件: 6.1、6.2、6.3、6.4、6.5、6.6_

  - [ ]* 9.2 文字起こし失敗時の空テキスト処理ユニットテストを書く
    - `faster-whisper` をモックして失敗させ、空テキストで `MemoStore.create()` が呼ばれることを検証する
    - _要件: 6.4_

  - [ ]* 9.3 ネットワーク非送信のユニットテストを書く
    - `Transcriber` が外部ネットワーク接続を行わないことを `unittest.mock` でソケットをモックして検証する
    - _要件: 6.5_

- [ ] 10. アプリケーション層の実装（RecorderController・ThemeGeneratorService 結合）
  - [x] 10.1 `RecorderController` クラスを実装する
    - `start_recording(mode, region)` で `ScreenCapture`・`AudioCapture`・`VideoEncoder` を起動する
    - `RecordingMode.AUDIO_ONLY` 時は `ScreenCapture` を起動しない
    - `stop_recording()` で録画・録音を停止し、`VideoEncoder.finish()` → `TranscribeWorker` → `ThemeGeneratorService` → `MemoStore.create()` のパイプラインを実行する
    - `update_region(region)` で `ScreenCapture.set_region()` をリアルタイム呼び出しする
    - スレッドモデル（キャプチャスレッド・エンコードスレッド・文字起こしスレッド）を `threading.Thread` で管理する
    - _要件: 2.1、2.4、5.1、5.2、5.4、6.1、7.4_

  - [x] 10.2 `ThemeGeneratorService` を `RecorderController` のパイプラインに結合する
    - 文字起こし完了後に `ThemeGeneratorService.generate(text)` を呼び出し、テーマを `MemoStore.create()` に渡す
    - _要件: 7.1、7.4_

- [ ] 11. GUI 層の実装（MainWindow・RegionOverlay・MemoListView）
  - [x] 11.1 `MainWindow` を実装する
    - tkinter メインウィンドウを作成し、録画開始・停止ボタン、モード選択（画面+音声 / 音声のみ）、マイクデバイス選択コンボボックスを配置する
    - `RecorderController` を呼び出す UI イベントハンドラを実装する
    - _要件: 2.1、2.4、5.1、5.2_

  - [x] 11.2 `RegionOverlay` を実装する
    - 透過ウィンドウで録画領域を視覚的に表示する
    - マウスホイールスクロールイベントを `RecordingRegion.clamp()` に接続し、リアルタイムでサイズを変更する
    - 変更後の領域を `RecorderController.update_region()` に通知する
    - _要件: 3.1、3.2、3.3、3.4_

  - [x] 11.3 `MemoListView` を実装する
    - `tkinter.ttk.Treeview` でメモ一覧を表示する（作成日時・テーマ・本文先頭 50 文字）
    - メモ選択時に全文を詳細ペインに表示する
    - メモ選択時に対応する OutputFile の再生を開始できるボタンを実装する
    - ページネーション UI（前ページ・次ページボタン）を実装する
    - `MemoStore.get_all()` を呼び出してデータを取得・表示する
    - _要件: 9.1、9.2、9.3、9.4、9.5_

  - [ ]* 11.4 `MemoListView` 表示情報のプロパティテストを書く
    - **プロパティ 14: メモ一覧の表示情報**
    - 任意のメモデータに対して、リスト表示に作成日時・テーマ・本文先頭 50 文字（50 文字未満は全文）が含まれることを検証する
    - **検証対象: 要件 9.2**

  - [ ]* 11.5 `MemoListView` 全文表示のプロパティテストを書く
    - **プロパティ 15: メモ全文表示**
    - 任意のメモを選択したとき、詳細表示のテキストがメモの `body` フィールドと完全一致することを検証する
    - **検証対象: 要件 9.3**

- [x] 12. チェックポイント — GUI 層のテストをすべてパスさせる
  - すべてのテストが通ることを確認する。疑問点があればユーザーに確認する。

- [ ] 13. 統合・結合とエントリーポイントの実装
  - [x] 13.1 `main.py` エントリーポイントを実装する
    - `MainWindow`・`RecorderController`・`MemoStore`・`ErrorNotifier` を初期化して結合する
    - `~/.screen-audio-recorder/` ディレクトリ構造を初回起動時に自動作成する
    - `logging` の設定（`app.log` への出力）を初期化する
    - _要件: 1.1、1.2、1.3_

  - [x] 13.2 PyInstaller 設定ファイル（`.spec`）を作成する
    - `--onedir` モードで `ffmpeg.exe` を `_internal/` に同梱する設定を記述する
    - 管理者権限不要（`uac_admin=False`）を明示する
    - _要件: 1.1_

  - [ ]* 13.3 統合テストを書く（`@pytest.mark.integration` マーカー付き）
    - 実際の ffmpeg バイナリを使用した 5 秒間の短時間録画テストを実装する
    - 実際の `faster-whisper` モデルを使用したテスト用音声ファイルの文字起こしテストを実装する
    - _要件: 2.5、6.1、6.2_

- [x] 14. バージョン情報タブの実装
  - [x] 14.1 `__init__.py` にメタデータ定数を追加する
    - `__version__`、`__author__`、`__company__`、`__license__` を定義する
    - _要件: 13.2、13.3、13.4、13.5_

  - [x] 14.2 `gui/about_tab.py` を実装する
    - アプリ名、バージョン、作者、会社、ライセンス、著作権表示を表示する
    - `__init__.py` のメタデータ定数を参照する
    - _要件: 13.1、13.2、13.3、13.4、13.5、13.6_

  - [x] 14.3 `main_window.py` に「このアプリについて」タブを追加する
    - 「詳細設定」タブの後に配置する
    - _要件: 13.1_

  - [x] 14.4 `pyproject.toml` に `authors` と `license` を追加する
    - パッケージメタデータとして作者・ライセンス情報を記載する

- [x] 15. 最終チェックポイント — すべてのテストをパスさせる
  - `pytest -m "not integration"` ですべての単体・プロパティテストが通ることを確認する。
  - 疑問点があればユーザーに確認する。

- [x] 16. ログ管理機能の実装
  - [x] 16.1 `models.py` に `AppSettings` データクラスを追加する
    - `verbose_logging: bool = False` フィールドを定義する
    - _要件: 12.4_

  - [x] 16.2 `app_settings_store.py` を実装する
    - `load_app_settings()` / `save_app_settings()` で `app_settings.json` の読み書きを行う
    - 設定ファイルパス: `~/Documents/screen-audio-recorder/app_settings.json`
    - _要件: 12.4_

  - [x] 16.3 `gui/advanced_settings_tab.py` を実装する
    - 「詳細ログを有効にする」チェックボックスを配置する
    - 保存ボタンで `save_app_settings()` を呼び出し、再起動後反映の旨を表示する
    - _要件: 12.3、12.5_

  - [x] 16.4 `main_window.py` に「詳細設定」タブを追加する
    - LLM 設定タブの隣に配置する
    - _要件: 12.3_

  - [x] 16.5 `main.py` の `_setup_logging()` を設定ファイル対応に変更する
    - `load_app_settings()` で `verbose_logging` を読み込み、ログレベルを切り替える
    - 通常: ファイル=INFO、コンソール=WARNING / 詳細: ファイル=DEBUG、コンソール=DEBUG
    - _要件: 12.1、12.2、12.7_

  - [x] 16.6 音量ログ・診断ログを DEBUG レベルに変更する
    - `audio_capture.py`: 音量 RMS ログ、ストリーム診断、音量自動調整ログ
    - `recorder_controller.py`: ストリーム開始時刻診断、映像フレーム破棄ログ
    - `video_encoder.py`: 壁時計時間、同期オフセット、映像/音声長さ診断
    - `llm_client.py`: llama-server stdout
    - _要件: 12.6_

  - [x] 16.7 `error_notifier.py` の独自ロギング設定を削除する
    - `_setup_logger()` からハンドラ追加・レベル設定を除去し、ロガー取得のみに変更する
    - ログ設定の一元化（`main.py` に委譲）
    - _要件: 12.7_

## Notes

- `*` が付いたサブタスクはオプションであり、MVP を優先する場合はスキップ可能
- 各タスクは要件の特定サブ要件を参照しており、トレーサビリティを確保している
- プロパティテストは `hypothesis` を使用し、最低 100 回（一部 200 回）のイテレーションを実行する
- 統合テスト（`@pytest.mark.integration`）は CI 環境ではスキップする
- すべてのファイル書き込みは `pathlib.Path.home()` 配下に限定する（プロパティ 1）
- GUI スレッドへの通知はすべて `root.after_idle()` 経由で行う
