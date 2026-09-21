# ADR-004: メモエクスポート機能（HTML 継続出力と設定タブ）

## ステータス

決定済み（Accepted）

## 日付

2026-09-21

## コンテキスト

録音メモは要約が約 1,000 字、全文が 10,000 字超になり、件数も数百件に達する。
これをアプリの tkinter UI 内で閲覧するのは負荷が高く読みにくい（ADR-003 参照）。
そこで、メモをアプリ外部の見やすい形式へ**エクスポートして閲覧する**機能を追加する。

要件は以下。

- メモが追加・更新されるたびに、出力先を**即時（イベント駆動）で更新する**（継続出力）
- 出力形式は複数を想定（HTML、将来的に OneNote 等）
- エクスポート機能の**設定をアプリの新しいタブで行える**
- HTML はローカルで完結し、インターネット公開はしない

本 ADR は、この機能の全体設計を定める。ADR-003 で決定した閲覧 UI（案B: 2ペイン、
全文折り畳み）を、この継続出力の出力テンプレートとして流用する。

### 既存コードの調査結果（設計の前提）

- **メモの永続化**: `memo_store.py` の `MemoStore` が `~/Documents/screen-audio-recorder/memos.json`
  への全読み書きを担当。書き込みは `create` / `update_memo` / `update_theme` / `delete` の
  4 メソッドで、いずれも唯一のファイル書き込み口 `_save_raw()` を経由する。
- **既存の通知の限界**: メモ保存通知は `RecorderController.set_on_memo_saved` の 1 つのみで、
  **新規録画経路でしか発火しない**。GUI の再処理・再文字起こし・テーマ編集・削除では発火せず、
  各ハンドラが直接 `memo_list_view.refresh()` を呼んでいる。汎用のイベント機構は存在しない。
  → この既存コールバックをフックにすると、編集・再処理による更新を取りこぼす。
- **設定の仕組み**: 「dataclass（`models.py`）＋ `*_settings_store.py`（JSON 永続化）＋ GUI タブ」の
  3 層パターンで統一。保存先は `~/Documents/screen-audio-recorder/<name>.json`（機能ごと 1 ファイル）。
  最小テンプレは `app_settings_store.py` + `advanced_settings_tab.py`。
- **タブ追加**: `MainWindow._build_ui()` 内で「遅延 import → タブ生成 → `notebook.add(tab.frame, text=...)`」。
  各タブは `self.frame` を公開し、保存は `_on_save` → `save_*()` → コールバックの順。

## 決定

### スコープ（第1弾）

- **HTML エクスポートのみを実装する。** OneNote 等の他形式は将来フェーズ（後述）。
- **メモ更新イベントで即エクスポート**（イベント駆動、短いデバウンスあり）。
- エクスポート設定用の**新タブ `MemoExportSettingsTab`** を追加する。
- HTML は**ローカル完結**（インターネット公開なし）。

### アーキテクチャ

```
[MemoStore] --(listener 発火)--> [ExportManager] --(有効な出力先へ)--> [HtmlExporter]
   create/update_memo/                                              (memos.json を
   update_theme/delete                                              読み込む HTML を出力)
```

1. **`MemoStore` にリスナー機構を追加する**（既存の `set_on_memo_saved` は使わない）。
   - `add_listener(callback)` を新設し、`create` / `update_memo` / `update_theme` / `delete` の
     各 `_save_raw()` 呼び出し後に発火させる。これにより**全経路**
     （新規録画・再処理・再文字起こし・テーマ編集・削除）を漏れなく検知できる。
   - コールバックは「変更があった」ことを通知する（引数は最小限。詳細出力は出力側で memos.json を再読込）。
2. **`ExportManager`（新規）** がリスナーを購読し、有効な出力形式へ委譲する。
   - **デバウンス**: 短時間に複数更新が来た場合、数百 ms〜数秒でまとめて 1 回出力する
     （連続更新時の過剰な書き込みを防ぐ）。
   - 出力は GUI をブロックしないよう、別スレッド or `after` で非同期実行する。
3. **`HtmlExporter`（新規）** が出力を担う。
   - 方式は **自己完結 HTML**（データ埋め込み）を採用。`memos.json` の内容を HTML 内に
     埋め込んだ単一ファイルを生成し、**ダブルクリックで開ける**ようにする
     （`file://` でも動作。ローカルサーバー不要）。テンプレートは ADR-003 の案B を流用。
   - 出力先は設定で指定（既定は `~/Documents/screen-audio-recorder/export/memo-viewer.html` 等の相対的な既定）。

### データモデルと設定

`models.py` に `ExportSettings`（dataclass）を追加し、`export_settings_store.py` を新設する
（`app_settings_store.py` と同じ流儀、保存先 `~/Documents/screen-audio-recorder/export_settings.json`）。

想定フィールド（第1弾）:

| フィールド | 型 | 既定 | 意味 |
|-----------|----|------|------|
| `html_enabled` | bool | False | HTML 継続出力の有効/無効 |
| `output_dir` | str | ""（空=既定を後段で解決） | 出力先ディレクトリ。絶対フルパスはハードコードしない |
| `include_output_file_path` | bool | False | `output_file`（ローカルパス）を HTML に含めるか。既定は含めない |

- `output_file` はローカルフルパスを含むため、**既定では HTML に出力しない**（プライバシー保護）。
- `body`・`summary` が空のメモは出力対象から除外する（ADR-003 と一貫）。

### 設定タブ

`gui/memo_export_settings_tab.py` に `MemoExportSettingsTab` を新設し、`advanced_settings_tab.py` を
雛形にする。`MainWindow._build_ui()` に「遅延 import → 生成 → `notebook.add(..., text="メモ出力")`」を
追加する。

- UI: HTML 出力の有効/無効チェック、出力先の選択（`filedialog`）、`output_file` 含めるかのチェック、
  「今すぐ出力」ボタン、保存ボタン。
- 保存時は `save_export_settings()` を呼び、`ExportManager` に新設定を反映する。

## 継続出力の動作

- `html_enabled = True` のとき、メモの追加/更新/削除のたびに `ExportManager` が発火し、
  デバウンス後に `HtmlExporter` が最新の memos.json から HTML を再生成する。
- 出力は原子的に行う（テンポラリへ書いてから置換）。閲覧中のファイルが壊れないようにする。
- 出力失敗（ディスク・権限など）はログに記録し、アプリ本体の動作（録画・保存）は妨げない。

## 検討した代替案

- **既存 `set_on_memo_saved` を流用**: 最小変更だが、録画経路でしか発火せず編集・再処理を取りこぼすため却下。
- **memos.json のファイル監視（watchdog 等）**: 外部依存が増え、書き込み途中の読み取り競合が起きやすいため却下。
  アプリ内リスナーの方が確実で軽量。
- **サーバー配信型 HTML（`python -m http.server`）**: 起動フォルダ依存で 404 が起きやすく、常駐も必要。
  ダブルクリックで開ける自己完結 HTML の方が「公開しない・すぐ開ける」要件に合う。

## 影響範囲

### 新規

- `src/screen_audio_recorder/export/__init__.py`
- `src/screen_audio_recorder/export/export_manager.py`（リスナー購読・デバウンス・委譲）
- `src/screen_audio_recorder/export/html_exporter.py`（自己完結 HTML 生成。案B テンプレート）
- `src/screen_audio_recorder/export_settings_store.py`（`export_settings.json` の読み書き）
- `src/screen_audio_recorder/gui/memo_export_settings_tab.py`（設定タブ）
- テスト: `tests/test_export_manager.py`, `tests/test_html_exporter.py`,
  `tests/test_export_settings_store.py`, `tests/test_memo_export_settings_tab.py`

### 変更

- `src/screen_audio_recorder/memo_store.py`: リスナー機構（`add_listener` と各書き込み後の発火）を追加
- `src/screen_audio_recorder/models.py`: `ExportSettings` dataclass を追加
- `src/screen_audio_recorder/gui/main_window.py`: 新タブの登録、`ExportManager` の生成・配線
- `src/screen_audio_recorder/main.py`: `ExportManager` を初期化し `MemoStore` に購読登録（結線）

## 将来フェーズ（本 ADR のスコープ外）

- **OneNote 連携**: OneNote はローカル生成が困難で、実質 Microsoft Graph API（OAuth ログイン＋
  ネットワーク通信）が必要。「公開しない・ローカル完結」方針と衝突するため、別 ADR で認証・
  レート制限・オフライン時の扱いを検討したうえで追加する。
- **大規模化**: メモが数百件を大きく超える場合、全件を単一 HTML に埋め込む方式は重くなる。
  「要約インデックス + 全文の遅延ロード」への分割を将来検討する（ADR-003 でも言及）。

## 備考

- サンプルおよび HTML テンプレートの検証には、実データではなく無害な生成データを用いる
  （`docs/site-samples/`）。実データ `memos.json` はローカルのみに置き、コミットしない。
