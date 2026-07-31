# インフラストラクチャ (AWS CloudFormation)

Screen Audio Recorder の AWS 環境を構築する CloudFormation テンプレート群。

## 構成

```
infra/
├── README.md                    # このファイル
├── templates/
│   ├── 01_network.yaml          # VPC・サブネット・セキュリティグループ
│   ├── 11_vllm-server.yaml      # vLLM 推論サーバー（GPU EC2）
│   └── 12_saas-resources.yaml   # SaaS 利用リソース（Bedrock/Transcribe 用 IAM）
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
- **構成**: IAM ユーザー/ロール + 最小権限ポリシー
- **接続**: デスクトップアプリから boto3 で直接 AWS API を呼び出し

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

```bash
aws cloudformation deploy \
  --template-file templates/12_saas-resources.yaml \
  --stack-name screen-recorder-saas \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides file://parameters/dev.json
```

## アプリとの接続設定

### vLLM エンドポイント
デプロイ後、スタック出力の `VllmEndpoint` をアプリの設定に入力:
- 文字起こし設定 → バックエンド: vLLM → エンドポイント URL
- LLM 設定 → バックエンド: API → エンドポイント URL

### SaaS (Bedrock / Transcribe)
デプロイ後、スタック出力の `AccessKeyId` / `SecretAccessKey` をアプリの AWS 設定に入力。
または IAM ロールの場合は AWS プロファイルを設定。

## コスト目安（東京リージョン）

| リソース | 月額目安 |
|---------|---------|
| EC2 g5.xlarge (オンデマンド) | 約 $1.00/h ≒ $720/月 (常時稼働) |
| EC2 g5.xlarge (スポット) | 約 $0.30〜0.50/h |
| EBS gp3 100GB | 約 $9.60/月 |
| Bedrock (Claude Haiku) | $0.25/100万入力トークン |
| Transcribe | $0.024/分 |

> **ヒント**: vLLM サーバーは必要な時だけ起動し、不要時は停止することでコストを抑えられます。
