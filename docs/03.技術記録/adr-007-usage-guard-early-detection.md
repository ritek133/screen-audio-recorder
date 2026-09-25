# ADR-007: 使用量ガードの上限超過を早期に検知する

## ステータス

提案中（Proposed）

## 日付

2026-09-25

## コンテキスト

ADR-006 で導入した SaaS 利用者ごとの使用量ガードは、上限超過時にアクセスキーを自動無効化する
安全弁である。構成は以下のとおり（`infra/templates/12_saas-user.yaml`）。

- `BedrockInvocationAlarm`（`AWS/Bedrock` の `InputTokenCount` を Sum 集計）
- `TranscribeJobAlarm`（`{ProjectName}/TranscribeUsage` のカスタムメトリクスを Sum 集計）
- いずれも CloudWatch Alarm → SNS（`UsageGuardTopic`）→ Lambda（`UsageGuardFunction`）で
  アクセスキーを `Inactive` にする。

### 問題

両アラームとも `Period: 86400`（1 日）で集計している。この設計には、実運用上の弱点がある。

1. **反応が遅い**: CloudWatch アラームは「1 つの Period 区間の統計値が確定してから」評価する。
   Period が 1 日のため、上限を超過しても、その区間のデータ点が確定・評価されるまで発報が
   遅れる。結果として、キー無効化が超過から**最大 1 日近く遅延しうる**。
2. **評価区間のズレ**: `Period: 86400` のスライディングウィンドウは「暦日 00:00 起点」ではなく
   「評価時点から遡る直近 24 時間」を集計する。一方、残量表示 Lambda（`UsageAggregatorFunction`）は
   `GetMetricData` の `StartTime` を「当日 00:00 UTC」に固定して集計している。両者で見ている区間が
   異なり、「表示は上限に達しているのにアラームが出ない（またはその逆）」が起こりうる。

安全弁としては「上限を超えたらできるだけ早く止める」ことが望ましいが、現状はブレーキが 1 日
遅れて効く状態になっている。本 ADR は、この**上限超過の早期検知**をどう実現するかの方針を記録する。

### 前提・制約（調査で確定した事実）

- **CloudWatch アラームは 1 つの Period 区間の統計値を評価する**ため、単純に Period を短くしても
  「直近 5 分の合計」を見るだけで、当日累計にはならない。Period 短縮だけでは「当日累計が
  上限に達したら発報」は実現できない。
- CloudWatch には **ウォールクロック評価ウィンドウ（`EvaluationWindow` の `WallClockWindow`）** が
  あり、評価窓を暦日境界（タイムゾーン指定可、既定 UTC）に整合できる。ただし対応する Period は
  1 分 / 5 分 / 1 時間 / 1 日 / 1 週のいずれかで、高解像度アラーム・複合アラーム・PromQL アラームでは
  使えない。
  - 出典（内容は要約・リフレーズ）: [Create a metric alarm that uses a wall clock evaluation window](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Create_WallClock_Alarm.html)
  - 注: ウォールクロック窓を使っても Period=1 日なら「その日の区間が完了してから評価」になるため、
    **区間ズレは解消できるが早期検知にはならない**。
- 残量表示 Lambda（`UsageAggregatorFunction`）は既に「当日 00:00 UTC から現在までの累計」を
  `GetMetricData` で算出するロジックを持つ。この集計ロジックは再利用できる。

## 決定（案）

早期検知（上限超過から数分でキー無効化）を実現するには、以下の 2 案がある。**本 ADR では
方針を確定させるため両案を比較し、採用案を決定する。**

### 案A: ウォールクロック評価ウィンドウで暦日境界に整合する

- `BedrockInvocationAlarm` / `TranscribeJobAlarm` の `Period` は 1 日のまま、`EvaluationWindow` を
  `WallClockWindow`（UTC 暦日境界）に設定する。
- 効果: 残量表示 Lambda と評価区間（暦日 00:00 起点）が一致し、「表示とアラームのズレ」が解消する。
- 限界: Period=1 日ゆえ、**上限超過の検知は依然として遅い**（区間完了後に評価）。早期検知は
  達成できない。
- CloudFormation 対応: `AWS::CloudWatch::Alarm` の `EvaluationWindow`（WallClockWindow）サポート
  状況を要確認（比較的新しい機能のため）。未対応なら CLI/カスタムリソースでの補完が必要になり、
  ユーザースタックの複雑性が上がる。

### 案B: EventBridge 定期実行 Lambda で当日累計を監視する（推奨）

- EventBridge ルール（例: 5〜10 分間隔）で監視 Lambda を定期起動する。
- 監視 Lambda は `UsageAggregatorFunction` と同じ「当日 00:00 UTC 起点の累計」ロジックで
  Bedrock トークン / Transcribe ジョブ数を集計し、上限（環境変数）と比較する。
- 上限に達していれば、既存の `UsageGuardFunction` 相当の処理（`iam:UpdateAccessKey` で
  アクセスキーを `Inactive`）を実行する。
- 効果: **上限超過を数分以内に検知してキー無効化できる**（早期検知を確実に達成）。暦日起点の
  集計とも自然に一致する。
- 既存資産の再利用: 集計ロジックは `UsageAggregatorFunction`、キー無効化ロジックは
  `UsageGuardFunction`、無効化権限は `UsageGuardLambdaRole` の考え方をそのまま流用できる。
- コスト: 5〜10 分間隔の Lambda 実行 + `GetMetricData` 呼び出しが定常的に発生するが、いずれも
  少額。過剰実行にならないよう間隔を調整する。
- トレードオフ: CloudWatch アラームに依存しない監視系を新設するため、リソース点数（EventBridge
  ルール + Lambda + ロール + パーミッション）が増える。

### 比較サマリ

| 観点 | 案A（WallClockWindow） | 案B（EventBridge 定期実行） |
|---|---|---|
| 早期検知（数分で無効化） | できない（Period=1 日の遅延が残る） | できる（間隔に依存、数分） |
| 表示との区間ズレ解消 | 解消する | 解消する（同一の暦日集計） |
| 実装量 | 小（アラーム属性追加） | 中（監視 Lambda + EventBridge 新設） |
| CFn 対応リスク | `EvaluationWindow` 対応要確認 | 標準リソースのみで実現可能 |
| 既存資産の再利用 | アラーム構成を流用 | 集計/無効化ロジックを流用 |
| 追加コスト | ほぼなし | 定期 Lambda + GetMetricData（少額） |

### 推奨

**案B を推奨する。** 本要件の主目的は「上限を超えたらできるだけ早くキーを無効化する」ことであり、
これを確実に満たせるのは案 B のみである。案 A は区間ズレは直せるが早期検知を達成できず、
主目的に対しては不十分。

## 想定する影響範囲（案B 採用時）

### 変更・新規

- `infra/templates/12_saas-user.yaml`:
  - 監視 Lambda（当日累計を集計し上限超過でキー無効化）を新設。集計ロジックは
    `UsageAggregatorFunction`、無効化は `UsageGuardFunction` の実装を踏襲。
  - EventBridge ルール（`AWS::Events::Rule`、5〜10 分間隔）+ Lambda 呼び出しパーミッションを新設。
  - 監視 Lambda 実行ロール（`cloudwatch:GetMetricData` 読み取り + `iam:UpdateAccessKey` /
    `iam:ListAccessKeys` を当該ユーザーに限定）を新設。
  - 既存 `BedrockInvocationAlarm` / `TranscribeJobAlarm` の扱いを決める（廃止するか、粗い
    安全弁として併存させるか）。本 ADR では**併存させ、EventBridge 監視を主・アラームを予備**と
    する方針を推奨（多層防御）。
  - `AlarmDescription` / `AppConfigSummary` の文言整合。
- `infra/README.md`: 監視方式・間隔・デプロイ手順の追記。

### 影響なし（維持）

- 残量表示 API（`UsageApi` 系）とアプリ側表示。
- 既存の認証方式・呼び出し経路。

## 検討した代替案

- **Period 短縮のみ**（当初の素朴な案）: CloudWatch アラームは 1 Period の統計値しか見ないため、
  「直近 5 分の合計」を評価するだけで当日累計にならない。目的を達成できないため却下。
- **メトリクス数式で当日累積を算出してアラーム化**: 「暦月/暦日の固定起点からの累積」を
  メトリクス数式で厳密に表現するのは難しく（数式は相対期間ベース）、複雑で保守しづらい。
  ウォールクロック窓（案A）の方が素直だが、いずれも早期検知は達成できない。

## 検証方法

- CloudFormation: サンドボックスでは YAML パース + 変更差分レビュー。可能なら実デプロイで
  EventBridge → 監視 Lambda → キー無効化の一連の動作を確認する。
- 監視 Lambda: `GetMetricData` / `iam` をモックしたユニットテスト（上限超過時にキー無効化を呼ぶ／
  未超過時は呼ばない／既に Inactive はスキップ）。
- 既存テスト（`tests/`）が緑であること。

## 備考

- 本 ADR は方針の記録であり、採用案の確定後に `12_saas-user.yaml` の実装を行う。
- 実装時は既存の使用量ガード（アラーム系）との役割分担（主 = EventBridge 監視、予備 = アラーム）を
  コメントで明記する。
- サンドボックスは Windows 専用依存が入らないため、実アプリ起動ではなく Windows 依存を import
  しないユニットテストで検証する。
