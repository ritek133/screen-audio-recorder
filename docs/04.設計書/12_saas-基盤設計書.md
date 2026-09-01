# SaaS 基盤 設計書兼仕様書

Screen Audio Recorder - SaaS リソース構成（CloudFormation）

| 項目 | 内容 |
|------|------|
| 対象テンプレート | `infra/templates/12_saas-shared.yaml`, `infra/templates/12_saas-user.yaml` |
| 目的 | Bedrock / Transcribe を利用する SaaS 型サービスのユーザー単位リソースおよび共有リソースをコード化する |
| リージョン想定 | ap-northeast-1（Bedrock モデル ARN 既定値より） |
| デプロイ方式 | AWS CloudFormation（2 スタック構成） |

---

## 1. 概要

本設計は、複数ユーザーへ Bedrock（生成 AI）および Amazon Transcribe（音声文字起こし）機能を提供する SaaS 基盤を、2 つの CloudFormation テンプレートで構成する。

- **共有スタック（`12_saas-shared.yaml`）**: 全ユーザーで共通利用する S3 バケット（Transcribe 一時保管 + CloudTrail ログ保存）を作成する。1 アカウントに 1 つデプロイする。
- **ユーザースタック（`12_saas-user.yaml`）**: ユーザー単位で作成するリソース群（Bedrock 推論プロファイル、IAM ユーザー、アクセスキー、使用量監視）を作成する。ユーザーごとに 1 スタックずつデプロイする。

ユーザースタックは共有スタックが作成した S3 バケット名をパラメータで受け取り、そのバケットを共用する。

### 1.1 スタック構成図

```
┌─────────────────────────────────────────────┐
│ 共有スタック (12_saas-shared)  ※アカウントに1つ   │
│  ┌───────────────────────────────────────┐  │
│  │ S3 Bucket (Transcribe + CloudTrail)   │  │
│  │  - audio/       : 7日で自動削除         │  │
│  │  - cloudtrail/  : 30日で自動削除        │  │
│  └───────────────────────────────────────┘  │
│         │ Export: transcribe-bucket-name      │
└─────────┼───────────────────────────────────┘
          │ (バケット名をパラメータ渡し)
          ▼
┌─────────────────────────────────────────────┐
│ ユーザースタック (12_saas-user)  ※ユーザーごと    │
│  - Bedrock 推論プロファイル                     │
│  - IAM ユーザー + アクセスキー                   │
│  - IAM ポリシー (Bedrock / Transcribe)         │
│  - Secrets Manager (認証情報)                  │
│  - 使用量ガード (Alarm→SNS→Lambda→キー無効化)   │
└─────────────────────────────────────────────┘
```

---

## 2. 共有スタック仕様（12_saas-shared.yaml）

### 2.1 パラメータ

| 名前 | 型 | 既定値 | 説明 |
|------|----|--------|------|
| `ProjectName` | String | `screen-recorder` | リソース名のプレフィックス |

### 2.2 リソース一覧

| 論理 ID | タイプ | 概要 |
|---------|--------|------|
| `TranscribeBucket` | `AWS::S3::Bucket` | Transcribe 一時ファイル + CloudTrail ログ保存用バケット |
| `TranscribeBucketPolicy` | `AWS::S3::BucketPolicy` | CloudTrail からの書き込みを許可するバケットポリシー |

### 2.3 S3 バケット詳細（TranscribeBucket）

| 設定項目 | 内容 |
|----------|------|
| バケット名 | `${ProjectName}-transcribe-${AWS::AccountId}` |
| 削除ポリシー | `Retain`（スタック削除時もバケットを保持） |
| 置換時ポリシー | `Retain`（`UpdateReplacePolicy`） |
| 暗号化 | サーバーサイド暗号化 `AES256`（SSE-S3） |
| パブリックアクセス | 全面ブロック（ACL / ポリシー / 公開バケットを全て制限） |

#### ライフサイクルルール

| ルール ID | 対象プレフィックス | 動作 |
|-----------|--------------------|------|
| `DeleteTempAudioFiles` | `audio/` | 7 日後に自動削除 |
| `DeleteCloudTrailLogs` | `cloudtrail/` | 30 日後に自動削除 |

### 2.4 バケットポリシー詳細（TranscribeBucketPolicy）

CloudTrail サービス（`cloudtrail.amazonaws.com`）に対して以下を許可する。ユーザースタックが個別に作成する Trail 全てからの書き込みを受け入れるため、`aws:SourceArn` を Trail 名プレフィックス（`${ProjectName}-*`）で制限する。

| Sid | アクション | リソース | 条件 |
|-----|-----------|----------|------|
| `AWSCloudTrailAclCheck` | `s3:GetBucketAcl` | バケット ARN | `SourceArn` が `arn:aws:cloudtrail:{region}:{account}:trail/${ProjectName}-*` |
| `AWSCloudTrailWrite` | `s3:PutObject` | `{バケット}/cloudtrail/AWSLogs/{account}/*` | 同上 |

### 2.5 出力（Outputs / Export）

| 出力名 | Export 名 | 内容 |
|--------|-----------|------|
| `TranscribeBucketName` | `${ProjectName}-transcribe-bucket-name` | バケット名 |
| `TranscribeBucketArn` | `${ProjectName}-transcribe-bucket-arn` | バケット ARN |

> ユーザースタックはバケット名を **パラメータ** で受け取る設計のため、Export は主に参照・確認用途。

---

## 3. ユーザースタック仕様（12_saas-user.yaml）

### 3.1 パラメータ

| 名前 | 型 | 既定値 | 説明 |
|------|----|--------|------|
| `ProjectName` | String | `screen-recorder` | リソース名のプレフィックス |
| `UserName` | String | （必須） | 対象ユーザー名（例: `user-a`）。リソース名に使用 |
| `CreateAccessKey` | String | `true` | IAM アクセスキーを作成するか（`true`/`false`） |
| `BedrockModelArn` | String | `arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0` | 推論プロファイルのソースモデル ARN |
| `EnableTranscribe` | String | `true` | Amazon Transcribe の利用を許可するか |
| `TranscribeBucketName` | String | （必須） | 共有スタックで作成された S3 バケット名 |
| `EnableUsageGuard` | String | `true` | 使用量ガード（上限超過でキー無効化）を有効にするか |
| `MonthlyTokenLimit` | Number | `500000` | 月間トークン上限。超過でアクセスキーを自動無効化 |
| `DailyTranscribeJobLimit` | Number | `10` | 1 日あたり Transcribe ジョブ数上限。超過でキー無効化 |

### 3.2 条件（Conditions）

| 条件名 | 定義 | 用途 |
|--------|------|------|
| `ShouldCreateAccessKey` | `CreateAccessKey == "true"` | アクセスキー・Secret 作成の可否 |
| `ShouldEnableTranscribe` | `EnableTranscribe == "true"` | Transcribe ポリシー作成の可否 |
| `ShouldEnableUsageGuard` | `ShouldCreateAccessKey AND EnableUsageGuard == "true"` | 使用量ガード全般の可否（キーがなければガード不要） |
| `ShouldEnableTranscribeGuard` | `ShouldEnableTranscribe AND ShouldEnableUsageGuard` | Transcribe 用ガード（CloudTrail 系）の可否 |

### 3.3 リソース一覧

| 論理 ID | タイプ | 条件 | 概要 |
|---------|--------|------|------|
| `InferenceProfile` | `AWS::Bedrock::ApplicationInferenceProfile` | 常時 | ユーザー単位の Bedrock 推論プロファイル |
| `AppUser` | `AWS::IAM::User` | 常時 | アプリ利用用の IAM ユーザー |
| `BedrockPolicy` | `AWS::IAM::Policy` | 常時 | Bedrock アクセス（推論プロファイル経由のみ許可） |
| `TranscribePolicy` | `AWS::IAM::Policy` | `ShouldEnableTranscribe` | Transcribe バッチ + S3 アクセス |
| `AppUserAccessKey` | `AWS::IAM::AccessKey` | `ShouldCreateAccessKey` | IAM アクセスキー |
| `AppUserSecret` | `AWS::SecretsManager::Secret` | `ShouldCreateAccessKey` | 認証情報を格納する Secret |
| `UsageGuardTopic` | `AWS::SNS::Topic` | `ShouldEnableUsageGuard` | アラーム通知先 SNS トピック |
| `UsageGuardLambdaRole` | `AWS::IAM::Role` | `ShouldEnableUsageGuard` | キー無効化 Lambda 実行ロール |
| `UsageGuardFunction` | `AWS::Lambda::Function` | `ShouldEnableUsageGuard` | アクセスキーを無効化する Lambda |
| `UsageGuardSubscription` | `AWS::SNS::Subscription` | `ShouldEnableUsageGuard` | SNS → Lambda サブスクリプション |
| `UsageGuardLambdaPermission` | `AWS::Lambda::Permission` | `ShouldEnableUsageGuard` | SNS からの Lambda 呼び出し許可 |
| `BedrockInvocationAlarm` | `AWS::CloudWatch::Alarm` | `ShouldEnableUsageGuard` | Bedrock トークン使用量アラーム |
| `TranscribeTrailLogGroup` | `AWS::Logs::LogGroup` | `ShouldEnableTranscribeGuard` | CloudTrail 転送先ロググループ |
| `CloudTrailLogsRole` | `AWS::IAM::Role` | `ShouldEnableTranscribeGuard` | CloudTrail → CloudWatch Logs 書き込みロール |
| `TranscribeTrail` | `AWS::CloudTrail::Trail` | `ShouldEnableTranscribeGuard` | Transcribe API コール記録用 Trail |
| `TranscribeJobMetricFilter` | `AWS::Logs::MetricFilter` | `ShouldEnableTranscribeGuard` | `StartTranscriptionJob` 数を計上 |
| `TranscribeJobAlarm` | `AWS::CloudWatch::Alarm` | `ShouldEnableTranscribeGuard` | Transcribe 日次ジョブ数アラーム |

### 3.4 Bedrock 推論プロファイル（InferenceProfile）

| 項目 | 内容 |
|------|------|
| プロファイル名 | `${ProjectName}-${UserName}` |
| ソースモデル | `BedrockModelArn`（既定は Claude 3 Haiku） |
| 目的 | ユーザー単位でトークン使用量を計測・課金分離できるようにする |

### 3.5 IAM ポリシー（Bedrock）詳細

推論プロファイル経由の呼び出しのみを許可する **多層防御** 構成。

| Sid | 効果 | 対象 | 意図 |
|-----|------|------|------|
| `AllowInferenceProfile` | Allow | 推論プロファイル ARN | プロファイルへの `InvokeModel` / `Converse` 系を許可 |
| `AllowModelViaProfile` | Allow | 全 foundation-model | 条件 `bedrock:InferenceProfileArn` が本プロファイルのときのみ許可 |
| `DenyDirectModelAccess` | Deny | 全 foundation-model | `InferenceProfileArn` が未指定（`Null=true`）の直接呼び出しを拒否 |
| `BedrockReadOnly` | Allow | `*` | モデル/プロファイルの一覧・取得（読み取り専用） |

> 効果として「推論プロファイルを介した呼び出し」のみ許可され、ユーザーが任意モデルへ直接アクセスすることを防ぐ。

### 3.6 IAM ポリシー（Transcribe）詳細

条件 `ShouldEnableTranscribe` のときのみ作成。

| Sid | 効果 | アクション | リソース |
|-----|------|-----------|----------|
| `TranscribeBatch` | Allow | `StartTranscriptionJob` / `GetTranscriptionJob` / `ListTranscriptionJobs` / `DeleteTranscriptionJob` | `transcription-job/${ProjectName}-*` |
| `TranscribeS3` | Allow | `s3:PutObject` / `GetObject` / `DeleteObject` | `{バケット}/${UserName}/*`, `{バケット}/screen-audio-recorder/*` |
| `DenyStreaming` | Deny | `StartStreamTranscription` / `StartStreamTranscriptionWebSocket` | `*` |

> バッチ文字起こしのみ許可し、ストリーミング文字起こしは明示的に拒否する。

### 3.7 認証情報の保管（AppUserAccessKey / AppUserSecret）

条件 `ShouldCreateAccessKey` のときのみ作成。

- `AppUserAccessKey`: IAM ユーザーのアクセスキーを発行。
- `AppUserSecret`: Secrets Manager に以下の JSON 形式で格納。
  - Secret 名: `${ProjectName}/${UserName}/credentials`
  - 格納内容: `access_key_id`, `secret_access_key`, `region`, `inference_profile_arn`

> 認証情報はテンプレート内でハードコードされず、CloudFormation の擬似パラメータ・リソース属性参照で動的に組み立てられる。アプリ側は Secrets Manager から取得する運用を推奨。

---

## 4. 使用量ガードの仕組み

上限超過時にアクセスキーを自動無効化することで、コスト暴走を防ぐ。Bedrock と Transcribe で監視経路が異なる。

### 4.1 共通経路（アラーム → キー無効化）

```
CloudWatch Alarm ──(ALARM)──▶ SNS Topic ──▶ Lambda ──▶ IAM アクセスキーを Inactive 化
```

- `UsageGuardFunction`（Python 3.12）は SNS メッセージの `NewStateValue == "ALARM"` を確認し、対象 IAM ユーザーの Active なアクセスキーを全て `Inactive` に更新する。
- Lambda ロールは対象ユーザーに対する `iam:UpdateAccessKey` / `iam:ListAccessKeys` のみを許可（最小権限）。

### 4.2 Bedrock トークン監視（BedrockInvocationAlarm）

| 項目 | 内容 |
|------|------|
| 名前空間 / メトリクス | `AWS/Bedrock` / `InputTokenCount` |
| ディメンション | `InferenceProfileArn` = 当該プロファイル |
| 集計 | `Sum` / 期間 86400 秒（1 日）/ 評価回数 1 |
| しきい値 | `MonthlyTokenLimit`（既定 500000） |
| 比較演算子 | `GreaterThanOrEqualToThreshold` |
| 欠測時 | `notBreaching`（データなしは正常扱い） |

### 4.3 Transcribe ジョブ数監視（CloudTrail 経路）

Transcribe には直接のトークン系メトリクスがないため、CloudTrail の API コールを集計して監視する。

```
Transcribe API コール
   ▼
CloudTrail (TranscribeTrail, WriteOnly/管理イベント)
   ▼  (S3: cloudtrail/ + CloudWatch Logs)
Log Group (TranscribeTrailLogGroup, 保持14日)
   ▼
Metric Filter (StartTranscriptionJob かつ userName 一致で +1)
   ▼
CloudWatch Alarm (TranscribeJobAlarm)
   ▼
SNS → Lambda → キー無効化
```

| 項目 | 内容 |
|------|------|
| Trail 名 | `${ProjectName}-${UserName}-transcribe-trail` |
| ログ出力先 | 共有 S3 バケットの `cloudtrail` プレフィックス + CloudWatch Logs |
| フィルタパターン | `eventName = "StartTranscriptionJob"` かつ `userIdentity.userName = "${ProjectName}-${UserName}"` |
| メトリクス | `${ProjectName}/TranscribeUsage` / `${UserName}-TranscribeJobCount` |
| しきい値 | `DailyTranscribeJobLimit`（既定 10）/ 期間 86400 秒 |

---

## 5. 出力（Outputs）一覧（ユーザースタック）

| 出力名 | 条件 | 内容 |
|--------|------|------|
| `InferenceProfileArn` | 常時 | 推論プロファイル ARN |
| `InferenceProfileId` | 常時 | 推論プロファイル ID |
| `AppUserArn` | 常時 | IAM ユーザー ARN |
| `AccessKeyId` | `ShouldCreateAccessKey` | アクセスキー ID |
| `SecretAccessKey` | `ShouldCreateAccessKey` | シークレットアクセスキー（作成時のみ表示） |
| `SecretArn` | `ShouldCreateAccessKey` | Secrets Manager ARN |
| `AppConfigSummary` | 常時 | アプリ設定サマリー（人間可読テキスト） |

---

## 6. デプロイ手順

### 6.1 前提

- AWS CLI が設定済みで、CloudFormation・IAM・Bedrock・Transcribe の権限があること。
- Bedrock の対象モデル（既定は Claude 3 Haiku）が対象リージョンで有効化されていること。

### 6.2 手順

1. **共有スタックをデプロイ（アカウントで最初の 1 回のみ）**

   ```powershell
   aws cloudformation deploy `
     --template-file infra/templates/12_saas-shared.yaml `
     --stack-name screen-recorder-saas-shared `
     --parameter-overrides ProjectName=screen-recorder `
     --capabilities CAPABILITY_NAMED_IAM
   ```

2. **共有スタックのバケット名を取得**

   ```powershell
   aws cloudformation describe-stacks `
     --stack-name screen-recorder-saas-shared `
     --query "Stacks[0].Outputs[?OutputKey=='TranscribeBucketName'].OutputValue" `
     --output text
   ```

3. **ユーザースタックをデプロイ（ユーザーごとに実行）**

   ```powershell
   aws cloudformation deploy `
     --template-file infra/templates/12_saas-user.yaml `
     --stack-name screen-recorder-saas-user-a `
     --parameter-overrides `
       ProjectName=screen-recorder `
       UserName=user-a `
       TranscribeBucketName=<手順2で取得したバケット名> `
     --capabilities CAPABILITY_NAMED_IAM
   ```

> `--capabilities CAPABILITY_NAMED_IAM` は名前付き IAM リソース（ユーザー/ロール）を作成するため必須。

### 6.3 削除時の注意

- 共有 S3 バケットは `DeletionPolicy: Retain` のため、共有スタックを削除してもバケットは残る。不要な場合は手動で空にして削除する。
- ユーザースタック削除時、アクセスキー・Secret・監視リソースは削除される。

---

## 7. 設計上のポイント / 制約

- **2 スタック分離の理由**: S3 バケットは全ユーザーで共有し、CloudTrail ログを 1 箇所に集約するため。ユーザー追加時は共有スタックを変更せずユーザースタックを追加するだけでよい。
- **バケットポリシーの Trail 名ワイルドカード**: ユーザーごとに Trail 名（`${ProjectName}-*`）が異なるため、`aws:SourceArn` をプレフィックスマッチで許可している。
- **推論プロファイル経由の強制**: Bedrock の直接モデルアクセスを Deny し、コスト計測（ユーザー単位）を確実にする。
- **使用量ガードの依存関係**: `ShouldEnableUsageGuard` は `ShouldCreateAccessKey` を含むため、キーを作らない構成ではガードも作られない（無効化対象がないため）。
- **リージョン依存**: Bedrock モデル ARN 既定値が `ap-northeast-1`。別リージョンで使う場合は `BedrockModelArn` を上書きすること。
- **Transcribe はバッチのみ**: ストリーミング文字起こしは明示的に拒否している。

---

## 8. 変更履歴

| 日付 | 版 | 内容 |
|------|----|------|
| 2026-08-26 | 1.0 | 初版作成（既存テンプレートより設計書兼仕様書を起こす） |
