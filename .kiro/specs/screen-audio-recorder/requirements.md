# 要件定義書

## はじめに

本機能は、Windows ローカル環境で動作する画面・音声録画アプリケーションです。管理者権限なしでデプロイおよび実行が可能で、マイク音声とシステム音声の両方を録音できます。録画サイズはユーザーが自由に調整でき、音声のみの録音モードも備えます。録音した音声は自動で文字起こしされ、メモとして保存・一覧表示できます。各メモには文字起こし内容をもとに 10 文字以内のテーマが自動付与されます。

---

## 用語集

- **Recorder**: 画面・音声の録画・録音を制御するコンポーネント
- **ScreenCapture**: 画面映像のキャプチャを担当するサブシステム
- **AudioCapture**: マイク音声およびシステム音声の取得を担当するサブシステム
- **Transcriber**: 録音済み音声をテキストに変換するコンポーネント
- **MemoStore**: 文字起こし結果をメモとして保存・管理するコンポーネント
- **ThemeGenerator**: 文字起こしテキストをもとにメモのテーマを自動生成するコンポーネント
- **MemoList**: メモを時間軸順に一覧表示する UI コンポーネント
- **RecordingRegion**: ユーザーが指定する録画対象の画面領域
- **SystemAudio**: OS が出力するスピーカー・ヘッドフォン等の音声
- **MicAudio**: 接続されたマイクデバイスから取得する音声
- **OutputFile**: 録画・録音の結果として生成されるファイル

---

## 要件

### 要件 1: アプリケーションの起動と権限

**ユーザーストーリー:** 一般ユーザーとして、管理者権限なしにアプリをインストール・起動したい。そうすることで、制限された企業環境でも利用できる。

#### 受け入れ基準

1. THE Recorder SHALL 管理者権限（Administrator 権限）を要求せずに起動できる。
2. THE Recorder SHALL Windows 10 バージョン 1903 以降および Windows 11 上で動作する。
3. THE Recorder SHALL ユーザーのホームディレクトリ配下にのみファイルを書き込む。
4. THE Recorder SHALL 起動時にコンソールウィンドウ（CMD）を表示しない。PyInstaller の `console=False` および `ShowWindow(hwnd, 0)` で抑制する。
5. THE Recorder SHALL 起動時にメインウィンドウを先行表示し、Whisper モデルのバックグラウンドロード中はステータスバーに「モデル読み込み中...」と表示し、録画ボタンを無効化する。ロード完了後に録画ボタンを有効化する。
6. THE Recorder SHALL すべての子プロセス（ffmpeg、llama-server 等）を `CREATE_NO_WINDOW` フラグ付きで起動し、コンソールウィンドウを表示しない。

---

### 要件 2: 画面録画

**ユーザーストーリー:** ユーザーとして、PC の画面を録画したい。そうすることで、作業内容を映像として記録できる。

#### 受け入れ基準

1. WHEN ユーザーが録画開始を指示したとき、THE ScreenCapture SHALL 指定された RecordingRegion の映像キャプチャを開始する。
2. THE ScreenCapture SHALL 全画面、または任意のウィンドウを RecordingRegion として選択できる。
3. WHILE 録画中、THE ScreenCapture SHALL フレームレートを最低 15 fps 以上で維持する。
4. WHEN ユーザーが録画停止を指示したとき、THE ScreenCapture SHALL 録画を終了し OutputFile を生成する。
5. THE Recorder SHALL 録画結果を MP4 形式（H.264 エンコード）で OutputFile として保存する。
6. THE VideoEncoder SHALL ハードウェアエンコーダを自動検出し、利用可能な場合は優先的に使用する。検出優先順位は h264_nvenc（NVIDIA）→ h264_amf（AMD）→ h264_qsv（Intel）→ libx264（CPU フォールバック）とする。

---

### 要件 3: 録画サイズの調整

**ユーザーストーリー:** ユーザーとして、録画する画面領域のサイズをスクロール操作で自由に変更したい。そうすることで、必要な範囲だけを録画できる。

#### 受け入れ基準

1. WHEN ユーザーが RecordingRegion 上でスクロール操作を行ったとき、THE ScreenCapture SHALL RecordingRegion のサイズをスクロール量に応じて拡大または縮小する。
2. THE ScreenCapture SHALL RecordingRegion の最小サイズを 320×240 ピクセルとする。
3. THE ScreenCapture SHALL RecordingRegion の最大サイズをディスプレイの解像度と同一とする。
4. WHILE ユーザーが RecordingRegion のサイズを変更中、THE ScreenCapture SHALL 変更後の領域をリアルタイムでプレビュー表示する。

---

### 要件 4: 音声録音（マイク・システム音声）

**ユーザーストーリー:** ユーザーとして、マイク音声とシステム音声の両方を録音したい。そうすることで、自分の声と PC の出力音を同時に記録できる。

#### 受け入れ基準

1. WHEN 録画または録音が開始されたとき、THE AudioCapture SHALL MicAudio の録音を開始する。
2. WHEN 録画または録音が開始されたとき、THE AudioCapture SHALL SystemAudio の録音を開始する。
3. THE AudioCapture SHALL MicAudio と SystemAudio を独立したチャンネルとして取得する。
4. THE Recorder SHALL MicAudio と SystemAudio をミックスして OutputFile に含める。
5. THE AudioCapture SHALL 録音中に MicAudio と SystemAudio の平均音量（RMS）を追跡し、ミックス時に音量差を自動補正する（音量自動調整）。
6. THE AudioCapture SHALL 音量自動調整のゲイン上限を 50 倍（約 34 dB）とし、過度なノイズ増幅を防止する。
7. IF 指定されたマイクデバイスが利用不可の場合、THEN THE AudioCapture SHALL ユーザーに警告を表示し、SystemAudio のみで録音を継続する。
8. IF SystemAudio の取得に失敗した場合、THEN THE AudioCapture SHALL ユーザーに警告を表示し、MicAudio のみで録音を継続する。

---

### 要件 5: 録音のみモード

**ユーザーストーリー:** ユーザーとして、画面録画なしで音声のみを録音したい。そうすることで、会議や講義の音声を軽量なファイルとして保存できる。

#### 受け入れ基準

1. THE Recorder SHALL 画面録画を行わず音声のみを録音する「録音のみモード」を提供する。
2. WHEN ユーザーが録音のみモードを選択したとき、THE Recorder SHALL ScreenCapture を起動せずに AudioCapture のみを開始する。
3. THE Recorder SHALL 録音のみモードの結果を MP3 または WAV 形式で OutputFile として保存する。
4. WHEN 録音のみモードで録音が停止されたとき、THE Recorder SHALL OutputFile を生成し Transcriber に渡す。

---

### 要件 6: 音声の文字起こし

**ユーザーストーリー:** ユーザーとして、録音した音声を自動でテキストに変換したい。そうすることで、内容を後から検索・参照できる。

#### 受け入れ基準

1. WHEN OutputFile が生成されたとき、THE Transcriber SHALL 音声をテキストに変換する処理を開始する。
2. THE Transcriber SHALL 日本語音声を文字起こしの対象言語としてサポートする。
3. WHEN 文字起こしが完了したとき、THE Transcriber SHALL 変換結果テキストを MemoStore に渡す。
4. IF 文字起こし処理が失敗した場合、THEN THE Transcriber SHALL エラー内容をユーザーに表示し、空のテキストで MemoStore にメモを作成する。
5. THE Transcriber SHALL 文字起こし処理をローカル環境のみで完結させ、外部サーバーに音声データを送信しない。
6. THE Transcriber SHALL Whisper モデルサイズ（tiny/base/small/medium/large）をユーザーが設定から選択可能とする。デフォルトは small とする。

---

### 要件 7: メモの自動テーマ生成

**ユーザーストーリー:** ユーザーとして、文字起こし内容をもとにメモのテーマを自動で付けてほしい。そうすることで、後から内容を素早く把握できる。

#### 受け入れ基準

1. WHEN Transcriber から変換結果テキストを受け取ったとき、THE ThemeGenerator SHALL テキストの内容を要約した 10 文字以内のテーマ文字列を生成する。
2. THE ThemeGenerator SHALL 生成するテーマを日本語とする。
3. IF 変換結果テキストが空の場合、THEN THE ThemeGenerator SHALL テーマを「無題」とする。
4. WHEN テーマが生成されたとき、THE ThemeGenerator SHALL テーマを MemoStore に渡す。

---

### 要件 10: LLM によるテキスト後処理

**ユーザーストーリー:** ユーザーとして、文字起こし結果の句読点・誤字脱字を自動修正し、内容の要約を生成し、テーマ命名も自然な日本語で行ってほしい。そうすることで、メモの品質と可読性が向上する。

#### 受け入れ基準

1. WHEN Transcriber から変換結果テキストを受け取ったとき、THE TextPostProcessor SHALL LLM を使用してテキストの句読点補完・誤字脱字修正を行う。
2. WHEN 修正済みテキストが生成されたとき、THE TextPostProcessor SHALL LLM を使用して内容の要約テキストを生成する。
3. WHEN 修正済みテキストが生成されたとき、THE TextPostProcessor SHALL LLM を使用して 10 文字以内の日本語テーマを生成する。
4. THE TextPostProcessor SHALL ローカル LLM 推論（llama-cpp-python）を第一選択として使用する。
5. THE TextPostProcessor SHALL オプションとして OpenAI 互換 API（オンプレ推論基盤）への接続をサポートする。
6. IF LLM 推論が利用不可または失敗した場合、THEN THE TextPostProcessor SHALL 従来の janome ベースのテーマ生成にフォールバックし、テキストは未修正のまま使用する。
7. THE TextPostProcessor SHALL 各タスク（テーマ生成・テキスト修正・要約生成）のプロンプトをユーザーが設定ファイルからカスタマイズ可能とする。

---

### 要件 11: LLM 設定 UI

**ユーザーストーリー:** ユーザーとして、LLM の推論バックエンドやプロンプトを GUI から設定したい。そうすることで、環境に合わせた柔軟な運用ができる。

#### 受け入れ基準

1. THE MainWindow SHALL LLM 設定用のタブを提供する。
2. THE 設定タブ SHALL 推論バックエンドの選択（ローカル / オンプレ API）を提供する。
3. THE 設定タブ SHALL ローカルモデルのパスまたはモデル名の設定を提供する。
4. THE 設定タブ SHALL オンプレ API のエンドポイント URL の設定を提供する。
5. THE 設定タブ SHALL 各タスク（テーマ生成・テキスト修正・要約生成）のプロンプトテンプレートの編集を提供する。
6. THE 設定タブ SHALL 設定を JSON ファイルに永続化する。
7. THE 設定タブ SHALL 設定変更を即座に反映する（アプリ再起動不要）。
8. THE 設定タブ SHALL Whisper モデルサイズの選択（tiny/base/small/medium/large）を提供する。

---

### 要件 13: バージョン情報の表示

**ユーザーストーリー:** ユーザーとして、アプリの作者・会社・バージョンなどの情報を確認したい。そうすることで、利用しているアプリの出所やバージョンを把握できる。

#### 受け入れ基準

1. THE MainWindow SHALL 「このアプリについて」タブを提供する。
2. THE 「このアプリについて」タブ SHALL アプリケーション名を表示する。
3. THE 「このアプリについて」タブ SHALL バージョン番号を表示する。
4. THE 「このアプリについて」タブ SHALL 作者名（Taicheng Huang）を表示する。
5. THE 「このアプリについて」タブ SHALL 会社名（AKKODiSコンサルティング株式会社）を表示する。
6. THE 「このアプリについて」タブ SHALL 著作権表示を表示する。

---

### 要件 8: メモの保存

**ユーザーストーリー:** ユーザーとして、文字起こし結果をメモとして保存したい。そうすることで、録音内容を後から参照できる。

#### 受け入れ基準

1. WHEN MemoStore がテキストとテーマを受け取ったとき、THE MemoStore SHALL メモを作成日時・テーマ・本文・OutputFile へのパスとともに保存する。
2. THE MemoStore SHALL メモをローカルファイルシステム上のユーザーホームディレクトリ配下に保存する。
3. THE MemoStore SHALL 保存済みメモを削除する機能を提供する。
4. IF メモの保存に失敗した場合、THEN THE MemoStore SHALL エラー内容をユーザーに表示する。

---

### 要件 9: メモの時間軸一覧表示

**ユーザーストーリー:** ユーザーとして、保存されたメモを時間軸で一覧表示したい。そうすることで、過去の録音内容を時系列で振り返ることができる。

#### 受け入れ基準

1. THE MemoList SHALL 保存済みの全メモを作成日時の降順で一覧表示する。
2. THE MemoList SHALL 各メモの作成日時・テーマ・本文の先頭 50 文字をリスト上に表示する。
3. WHEN ユーザーがメモを選択したとき、THE MemoList SHALL そのメモの全文を表示する。
4. WHEN ユーザーがメモを選択したとき、THE MemoList SHALL 対応する OutputFile の再生を開始できる。
5. THE MemoList SHALL 表示件数が 100 件を超えた場合にページネーションまたは仮想スクロールを適用する。

---

### 要件 12: ログ管理

**ユーザーストーリー:** ユーザーとして、通常運用時はログ出力を最小限に抑え、バグ調査時にのみ詳細ログを有効にしたい。そうすることで、通常時のパフォーマンスとログファイルサイズを抑えつつ、問題発生時に十分な情報を得られる。

#### 受け入れ基準

1. THE Recorder SHALL 通常運用時にファイルログを INFO レベル、コンソールログを WARNING レベルで出力する。
2. THE Recorder SHALL 詳細ログモード有効時にファイルログ・コンソールログ共に DEBUG レベルで出力する。
3. THE MainWindow SHALL 「詳細設定」タブを提供し、詳細ログの有効/無効を切り替えるトグルを含める。
4. THE Recorder SHALL 詳細ログ設定を `app_settings.json` に永続化する。
5. THE Recorder SHALL ログレベルの変更をアプリケーション再起動後に反映する。
6. THE Recorder SHALL 音量 RMS ログ、ストリーム診断ログ、同期オフセットログを DEBUG レベルとして分類する。
7. THE Recorder SHALL ログ設定を `main.py` の `_setup_logging()` に一元化し、各モジュールが独自にハンドラを追加しない。
