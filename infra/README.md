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
- **集計**: Lambda が `cloudwatch:GetMetricData` で「当月 1 日 00:00 UTC 〜 現在」の
  Bedrock 入力トークン数（`AWS/Bedrock` `InputTokenCount`）と Transcribe ジョブ数
  （`{ProjectName}/TranscribeUsage` の `{UserName}-TranscribeJobCount`）を Sum 集計する。
- **残量計算**: 上限（`MonthlyTokenLimit` / `MonthlyTranscribeJobLimit`）との差分を
  サーバー側（Lambda 環境変数 = CloudFormation パラメータ由来）で算出する。
  **上限値そのものはアプリへ配布・保存しない。**
- **認証**: API Gateway は IAM 認可（SigV4 署名）。アプリ IAM ユーザーには
  当該 API の `prod/GET/usage` に限定した `execute-api:Invoke` を付与する。
- **集計期間の統一**: Bedrock・Transcribe とも「月次（暦月）」で評価する。
  使用量ガードのアラーム（`BedrockInvocationAlarm` / `TranscribeJobAlarm`）は
  評価窓を 30 日相当（`Period: 2592000`）とした近似的な安全弁であり、
  残量表示に用いる厳密な暦月累計は集約 Lambda が算出する。

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
  --parameter-overrides ProjectName=screen-recorder
```

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
    MonthlyTokenLimit=500000 \
    MonthlyTranscribeJobLimit=10 \
    BedrockModelArn=arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0
```

> **上限パラメータ**: Transcribe の上限パラメータは月次に統一され、名称が
> `DailyTranscribeJobLimit` から **`MonthlyTranscribeJobLimit`**（デフォルト 10）に変更された。
> Bedrock トークン上限は `MonthlyTokenLimit`（デフォルト 500000）。上限を変更する場合は
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
