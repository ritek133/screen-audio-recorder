# ADR-006: SaaS 利用者ごとの残存容量（残トークン・残文字起こし回数）の可視化

## ステータス

提案中（Proposed）

## 日付

2026-09-24

## コンテキスト

AWS SaaS 構成（Amazon Bedrock による要約 / Amazon Transcribe による文字起こし）を
利用者ごとに提供している。各利用者にはユーザー単位の CloudFormation スタック
（`infra/templates/12_saas-user.yaml`）で以下が払い出される。

- Bedrock アプリケーション推論プロファイル（ユーザー単位）
- IAM ユーザー + アクセスキー + Secrets Manager
- 使用量ガード（CloudWatch Alarm → SNS → Lambda によるアクセスキー自動無効化）

現状、利用者は自分がどれだけ使ったか・あとどれだけ使えるかを把握できない。上限に達すると
アクセスキーが自動的に無効化され、突然使えなくなる体験になっている。そこで
「**利用者ごとに自分の残存容量（残トークン数・残文字起こし回数・リセット日時）を
アプリ上で確認できる**」ようにしたい。

本 ADR は、この可視化機能の設計方針を記録する。実装は本 ADR の決定に基づき後続で行う。

### ユーザーが確定させた前提（設計の所与）

1. **集計期間は月次（月上限）に統一する。**
   - Bedrock トークンは既に月上限想定（`MonthlyTokenLimit`、デフォルト 500000）。
   - Transcribe は現状「日次」上限（`DailyTranscribeJobLimit`、`TranscribeJobAlarm` の
     `Period: 86400`）である。これを月次上限へ揃える。
2. **残量表示の場所はメインウィンドウ**（`src/screen_audio_recorder/gui/main_window.py`）。
3. **アーキテクチャは案B（集約 API 方式）。**
4. **上限値の管理は CloudFormation パラメータのまま**（DynamoDB / SSM 動的管理はしない）。
   上限変更時はスタック再デプロイで対応する。

### 現状コードの調査結果（設計の前提）

- Bedrock トークン使用量: `AWS/Bedrock` 名前空間の `InputTokenCount`
  （Dimension: `InferenceProfileArn`）を `BedrockInvocationAlarm` が Sum 集計している。
  上限は `MonthlyTokenLimit`。ただし現状の Alarm は `Period: 86400`（1 日）であり、
  「月内累計」を評価する構成にはなっていない（後述の課題）。
- Transcribe ジョブ数: CloudTrail → CloudWatch Logs → メトリクスフィルタで
  `{ProjectName}/TranscribeUsage` 名前空間のカスタムメトリクス
  `{UserName}-TranscribeJobCount`（`StartTranscriptionJob` のコール数）を生成している。
  上限は `DailyTranscribeJobLimit`。`TranscribeJobAlarm` の `Period: 86400`（1 日）。
- スタック Outputs: `InferenceProfileArn` / `AppUserArn` / `AccessKeyId` /
  `SecretAccessKey` / `SecretArn`。
- アプリ側 AWS 連携: `src/screen_audio_recorder/aws_utils.py` に
  `create_boto3_session` / `create_boto3_client`（任意サービスのクライアント生成が可能）、
  `is_boto3_available` がある。認証は `AwsSettings` / `AwsAuthMethod`（`models.py`）で
  アクセスキー or プロファイル/IAM ロールを切り替える。CA バンドル処理あり。
- AWS 設定の永続化: `llm_settings_store.py` が `llm_settings.json` の `aws` セクションで
  `AwsSettings` を保存・読み込みする。
- 上限値（`MonthlyTokenLimit` 等）はアプリ側 JSON には保存されていない。

## 決定

### 決定 1: 集計期間を月次（暦月）に統一する

残量表示・使用量ガードともに「**当月 1 日 00:00（UTC）から現在まで**」の累計で評価する。
リセット日時は「**翌月 1 日 00:00（UTC）**」とする。

これに伴い CloudFormation を以下のとおり変更する。

- Transcribe の上限パラメータ名を `DailyTranscribeJobLimit` から
  `MonthlyTranscribeJobLimit` へリネームする（デフォルト値は据え置き 10、あるいは月次に
  見合う値に見直す。実運用値はデプロイ時パラメータで調整）。
- `TranscribeJobAlarm` を「当月累計」を評価する構成へ変更する。CloudWatch Alarm 単体では
  「暦月の 1 日起点」を厳密に表現できないため、`TranscribeJobAlarm` は
  **メトリクスの `Period` を 30 日相当（`2592000` 秒）に設定**して近似する。厳密な暦月境界の
  判定は後述の集約 Lambda 側で `GetMetricData` の `StartTime` を「当月 1 日 00:00 UTC」に
  指定して行い、Alarm はあくまで「キー自動無効化のための安全弁」と位置づける。
  - 補足: Bedrock の `BedrockInvocationAlarm` も同様に `Period: 2592000`（30 日相当）へ
    変更し、Bedrock/Transcribe の評価窓を揃える。
- 上記に合わせて `AppConfigSummary` Output と `AlarmDescription` の文言（「日次」→「月次」）を修正する。

「暦月の厳密な累計」と「Alarm の近似（30 日窓）」の差は、残量表示（正）と自動無効化（安全弁）で
役割が異なることを許容する。表示値の正は集約 Lambda が `GetMetricData` で当月 1 日起点に集計する。

### 決定 2: 案B（集約 API 方式）で残量を返す

API Gateway（IAM 認証 / SigV4）＋ Lambda を新設する。Lambda は CloudWatch から当月使用量を
取得し、CloudFormation パラメータで与えられた上限との差分を計算して、以下を JSON で返す。

- 残トークン数 / 月トークン上限 / 当月使用トークン数
- 残文字起こし回数 / 月文字起こし上限 / 当月使用文字起こし回数
- 期間の開始・リセット日時（当月 1 日 00:00 UTC / 翌月 1 日 00:00 UTC）
- 取得時刻

アプリは 1 エンドポイントを SigV4 署名付きで呼ぶだけでよい。**上限値そのものはアプリに配布・
保存せず、サーバー側（Lambda 環境変数 = CloudFormation パラメータ由来）に閉じる。**
アプリは Lambda が返した「残量・上限・使用量」を表示するだけで、上限を知る必要はない
（差分計算はサーバー側で完結する）。

#### Lambda 設計

- Runtime: `python3.12`（既存の使用量ガード Lambda と同じ）。
- 取得: `cloudwatch:GetMetricData` で以下を当月 1 日 00:00 UTC 起点に Sum 集計する。
  - Bedrock: `AWS/Bedrock` `InputTokenCount`（Dimension `InferenceProfileArn`）
  - Transcribe: `{ProjectName}/TranscribeUsage` `{UserName}-TranscribeJobCount`
- 上限: Lambda の環境変数（`MONTHLY_TOKEN_LIMIT` / `MONTHLY_TRANSCRIBE_JOB_LIMIT`）として
  CloudFormation パラメータ値を注入する。
- 権限: Lambda 実行ロールに `cloudwatch:GetMetricData` の読み取り権限を付与する
  （リソースは `*`。GetMetricData はリソースレベル制限に非対応のため）。
- 認証: API Gateway は IAM 認可（`AWS_IAM`）。アプリ側 IAM ユーザーには
  `execute-api:Invoke` を当該 API リソースに限定して付与する。
- セキュリティ: **Lambda コードに環境変数の一括ダンプ（`os.environ` / `printenv` の全出力）を
  入れない。** ログには使用量・残量の要約のみを出力し、認証情報や環境変数全体は出力しない。

#### API Gateway 設計

- REST API（`AWS::ApiGateway::RestApi`）+ 単一リソース（例: `/usage`）+ `GET` メソッド。
- 認可: `AWS_IAM`。
- ステージ: 例 `prod`。
- 応答: Lambda プロキシ統合で JSON をそのまま返す。

#### テンプレート配置

新規リソース（API Gateway + 集約 Lambda + 実行ロール + アプリ IAM ユーザーへの
`execute-api:Invoke` 付与）は **`12_saas-user.yaml` に追記**する。理由は、これらが
ユーザー単位（推論プロファイル・IAM ユーザー・メトリクス）に強く紐づき、ユーザースタックの
ライフサイクルと一致するため。新規テンプレートに分割すると Outputs 経由の相互参照が増え、
デプロイ手順が煩雑になる。番号規則（12_ = SaaS 系）とも整合する。

- 新規 Output として `UsageApiEndpoint`（`GET` する URL）を追加する。
- 使用量 API は使用量ガード（`ShouldEnableUsageGuard`）とは独立に、`EnableTranscribe` に
  依存しない形で提供する（Bedrock 残量は常に返せる。Transcribe が無効ならその項目は
  上限 0 / 使用量 0 相当、あるいは `null` を返す設計とし、Lambda 側で分岐する）。

### 決定 3: アプリ側の使用量取得と表示

- 取得ロジックは **新規モジュール `src/screen_audio_recorder/usage_client.py`** に実装する。
  `aws_utils.create_boto3_session` で得た認証情報から SigV4 署名を作り、`UsageApiEndpoint` に
  `GET` する。`botocore` の `SigV4Auth` + `AWSRequest` + `urllib`/`botocore` の HTTP 送信を用い、
  余計な依存を増やさない。
- 取得結果は新規 dataclass（例: `UsageInfo`）として `models.py` に定義する
  （残トークン・月トークン上限・残文字起こし回数・月文字起こし上限・リセット日時・取得時刻・
  エラーメッセージ）。
- 使用量 API のエンドポイント URL はアプリ設定（`AwsSettings` を拡張、または
  `TranscriberSettings`/新設フィールド）に保存する。**上限値はアプリに保存しない**
  （案Bの要点）。`llm_settings.json` の `aws` セクションに `usage_api_endpoint` を追加する。
- メインウィンドウ（`main_window.py`）に残量表示 UI を追加する。ステータスバー付近、または
  録画タブ上部に「残トークン: X / 月上限 Y、残文字起こし: X / 月上限 Y、リセット: 日時」を
  表示する。取得はネットワーク I/O のため **バックグラウンドスレッドで実行**し、完了後に
  `root.after` で GUI に反映する（既存の Whisper 非同期ロードと同じパターン）。手動更新ボタンを
  設ける。取得失敗時は表示を「取得できませんでした」等にフォールバックし、録画機能は阻害しない。

### 検証方法

- CloudFormation: `aws cloudformation validate-template` 相当（サンドボックスでは
  YAML パース + 変更差分のレビュー）で構文を確認する。可能なら実デプロイで Output
  `UsageApiEndpoint` が生成され、`GET` が残量 JSON を返すことを確認する。
- アプリ: `usage_client` のユニットテスト（`GetMetricData`/HTTP をモックし、
  レスポンス JSON → `UsageInfo` 変換、エラー時フォールバックを検証）。メインウィンドウの
  表示更新テスト（バックグラウンド取得完了時に表示が更新されること）。
- 既存テスト（`tests/`）が緑であること。

## 検討した代替案

- **案A: アプリが CloudWatch を直読み**（各アプリが `GetMetricData` を直接呼ぶ）。
  - 却下理由: 上限値をアプリ側に配布・保存する必要があり、上限を利用者へ露出してしまう。
    各アプリに CloudWatch 読み取り権限を広く付与することになり最小権限から外れる。集計期間・
    上限計算ロジックがクライアントに分散し、上限変更のたびに全アプリの再配布が必要になる。
- **案C: 使用量を独自 DB（DynamoDB 等）で管理**し、アプリ利用ごとに加算・参照する。
  - 却下理由: 使用量の真実源が CloudWatch（Bedrock/Transcribe の実測）と二重になり整合性の
    担保が難しい。書き込み経路・整合性・コストの新規複雑性が、今回の「可視化」という要件に対して
    過剰。上限管理を CFn パラメータのままにする方針とも合わない。
- **Transcribe 上限を日次のまま残す**。
  - 却下理由: ユーザーが「月次に統一」と明確に決定済み。Bedrock（月次）と評価窓が食い違い、
    残量表示の一貫性が損なわれる。

## 影響範囲

### 変更・新規（想定）

- `infra/templates/12_saas-user.yaml`:
  - `DailyTranscribeJobLimit` → `MonthlyTranscribeJobLimit` へリネーム。
  - `TranscribeJobAlarm` / `BedrockInvocationAlarm` の `Period` を月次相当（`2592000`）へ変更。
  - API Gateway（`AWS_IAM`）+ 集約 Lambda + 実行ロールを新設。
  - アプリ IAM ユーザーに `execute-api:Invoke` を付与するポリシーを追加。
  - Output `UsageApiEndpoint` を追加。`AppConfigSummary` / `AlarmDescription` の文言更新。
- `infra/README.md`: 新リソース・デプロイ手順・アプリ設定（使用量 API エンドポイント）の追記。
- `src/screen_audio_recorder/models.py`: `UsageInfo` dataclass、`AwsSettings` へ
  `usage_api_endpoint` フィールド追加。
- `src/screen_audio_recorder/usage_client.py`（新規）: SigV4 署名付き `GET` による使用量取得。
- `src/screen_audio_recorder/llm_settings_store.py`: `aws` セクションの
  `usage_api_endpoint` 読み書き。
- `src/screen_audio_recorder/gui/main_window.py`: 残量表示 UI とバックグラウンド取得結線。
- `tests/`: `usage_client` / `models`（`UsageInfo`）/ `llm_settings_store` /
  `main_window` の残量表示のテスト追加。

### 影響なし（維持）

- 既存の使用量ガード（Alarm → SNS → Lambda によるキー無効化）の骨格は維持し、評価窓のみ月次化する。
- 既存の Bedrock/Transcribe 呼び出し経路、認証方式（`AwsSettings`）。

## 備考

- 本 ADR は方針の記録であり、実装は後続で段階的に行う。
- CI/CD 設定（`.github/workflows/*`）を変更する場合はデフォルトブランチへの直 push を避け、
  PR 経由で行うこと（本タスクでは CI 設定変更は想定しない）。
- サンドボックスは Linux（Python 3.9）で Windows 専用依存（dxcam / PyAudioWPatch）が入らないため、
  実アプリ起動ではなく、Windows 依存を import しないユニットテストで検証する。
