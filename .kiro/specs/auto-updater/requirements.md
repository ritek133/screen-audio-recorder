# Requirements Document

## Introduction

Screen Audio Recorder アプリケーションに自動更新機能を追加する。現在はユーザーが手動で .exe ファイルを差し替える運用だが、GitHub Releases を活用しアプリ内から更新確認・ダウンロード・自動置き換え・再起動を行えるようにする。ポータブル配布（インストーラーなし）の特性を考慮し、実行中ファイルの自己置き換え問題をバッチスクリプトで解決する。

配布はハイブリッド方式を採用する:
- **通常更新（exe単体）**: コード変更のみの場合、exe ファイルのみを配布（軽量）
- **フル更新（zip）**: `_internal` フォルダの変更を含む場合、フォルダ全体をzipで配布

リリースアセットの命名規則でアプリが自動判別する。Zip_Asset が存在する場合はフル更新を優先する。

### 前提条件

- GitHub リポジトリは **パブリック** とする（認証トークン不要）。将来プライベート化する場合はトークン設定の要件を追加する。
- 起動時の自動更新チェックは **初回リリースでは実装しない**（手動ボタン押下のみ）。将来のオプション機能として検討する。
- ダウンロードのレジューム（HTTP Range リクエスト）は **初回リリースでは実装しない**。ダウンロード失敗時は最初からやり直す。

## Glossary

- **Updater**: 自動更新機能を提供するモジュール。バージョン確認、ダウンロード、置き換え、再起動の一連の処理を担う
- **GitHub_Releases_API**: GitHub が提供する REST API。リポジトリの最新リリース情報（タグ名、アセット URL 等）を取得するために使用する
- **Current_Version**: アプリケーションに埋め込まれた現在のバージョン文字列（セマンティックバージョニング形式: MAJOR.MINOR.PATCH）
- **Latest_Release**: GitHub Releases API から取得した最新のリリース情報（タグ名とアセット URL を含む）
- **Update_Script**: 実行中の exe を新しいファイルに置き換えるために生成されるバッチスクリプト（.bat ファイル）
- **Backup_Exe**: 更新前に旧 exe を `screen-audio-recorder-vX.Y.Z.exe.bak` の命名規則でリネームして作成するバックアップファイル。ロールバックに使用する
- **Backup_Folder**: フル更新時に旧フォルダを `app-backup-vX.Y.Z` の命名規則でリネームして作成するバックアップ。ロールバックに使用する
- **About_Tab**: 「このアプリについて」タブ。バージョン情報と更新確認ボタンを配置する
- **Exe_Asset**: リリースアセットのうち `screen-audio-recorder-vX.Y.Z.exe` の命名パターンに一致するファイル（通常更新用）
- **Zip_Asset**: リリースアセットのうち `screen-audio-recorder-vX.Y.Z-full.zip` の命名パターンに一致するファイル（フル更新用）。zip のルート直下に exe と `_internal` フォルダが並ぶ構造とする

## Requirements

### Requirement 1: バージョン確認

**User Story:** ユーザーとして、アプリ内から最新バージョンの有無を確認したい。手動でGitHubページを確認する手間を省くため。

#### Acceptance Criteria

1. WHEN ユーザーが「更新を確認」ボタンを押下した場合, THE Updater SHALL GitHub_Releases_API を呼び出し最新リリースのタグ名を取得する。API呼び出しのタイムアウトは30秒とする。
2. WHEN GitHub_Releases_API から最新タグ名を取得した場合, THE Updater SHALL Current_Version とセマンティックバージョニング（MAJOR.MINOR.PATCH）の比較を行い、新しいバージョンが存在するか判定する。プレリリース版（タグにハイフン付きサフィックスを含むもの）は比較対象から除外する。
3. WHEN 新しいバージョンが存在する場合, THE Updater SHALL 最新バージョン番号とリリースノートの先頭200文字をダイアログに表示する。
4. WHEN Current_Version が最新である場合, THE Updater SHALL 最新バージョンである旨のメッセージをダイアログに表示する。
5. IF GitHub_Releases_API への接続がタイムアウトした場合またはHTTPエラーレスポンスを受信した場合, THEN THE Updater SHALL ネットワーク接続の確認を促すエラーメッセージをダイアログに表示する。
6. IF GitHub_Releases_API のレスポンスがセマンティックバージョニング形式のタグ名を含まない場合, THEN THE Updater SHALL 更新情報の解析失敗を示すエラーメッセージをダイアログに表示する。
7. WHILE 更新確認の通信が進行中である場合, THE Updater SHALL 「更新を確認」ボタンを無効化し、通信完了後に再度有効化する。
8. IF アプリケーションが録画中である場合, THEN THE Updater SHALL 「更新を確認」ボタン押下時に「録画中は更新できません。録画を停止してから再度お試しください。」というメッセージを表示し、更新確認を実行しない。

### Requirement 2: ハイブリッド配布判定

**User Story:** ユーザーとして、必要最小限のダウンロードで更新を完了したい。毎回数百MBダウンロードするのは時間がかかるため。

#### Acceptance Criteria

1. WHEN 最新リリースのアセット一覧を取得した場合, THE Updater SHALL アセット名が `screen-audio-recorder-vX.Y.Z-full.zip` パターンに一致する Zip_Asset の有無を確認する。
2. WHEN Zip_Asset と Exe_Asset の両方が同一リリースに存在する場合, THE Updater SHALL Zip_Asset を優先し、フル更新として処理を進める。
3. WHEN Zip_Asset が存在する場合, THE Updater SHALL 更新ダイアログに「フル更新（_internal 含む）」である旨とファイルサイズを表示し、ユーザーに更新種別を明示する。
4. WHEN Zip_Asset が存在せず Exe_Asset（`screen-audio-recorder-vX.Y.Z.exe` パターン）のみ存在する場合, THE Updater SHALL 「通常更新（アプリ本体のみ）」として処理を進める。
5. IF リリースに Exe_Asset も Zip_Asset も存在しない場合, THEN THE Updater SHALL 「更新ファイルが見つかりません。」というエラーメッセージを表示する。
6. WHEN フル更新を実行する場合, THE Updater SHALL zip をダウンロードし、展開後にアプリフォルダ全体（exe + _internal）を置き換える。zip のルート直下に exe と `_internal` フォルダが並ぶ構造を期待する。
7. WHEN 通常更新を実行する場合, THE Updater SHALL exe ファイルのみをダウンロードし、既存の exe を置き換える（_internal はそのまま維持）。
8. IF フル更新の zip 展開後にルート直下に exe ファイルが存在しない場合, THEN THE Updater SHALL 「更新ファイルの構造が不正です。」というエラーメッセージを表示し、更新処理を中止する。

### Requirement 3: 更新ダウンロードと進捗表示

**User Story:** ユーザーとして、ダウンロードの進捗をリアルタイムで確認したい。あとどのくらい待てば良いか把握するため。

#### Acceptance Criteria

1. WHEN ユーザーが更新ダイアログで「更新する」ボタンを押下した場合, THE Updater SHALL ダウンロードを一時ディレクトリに開始する。
2. WHILE ダウンロードが進行中である場合, THE Updater SHALL プログレスバーでダウンロード進捗率を整数パーセント（0〜100%）でリアルタイム表示する。
3. WHILE ダウンロードが進行中である場合, THE Updater SHALL ダウンロード済みサイズ / 総サイズ（例: 「125 MB / 400 MB」）をラベルで動的表示する。
4. WHILE ダウンロードが進行中である場合, THE Updater SHALL 現在のダウンロード速度（例: 「12.5 MB/s」）を動的表示する。
5. WHILE ダウンロードが進行中である場合, THE Updater SHALL 推定残り時間（例: 「残り約 22 秒」）を動的表示する。
6. THE Updater SHALL プログレスバーおよび各ラベルの表示を 500 ミリ秒ごとに更新する。
7. WHILE ダウンロードが進行中である場合, THE Updater SHALL 「キャンセル」ボタンを有効状態で表示する。
8. WHEN ユーザーが「キャンセル」ボタンを押下した場合, THE Updater SHALL 5秒以内にダウンロードを中断し、一時ファイルを削除し、更新ダイアログを閉じる。
9. IF ダウンロード中にネットワークエラーが発生した場合, THEN THE Updater SHALL 一時ファイルを削除し、ネットワーク接続の確認を促すエラーメッセージを表示する。
10. WHEN ダウンロードが完了した場合, THE Updater SHALL ダウンロードしたファイルのサイズが GitHub Releases で報告されたアセットサイズと一致することを検証する。
11. IF ダウンロードしたファイルのサイズが不一致である場合, THEN THE Updater SHALL 一時ファイルを削除し、ファイル破損の可能性と再試行を促すエラーメッセージを表示する。
12. IF ダウンロード開始時に一時ディレクトリのあるドライブの空き容量がダウンロード対象ファイルサイズの2倍未満である場合, THEN THE Updater SHALL ダウンロードを開始せず、ディスク空き容量不足を示すエラーメッセージを表示する。
13. WHILE ダウンロードが進行中である場合, IF ユーザーがアプリケーションを終了しようとした場合, THEN THE Updater SHALL 「ダウンロード中です。終了してもよろしいですか？」という確認ダイアログを表示し、ユーザーが承諾した場合のみ処理を中断してアプリケーションを終了する。

### Requirement 4: 自己置き換えと再起動

**User Story:** ユーザーとして、ダウンロード完了後に自動的にアプリが更新・再起動されてほしい。手動でファイルを差し替える作業を無くすため。

#### Acceptance Criteria

1. WHEN 通常更新（exe単体）のダウンロードとファイル検証が成功した場合, THE Updater SHALL 現在実行中の exe ファイルを `screen-audio-recorder-vX.Y.Z.exe.bak`（X.Y.Z は Current_Version）としてリネームし Backup_Exe を作成する。
2. WHEN フル更新（zip）のダウンロードとファイル検証が成功した場合, THE Updater SHALL zipを一時ディレクトリに展開し、現在のアプリフォルダを `app-backup-vX.Y.Z`（X.Y.Z は Current_Version）としてリネームし Backup_Folder を作成する。
3. WHEN バックアップの作成が完了した場合, THE Updater SHALL Update_Script（バッチファイル）を一時ディレクトリに生成する。
4. THE Update_Script SHALL 以下の手順を順序通りに実行する: (a) 現在のアプリプロセスの終了を最大60秒間待機する (b) 新しいファイルを元のパスに移動する（通常更新: exe のみ、フル更新: フォルダ全体） (c) 新しい exe を起動する (d) Update_Script 自身を削除する。
5. WHEN Update_Script の生成が完了した場合, THE Updater SHALL Update_Script を起動し、アプリケーションを終了する。
6. IF Update_Script の実行中に新しいファイルの移動に失敗した場合, THEN THE Update_Script SHALL バックアップを元のパスにリネームして復元し、復元した旧バージョンの exe を起動する。
7. IF バックアップのリネームに失敗した場合, THEN THE Updater SHALL 更新処理を中止し「更新の準備に失敗しました。管理者権限で再試行してください。」というエラーメッセージを表示する。
8. IF Update_Script の実行中にプロセス終了待機が60秒を超過した場合, THEN THE Update_Script SHALL バックアップを元のパスにリネームして復元し、更新処理を中止する。
9. IF Update_Script の生成に失敗した場合, THEN THE Updater SHALL バックアップを元のファイル名にリネームして復元し、「更新スクリプトの生成に失敗しました。」というエラーメッセージを表示する。

### Requirement 5: ロールバック

**User Story:** ユーザーとして、更新後に問題が発生した場合に以前のバージョンに戻したい。更新による業務中断を最小化するため。

#### Acceptance Criteria

1. WHEN アプリケーションが起動した場合, THE Updater SHALL 同一ディレクトリにバックアップ（`*.exe.bak` または `app-backup-v*` フォルダ）が存在するか確認する。
2. WHILE バックアップが同一ディレクトリに存在する場合, THE About_Tab SHALL 「前のバージョンに戻す」ボタンを表示し、バックアップのファイル名からバージョン文字列を抽出して表示する。
3. WHEN ユーザーが「前のバージョンに戻す」ボタンを押下した場合, THE Updater SHALL バックアップのバージョン文字列を含む確認ダイアログ「バージョン X.Y.Z に戻しますか？」を表示する。
4. WHEN ユーザーが確認ダイアログで「いいえ」を選択した場合, THE Updater SHALL ダイアログを閉じ、ロールバック処理を実行しない。
5. WHEN ユーザーが確認ダイアログで「はい」を選択した場合, THE Updater SHALL ロールバック用の Update_Script を一時ディレクトリに生成し、バックアップを現在のパスに復元する処理を実行する。
6. IF ロールバック用 Update_Script の実行中にバックアップの移動に失敗した場合, THEN THE Update_Script SHALL 現在のファイルをそのまま維持し、エラーを示すログファイルを同一ディレクトリに出力する。
7. WHEN 次回の更新が正常に完了した場合, THE Updater SHALL 同一ディレクトリに残存する古いバックアップを削除する。
8. IF アプリケーションが録画中に「前のバージョンに戻す」ボタンが押下された場合, THEN THE Updater SHALL 「録画中はロールバックできません。録画を停止してから再度お試しください。」というメッセージを表示し、処理を実行しない。

### Requirement 6: 更新ステータス表示

**User Story:** ユーザーとして、更新処理の各段階が今どこまで進んでいるか把握したい。処理が止まっていないか確認するため。

#### Acceptance Criteria

1. THE About_Tab SHALL 更新ステータス表示エリアを「更新を確認」ボタンの下部に配置する。
2. WHILE 更新確認中である場合, THE About_Tab SHALL ステータスに「🔍 最新バージョンを確認中...」と表示し、テキスト色をグレーにする。
3. WHEN 新しいバージョンが見つかった場合, THE About_Tab SHALL ステータスに「✅ 新しいバージョン vX.Y.Z が利用可能です」と表示し、テキスト色を緑にする。
4. WHILE ダウンロード中である場合, THE About_Tab SHALL ステータスに「⬇️ ダウンロード中... (XX%)」と表示し、テキスト色を青にし、パーセンテージを500ミリ秒ごとに更新する。
5. WHILE 更新適用処理中である場合, THE About_Tab SHALL ステータスに「🔄 更新を適用中...」と表示し、テキスト色をグレーにする。
6. WHEN 更新処理が正常に完了し再起動直前である場合, THE About_Tab SHALL ステータスに「✅ 更新完了。再起動します...」と表示し、テキスト色を緑にする。
7. IF 更新処理中にエラーが発生した場合, THEN THE About_Tab SHALL ステータスに「❌ エラー: [エラー内容の要約]」と表示し、テキスト色を赤にする。
8. WHEN 最新バージョンであることが確認された場合, THE About_Tab SHALL ステータスに「✅ 最新バージョンです (vX.Y.Z)」と表示し、テキスト色を緑にする。

### Requirement 7: UI 統合

**User Story:** ユーザーとして、更新機能がアプリの既存UIに自然に統合されていてほしい。使い慣れた画面から操作できるため。

#### Acceptance Criteria

1. THE About_Tab SHALL 「更新を確認」ボタンをバージョン情報の下部に配置する。
2. THE Updater SHALL すべての更新処理（バージョン確認、ダウンロード、ファイル操作）をバックグラウンドスレッドで実行し、GUI スレッドをブロックしない（更新処理中もボタン操作やウィンドウ移動が200ミリ秒以内に応答すること）。
3. WHILE ダウンロードが進行中である場合, THE About_Tab SHALL ダウンロード進捗ダイアログをモーダルウィンドウとして表示する。
4. IF 更新処理中にエラーが発生した場合, THEN THE About_Tab SHALL エラー内容をダイアログで通知し、「更新を確認」ボタンを有効状態に復元する。
5. WHILE 録画中である場合, THE About_Tab SHALL 「更新を確認」ボタンをグレーアウトし、ツールチップに「録画中は更新できません」と表示する。

### Requirement 8: セマンティックバージョニング解析

**User Story:** ユーザーとして、バージョンの大小関係が正確に判定されてほしい。正しく更新が提供されるため。

#### Acceptance Criteria

1. THE Updater SHALL バージョン文字列を MAJOR.MINOR.PATCH 形式（各要素は非負整数）として解析する。
2. WHEN GitHub のタグ名に "v" または "V" プレフィックスが付いている場合, THE Updater SHALL プレフィックスを大文字小文字問わず除去してからバージョン比較を行う。
3. THE Updater SHALL MAJOR → MINOR → PATCH の順に数値比較を行い、左の要素が大きいほど新しいバージョンと判定する。
4. IF バージョン文字列が MAJOR.MINOR.PATCH 形式に合致しない場合, THEN THE Updater SHALL そのリリースを無視し、エラーログを記録する。
5. WHEN Current_Version と Latest_Release のバージョンが完全に一致する場合, THE Updater SHALL 「最新バージョンです」と判定する。
6. IF タグ名にプレリリースサフィックス（ハイフン以降の文字列、例: 1.2.0-beta）が含まれる場合, THEN THE Updater SHALL そのリリースを更新候補から除外する。

### Requirement 9: セキュリティとネットワーク

**User Story:** ユーザーとして、更新プロセスが安全に行われてほしい。悪意のあるファイルによるシステム侵害を防ぐため。

#### Acceptance Criteria

1. THE Updater SHALL すべての GitHub API 通信および exe/zip ダウンロードに HTTPS を使用する。
2. THE Updater SHALL GitHub API リクエストに 30 秒のタイムアウトを設定する。
3. THE Updater SHALL exe/zip ダウンロードに 600 秒のタイムアウトを設定する（フル更新の大容量ファイルを考慮）。
4. WHEN プロキシ環境下で実行されている場合, THE Updater SHALL システムのプロキシ設定（環境変数 HTTP_PROXY / HTTPS_PROXY）を自動的に利用する。
5. THE Updater SHALL ダウンロードしたファイルを一時ディレクトリに保存し、検証完了後に移動する。
6. IF タイムアウトが発生した場合, THEN THE Updater SHALL 進行中のリクエストを中止し、タイムアウトした旨のエラーメッセージをユーザーに表示する。
7. IF SSL/TLS 証明書の検証に失敗した場合, THEN THE Updater SHALL 接続を中止し、セキュリティエラーが発生した旨のメッセージをユーザーに表示する。
