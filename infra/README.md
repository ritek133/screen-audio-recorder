# インフラストラクチャ (AWS CloudFormation)

Screen Audio Recorder の AWS 環境を構築する CloudFormation テンプレート群。

## 構成

```
infra/
├── README.md                    # このファイル
├── templates/
│   ├── 01_network.yaml          # VPC・サブネット・セキュリティグループ
│   ├── 11_vllm-server.yaml      # vLLM 推論サーバー（GPU EC2）
│   ├── 12_saas-shared.yaml      # SaaS 共有リソース（S3 バケット）
│   └── 12_saas-user.yaml        # SaaS ユーザーリソース（IAM・Bedrock・監視）
└── parameters/
    └── dev.json                 # 開発環境パラメータ例
```

> **番号規則**: 01〜09 = 基盤（ネットワーク）、11〜19 = コンピュート/アプリ、21〜 = ストレージ/その他

## アーキテクチャ概要

### vLLM 環境
- **用途**: Whisper 音声文字起こし + LLM テキスト後処理を GPU サーバーで実行
- **構成**: EC2 (g5.xlarge) + NVIDIA ドライバ + vLLM サーバー
- **接続**: デスクトップアプリから HTTPS で vLLM の OpenAI 互換 API にアクセス

### SaaS 環境
- **用途**: Amazon Bedrock（LLM）、Amazon Transcribe（文字起こし）をマネージドサービスとして利用
- **構成**: IAM ユーザー/ロール + 最小権限ポリシー + 使用量ガード（CloudWatch Alarm → SNS → Lambda）
- **接続**: デスクトップアプリから boto3 で直接 AWS API を呼び出し

#### 使用量可視化 API（案B: 集約 API 方式）
`12_saas-user.yaml` には、利用者ごとの残存容量（残トークン数・残文字起こし回数・リセット日時）を
返す使用量集約 API が含まれる。

- **構成**: API Gateway（REST API, `AWS_IAM` 認可）→ Lambda（`python3.12`）。
- **集計**: Lambda が `cloudwatch:GetMetricData` で「当日 00:00 UTC 〜 現在」の
  Bedrock 入力トークン数（`AWS/Bedrock` `InputTokenCount`）と Transcribe ジョブ数
  （`{ProjectName}/TranscribeUsage` の `{UserName}-TranscribeJobCount`）を Sum 集計する。
- **残量計算**: 上限（`DailyTokenLimit` / `DailyTranscribeJobLimit`）との差分を
  サーバー側（Lambda 環境変数 = CloudFormation パラメータ由来）で算出する。
  **上限値そのものはアプリへ配布・保存しない。**
- **認証**: API Gateway は IAM 認可（SigV4 署名）。アプリ IAM ユーザーには
  当該 API の `prod/GET/usage` に限定した `execute-api:Invoke` を付与する。
- **集計期間の統一**: Bedrock・Transcribe とも「日次」で評価する。
  使用量ガードのアラーム（`BedrockInvocationAlarm` / `TranscribeJobAlarm`）は
  評価窓を 1 日（`Period: 86400`）とした安全弁であり、
  残量表示に用いる厳密な当日累計（当日 00:00 UTC 起点）は集約 Lambda が算出する。

##### 使用量 API のセキュリティ
使用量 API（`UsageApi` / `UsageApiStage`）には以下のセキュリティ対策を施している。

- **IAM 認可（SigV4）**: `GET /usage`（`UsageApiMethod`）の `AuthorizationType` は
  `AWS_IAM`。呼び出しには IAM 資格情報での SigV4 署名が必須で、公開 API ではない。
  アプリ IAM ユーザーには `UsageApiInvokePolicy` で `execute-api:Invoke` を
  当該 API の `prod/GET/usage` に限定して付与しており、他リソース・他メソッド・他ステージへの
  呼び出しは許可されない。
- **スロットリング（レート制限）**: `prod` ステージの `MethodSettings` で全メソッドに
  `ThrottlingRateLimit: 5`（req/s）・`ThrottlingBurstLimit: 10` を設定。更新ボタンの連打や
  誤実装による過剰コール・コスト増を抑制する。
- **アクセスログ**: `prod` ステージの `AccessLogSetting` で CloudWatch Logs ロググループ
  `/aws/apigateway/${ProjectName}-${UserName}-usage-api`（`UsageApiAccessLogGroup`、
  `RetentionInDays: 14`）へ JSON 形式で出力する。ログには `requestId` / `ip` / `caller` /
  `user` / `requestTime` / `httpMethod` / `resourcePath` / `status` / `protocol` /
  `responseLength` のみを含め、**認証情報・`Authorization` ヘッダ・リクエスト/レスポンス本文は
  一切残さない**。
- **実行ログ・メトリクス**: `MethodSettings` で `LoggingLevel: INFO`、`MetricsEnabled: true` を
  有効化。ただし `DataTraceEnabled: false` を厳守する（`true` にするとリクエスト/レスポンス本文が
  ログに出力されるため、有効化しない）。

> **前提: API Gateway の CloudWatch Logs ロール設定（アカウント/リージョンで一度だけ）**
>
> API Gateway がアクセスログ・実行ログを CloudWatch Logs へ書き込むには、
> アカウントレベルの設定（`AWS::ApiGateway::Account` の `CloudWatchRoleArn`）が必要である。
> これはリージョン/アカウントにつき 1 つのグローバル設定であり、ユーザーごとスタック
> （`12_saas-user.yaml`）に置くとデプロイのたびに上書き競合する。そのため
> **共有スタック（`12_saas-shared.yaml`）に集約**しており、共有スタックを一度デプロイすれば
> 設定が完了する（下記「3a. 共有リソース」を参照）。
>
> 共有スタックを使わず個別に設定する場合は、次のいずれかを一度だけ実行する。
>
> - CLI（ロールを作成済みの場合）:
>
>   ```bash
>   aws apigateway update-account \
>     --patch-operations op=replace,path=/cloudwatchRoleArn,value=arn:aws:iam::<アカウントID>:role/<ログ用ロール名>
>   ```
>
> - マネジメントコンソール: API Gateway → 設定（Settings）→ CloudWatch log role ARN に
>   `AmazonAPIGatewayPushToCloudWatchLogs` を持つロールの ARN を設定する。
>
> この設定が未了だと、ユーザースタックのステージでログ出力が有効化されずデプロイが失敗する
> 場合があるため、**ユーザースタックの前に共有スタックをデプロイすること**。

## デプロイ手順

### 前提条件
- AWS CLI がインストール・設定済み
- デプロイ先の AWS アカウントへの管理者権限

### 1. ネットワーク（共通基盤）

```bash
aws cloudformation deploy \
  --template-file templates/01_network.yaml \
  --stack-name screen-recorder-network \
  --parameter-overrides file://parameters/dev.json
```

### 2. vLLM サーバー（GPU 推論が必要な場合）

```bash
aws cloudformation deploy \
  --template-file templates/11_vllm-server.yaml \
  --stack-name screen-recorder-vllm \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides file://parameters/dev.json
```

### 3. SaaS リソース（Bedrock/Transcribe 利用の場合）

#### 3a. 共有リソース（初回のみ）

```bash
aws cloudformation deploy \
  --template-file templates/12_saas-shared.yaml \
  --stack-name screen-recorder-saas-shared \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides ProjectName=screen-recorder
```

> **CAPABILITY / API Gateway アカウント設定**: 共有スタックは S3 バケットに加えて、
> API Gateway が CloudWatch Logs へログ出力するためのアカウント用 IAM ロール
> （`AWS::IAM::Role` + `AWS::ApiGateway::Account`）を作成する。名前付き IAM リソースを
> 含むため `--capabilities CAPABILITY_NAMED_IAM` が必要。この設定はリージョン/アカウントに
> つき一度だけ行えばよく、ユーザースタックのアクセスログ/実行ログの前提となる（上記
> 「使用量 API のセキュリティ」を参照）。

#### 3b. ユーザーリソース（ユーザーごと）

```bash
aws cloudformation deploy \
  --template-file templates/12_saas-user.yaml \
  --stack-name screen-recorder-saas-user01 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName=screen-recorder \
    UserName=user01 \
    TranscribeBucketName=screen-recorder-transcribe-<アカウントID> \
    DailyTokenLimit=500000 \
    DailyTranscribeJobLimit=10 \
    BedrockModelArn=arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0
```

> **上限パラメータ**: Bedrock・Transcribe とも日次上限に統一されている。
> Bedrock トークン上限は **`DailyTokenLimit`**（デフォルト 500000）、
> Transcribe ジョブ上限は **`DailyTranscribeJobLimit`**（デフォルト 10）。上限を変更する場合は
> パラメータを指定してスタックを再デプロイする（DynamoDB / SSM による動的管理は行わない）。
>
> **CAPABILITY**: 使用量集約 API 用の IAM ロール・名前付き IAM リソースを含むため、
> 従来どおり `--capabilities CAPABILITY_NAMED_IAM` が必要（追加の CAPABILITY は不要）。

## アプリとの接続設定

### vLLM エンドポイント
デプロイ後、スタック出力の `VllmEndpoint` をアプリの設定に入力:
- 文字起こし設定 → バックエンド: vLLM → エンドポイント URL
- LLM 設定 → バックエンド: API → エンドポイント URL

### SaaS (Bedrock / Transcribe)
デプロイ後、スタック出力の `AccessKeyId` / `SecretAccessKey` をアプリの AWS 設定に入力。
または IAM ロールの場合は AWS プロファイルを設定。

### 使用量 API エンドポイント（残存容量の可視化）
デプロイ後、スタック出力の **`UsageApiEndpoint`**
（`https://<RestApiId>.execute-api.<リージョン>.amazonaws.com/prod/usage` の形式）を
アプリの AWS 設定に入力する。アプリはこのエンドポイントを IAM/SigV4 署名付きで `GET` し、
残トークン数・残文字起こし回数・リセット日時をメインウィンドウに表示する。
（設定値はアプリの `llm_settings.json` の `aws` セクションに保存される。上限値は保存されない。）

## コスト目安（東京リージョン）

| リソース | 月額目安 |
|---------|---------|
| EC2 g5.xlarge (オンデマンド) | 約 $1.00/h ≒ $720/月 (常時稼働) |
| EC2 g5.xlarge (スポット) | 約 $0.30〜0.50/h |
| EBS gp3 100GB | 約 $9.60/月 |
| Bedrock (Claude Haiku) | $0.25/100万入力トークン |
| Transcribe | $0.024/分 |
| 使用量 API (API Gateway + Lambda) | ごく僅か（残量取得のたびに 1 リクエスト、無料枠内に収まる想定） |
| CloudWatch GetMetricData | ごく僅か（メトリクス取得料金。呼び出し回数に比例） |

> **ヒント**: vLLM サーバーは必要な時だけ起動し、不要時は停止することでコストを抑えられます。
> **補足**: 使用量 API は残量取得時のみ呼び出されるため、追加コストは軽微です。
