# ADR-008: Bedrock 使用量集計のメトリクスディメンション修正と入力+出力トークンの合算

## ステータス

承認済み（Accepted）

## 日付

2026-09-30

## コンテキスト

ADR-006 で導入した SaaS 利用者ごとの残存容量表示は、使用量集約 Lambda
（`UsageAggregatorFunction`、`infra/templates/12_saas-user.yaml`）が CloudWatch の
`GetMetricData` で Bedrock トークン使用量を当日累計し、上限との差分（残量）を返す仕組みである。

### 問題

アプリ上の「残存容量（残トークン）」が、Bedrock を実際に使用しても**まったく変化しなかった**
（常に満タンのまま）。一方、CloudWatch のメトリクス画面を直接見ると、トークン使用量は正しく
積み上がっていた。何度取得し直しても残量が変わらないことから、メトリクス反映の遅延ではなく、
集計対象そのものの指定ミスが疑われた。

### 調査で確定した事実

- 使用量集約 Lambda と安全弁アラーム（`BedrockInvocationAlarm`）は、Bedrock トークンを
  `AWS/Bedrock` の `InputTokenCount` に対し **`InferenceProfileArn` ディメンション**を指定して
  集計していた。
- しかし `aws cloudwatch list-metrics --namespace AWS/Bedrock --metric-name InputTokenCount` の
  結果、実在するディメンションは次の 2 系列のみだった。
  - ディメンションなし（`Dimensions: []`）
  - `ModelId`（値の例: `dx31hxxt6edz`）
- `InferenceProfileArn` というディメンションは**存在しない**。存在しない系列を指定していたため
  `GetMetricData` の戻り値は常に空となり、`used_tokens` が常に 0 → 残量 = 上限 - 0 = 上限のまま
  固定されていた。これが「何度取得しても残量が変化しない」症状の直接原因である。
- `ModelId` の値 `dx31hxxt6edz` は、このユーザーの Application Inference Profile の
  `inferenceProfileId`（= `inferenceProfileArn` の末尾）と一致することを
  `aws bedrock list-inference-profiles --type-equals APPLICATION` で確認した。すなわち
  Bedrock は Application Inference Profile 経由の使用量を、プロファイル ARN ではなく
  **`ModelId`（値 = プロファイル ID）** ディメンションで発行する。
- `OutputTokenCount` も同じ `ModelId=<プロファイル ID>` 系列で発行されていることを確認した。

### 追加要件

上記の残量不変バグの修正に加えて、日次上限を「入力トークンのみ」ではなく
**入力 + 出力の合算総トークン**に対して適用したいという要件が挙がった。

## 決定

`infra/templates/12_saas-user.yaml` に対し、以下を実施した。

### 1. 集計ディメンションを `ModelId` に修正（バグ修正）

- 使用量集約 Lambda が集計に使うディメンションを
  `InferenceProfileArn=<ARN>` から `ModelId=<InferenceProfileId>` に変更。
- Lambda の環境変数を `INFERENCE_PROFILE_ARN`（`!GetAtt InferenceProfile.InferenceProfileArn`）から
  `INFERENCE_PROFILE_ID`（`!GetAtt InferenceProfile.InferenceProfileId`）に変更。
- 安全弁 `BedrockInvocationAlarm` のディメンションも同様に `ModelId=<InferenceProfileId>` に修正
  （表示と安全弁で同じ系列を見るため）。

### 2. 入力 + 出力トークンの合算（要件対応）

- 使用量集約 Lambda で `InputTokenCount` と `OutputTokenCount` を個別に当日集計し、
  `used_tokens = used_input_tokens + used_output_tokens` として合算。日次上限
  （`DAILY_TOKEN_LIMIT`）は合算総トークンに対して適用する。ログにも入力・出力の内訳を出力する。
- `BedrockInvocationAlarm` を単一メトリクス指定から **metric math** 方式に変更し、
  入力 + 出力を合算した値をしきい値評価する。
  - `m1` = `InputTokenCount`（`ModelId=<InferenceProfileId>`, `Period=86400`, `Stat=Sum`, `ReturnData: false`）
  - `m2` = `OutputTokenCount`（同上）
  - `e1` = `m1 + m2`（`Expression`, `ReturnData: true`）を `Threshold`（`DailyTokenLimit`）と比較
  - CloudFormation の仕様上、`Metrics:`（metric math）使用時は `Namespace` / `MetricName` /
    `Dimensions` / `Statistic` / `Period` の直接指定は併用できないため、それらを削除して
    `Metrics:` 配下へ移した。
- `AlarmDescription` を「トークン使用量（入力+出力）が日次上限を超過」に更新。

### 3. GetMetricData の Period 細粒度化

- 使用量集約 Lambda の `_sum_metric` の `Period` を 86400 秒（当日を 1 バケット）から
  300 秒（5 分）に変更し、返ってきた複数データポイントを合算する。当日途中区間で最新の増分が
  反映されにくく、コンソール表示と食い違って見えるのを避けるため。Sum の総和は変わらず、
  当日累計を正しく得られる。

## 影響範囲

### 変更

- `infra/templates/12_saas-user.yaml`
  - `UsageAggregatorFunction`（環境変数・集計ロジック・ログ文言）
  - `BedrockInvocationAlarm`（metric math 化・ディメンション修正・説明文）

### 影響なし（維持）

- 残量表示 API（`UsageApi` 系）のエンドポイント・認証方式・呼び出し経路。
- アプリ側の表示ロジック（`usage_client.py` / `main_window.py`）。返却 JSON の
  `daily_token_limit` / `used_tokens` / `remaining_tokens` の意味は同一で、`used_tokens` の
  中身が「入力のみ」から「入力+出力合算」に変わるのみ。
- アプリが Bedrock を呼ぶための Secrets（`inference_profile_arn`）や IAM ポリシーの
  `bedrock:InferenceProfileArn` 条件キーは正当な用途のため変更しない。

## 検討した代替案

- **`Dimensions: []`（ディメンションなし）系列で集計する**: そのアカウント/リージョンで Bedrock 利用が
  当該プロファイルのみなら合計は一致するが、複数モデル/プロファイル運用では他の使用量が混入し
  不正確。1 ユーザー = 1 プロファイル前提に依存するため却下し、`ModelId` 明示指定を採用。
- **`ModelId` を Lambda が `ListMetrics` で動的解決する**: プロファイル ID 変化に強いが、権限追加と
  複数系列の取り違えリスクがある。`inferenceProfileId` が `!GetAtt` で静的に取得でき、メトリクスの
  `ModelId` 値と一致することを確認できたため、静的指定（案）を採用しシンプルさを優先した。
- **入力のみを上限管理のまま維持**: 要件（合算で管理したい）に合致しないため却下。

## 検証方法

- サンドボックス（Windows・AWS CLI/cfn-lint なし）では以下を実施済み。
  - テンプレートの YAML パース: OK。
  - 埋め込み Lambda（Python）の構文チェック（`ast.parse`）: OK。
  - 合算・ディメンション・Period の変更がコード実体へ反映されていることの確認: OK。
- 未実施（デプロイ環境側で確認が必要）。
  - CloudFormation の完全検証（特に `AWS::CloudWatch::Alarm` の `Metrics` / metric math スキーマ）。
  - 再デプロイ後に使用量 API を呼び、残量が入力+出力の合算で正しく減ることの実挙動確認。

## 備考

- 本修正は残量表示バグ（`ModelId` ディメンション不一致）と要件対応（入力+出力合算）を
  同一の使用量集計まわりの一連の変更としてまとめた。
- 根本原因は、Application Inference Profile 経由の Bedrock 使用量メトリクスが `InferenceProfileArn`
  ではなく `ModelId`（値 = プロファイル ID）で発行される、という発行仕様の想定違いであった。
