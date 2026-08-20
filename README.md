# NPU Codex

Intel NPU上の小型ローカルLLMを、OpenAI Codex CLIの推論バックエンドとして使うための実験的なResponses APIブリッジです。

Codex CLIが持つファイル参照、シェル実行、パッチ適用、承認、サンドボックス等のエージェント機能はそのまま利用し、モデル推論だけをOpenVINO GenAIの`LLMPipeline`へ置き換えます。ブリッジ自身はファイル編集やコマンド実行を行いません。モデルが返したツール要求を検証し、Codex CLIへ返すことに専念します。

> [!WARNING]
> 本プロジェクトはα版です。OpenAI、Intel、OpenVINOの公式製品ではなく、各社との提携・承認を示すものでもありません。実際の業務利用前に、組織の情報セキュリティ規程、モデルライセンス、ソフトウェア持込み手続、出力精度を確認してください。

## 現在の到達点

- Codex向けOpenAI Responses API互換エンドポイント
- 通常応答、JSON Schema function tool、free-form custom tool
- gzip / zstdリクエスト、SSEストリーミング、keep-alive
- OpenVINO GenAIによるIntel NPU推論
- NPU未搭載環境で動作確認できる決定的mock backend
- 受信ツール一覧との照合、基本的なJSON Schema検証、誤出力の再生成
- loopback限定待受、Host検証、任意Bearer認証、リクエストサイズ制限
- 専用`CODEX_HOME`の生成によるクラウド認証情報との分離
- Windows向けオンライン／オフライン導入スクリプト

物理NPU上のモデルごとの精度・速度は、対象PC、NPUドライバー、OpenVINO、モデル変換条件に依存します。このリポジトリにはモデル重みを含めません。

## アーキテクチャ

```text
利用者
  │
  ▼
OpenAI Codex CLI
  │  POST /v1/responses
  │  function_call / custom_tool_call / SSE
  ▼
NPU Codex bridge (127.0.0.1 only)
  ├─ Codex履歴を小型モデル向けに圧縮
  ├─ ツール定義を簡略化
  ├─ モデル出力をJSONとして解析
  ├─ ツール名・引数を受信定義と照合
  └─ Responses APIイベントへ変換
  │
  ▼
OpenVINO GenAI LLMPipeline
  │
  ▼
Intel NPU
```

詳細は[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)を参照してください。

## 動作条件

- Windows 11
- Intel NPUを搭載し、OpenVINOから`NPU`として認識できるPC
- Python 3.11または3.12を推奨
- OpenAI Codex CLI
- PowerShell 5.1以降
- NPU対応形式へ変換済みのOpenVINO IRモデル

OpenVINO 2026.3系を基準にしています。NPUドライバーは対象PCメーカーまたはIntelが提供する適合版を使用してください。

## まずmock backendで確認する

NPUやモデルを用意する前に、Codexとの接続経路だけを確認できます。

```powershell
git clone https://github.com/booster-onigiri/NPU-codex.git
cd NPU-codex

powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Mock
powershell -ExecutionPolicy Bypass -File .\scripts\start-bridge.ps1
```

別のPowerShellを開きます。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\configure-codex.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-codex.ps1 `
  -Workspace C:\Work\SampleRepository
```

mock backendは実際のコード判断を行わず、接続確認用メッセージだけを返します。

## Intel NPUで起動する

### 1. Python環境を作成

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

`config.local.toml`が生成され、既定では次の設定になります。

```toml
[model]
backend = "openvino"
path = "models/local-coder"
device = "NPU"
allow_cpu_fallback = false
```

意図しないCPU実行を避けるため、既定ではCPUへフォールバックしません。

### 2. モデルを配置

推奨する初期評価候補は、1B～4B級のinstruction/coderモデルです。NPU向けには、対称INT4、`group-size 128`または`-1`で変換します。

接続可能な検証用PCで変換する例です。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export-model.ps1 `
  -ModelId "Qwen/Qwen2.5-Coder-1.5B-Instruct" `
  -OutputDirectory .\models\local-coder `
  -InstallDependencies
```

モデルの利用条件や外部配布可否は、モデルカードと組織規程を必ず確認してください。詳細は[`docs/MODEL_GUIDE.md`](docs/MODEL_GUIDE.md)にあります。

### 3. 診断

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\doctor.ps1
```

`inference_device`の`available`に`NPU`が含まれることを確認します。診断はモデルをコンパイルしないため、最終確認には実際の起動とsmoke testも必要です。

### 4. ブリッジ起動

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-bridge.ps1
```

初回起動時はNPU向けコンパイルに時間がかかる場合があります。生成されたコンパイルキャッシュは`.cache/openvino`に保存されます。

### 5. Codex専用設定を生成

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\configure-codex.ps1
```

`.codex-local/config.toml`が生成されます。通常の`%USERPROFILE%\.codex`とは分離され、`requires_openai_auth = false`のローカルプロバイダーを使用します。`.codex-local`へ`auth.json`をコピーしないでください。

### 6. ローカルCodexを起動

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-codex.ps1 `
  -Workspace C:\Work\TargetRepository
```

`codex --oss`は使いません。このブリッジは専用のResponses APIプロバイダーとして設定します。

## 任意のBearer認証

同一PC上の別プロセスからのアクセスも制限したい場合、`config.local.toml`を次のように設定します。

```toml
[security]
api_token_env = "NPU_CODEX_API_TOKEN"
```

起動前に同じPowerShellセッションで設定します。

```powershell
$env:NPU_CODEX_API_TOKEN = "十分に長いランダム値"
```

Codexは生成されたprovider設定の`env_key`から、この値をBearerトークンとして送信します。トークンを設定ファイルやリポジトリへ保存しないでください。

## 閉域PCへの持込み

接続可能な準備用Windows PCで、依存wheelと必要ファイルをまとめます。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare-offline-bundle.ps1 `
  -OutputDirectory C:\Temp\NPUCodexOffline `
  -IncludeExporter
```

業務PCで展開後、次を実行します。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 `
  -Wheelhouse .\wheelhouse
```

モデルをバンドルへ含める場合は、ライセンスと持込み容量を確認した上で`-ModelDirectory`を明示します。詳細は[`docs/OFFLINE_DEPLOYMENT.md`](docs/OFFLINE_DEPLOYMENT.md)を参照してください。

## 設定

主な設定は`config.local.toml`です。

| 設定 | 既定値 | 意味 |
|---|---:|---|
| `server.host` | `127.0.0.1` | 待受アドレス。loopback以外は既定で拒否 |
| `model.device` | `NPU` | OpenVINO推論デバイス |
| `model.max_prompt_tokens` | `4096` | NPUパイプラインの最大入力長 |
| `model.min_response_tokens` | `512` | NPUパイプラインの応答用領域 |
| `model.max_new_tokens` | `768` | 1回のモデル生成上限 |
| `agent.prompt_char_budget` | `10000` | 小型モデルへ渡すプロンプト文字数上限 |
| `agent.max_repair_attempts` | `1` | 不正なJSON／ツール要求の再生成回数 |
| `security.max_request_bytes` | `16777216` | 圧縮前後のリクエスト上限 |

## API

- `GET /healthz` — プロセスとbackend状態
- `GET /readyz` — モデルロード状態
- `GET /v1/models` — ローカルモデル一覧
- `POST /v1/responses` — Responses API互換エンドポイント

これはCodex接続に必要な最小サブセットであり、OpenAI Responses API全体の完全実装ではありません。

## テスト

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
```

CIはWindows／Linux上のmock backendで、プロトコル、SSE、圧縮、認証、ツール検証を確認します。物理NPU試験はCIに含みません。

## 重要な制約

- 1B～4B級モデルはクラウド版Codexと同等の推論能力ではありません。
- 長いリポジトリ全体の理解、大規模設計変更、複雑なデバッグでは失敗しやすくなります。
- モデルはCodexから提示されたツールを選べます。実行可否はCodex側の承認・サンドボックス設定にも依存します。
- ブリッジはツール引数を完全なJSON Schema実装で検証するものではありません。
- Codex CLIやOpenVINOの更新により互換性が変わる可能性があります。
- 生成コードと実行コマンドは、人が差分・影響範囲を確認してください。

セキュリティ設計は[`docs/SECURITY.md`](docs/SECURITY.md)、脆弱性報告方法は[`SECURITY.md`](SECURITY.md)を参照してください。

## ライセンス

本リポジトリのコードはMIT Licenseです。モデル、Codex CLI、OpenVINO、その他依存ソフトウェアには、それぞれ別のライセンスが適用されます。
