# Architecture

## 目的

NPU Codexは、Codex CLIのエージェントハーネスと、Intel NPUで動く小型モデルの間を接続するローカルプロトコルアダプターです。モデルにOS権限を直接与えず、Codexが既に持つツール実行・承認・サンドボックス境界を維持します。

## コンポーネント

### Codex CLI

- リポジトリの作業コンテキストを管理
- 利用可能なツール定義をResponses APIリクエストへ格納
- `function_call`または`custom_tool_call`を受け、承認ポリシーに従って実行
- ツール結果を次ターンの入力として送信

### Responses bridge

FastAPIで実装したloopback限定HTTPサービスです。

1. gzip / zstdを展開し、圧縮前後のサイズを制限
2. Codexの`input`履歴をテキストレコードへ正規化
3. ツール定義を小型モデル向けの簡略カタログへ変換
4. モデルに「単一JSON action」を生成させる
5. actionを解析し、受信したツール定義と照合
6. Responses APIの出力itemとSSEイベントへ変換

ブリッジは、シェル、Git、ファイルI/Oのエージェントツールを実装しません。

### OpenVINO backend

- `openvino_genai.LLMPipeline`
- 既定デバイスは`NPU`
- 1つのパイプラインへの生成要求をロックで直列化
- 初回アクセス時に遅延ロード
- `CACHE_DIR`でコンパイルキャッシュを保持
- NPU時に`MAX_PROMPT_LEN`、`MIN_RESPONSE_LEN`、`PREFILL_HINT`、`GENERATE_HINT`を設定

### Mock backend

HTTP、SSE、Codex設定、セキュリティ境界の確認用です。実際の推論は行いません。

## ターン処理

```text
Codex request
  └─ instructions
  └─ input history
  └─ tools
       │
       ▼
normalize + budget
       │
       ▼
small-model prompt
       │
       ▼
{"type":"tool_call", ...}
       │
       ▼
parse + validate
       ├─ invalid → repair prompt（設定回数まで）
       └─ valid
             │
             ▼
Responses output item / SSE
             │
             ▼
Codex executes under its policy
```

## 小型モデル向けコンテキスト削減

全文をモデルへ渡すとNPUのコンテキスト上限とTTFTが問題になるため、次を行います。

- 最新の履歴itemを優先
- 画像・音声はプレースホルダー化
- 長いtool outputを切詰め
- tool schemaから主要フィールドだけを抽出
- `prompt_char_budget`と`tool_schema_char_budget`を別管理
- 省略件数をresponse metadataへ記録

これは意味的要約ではなく、決定的な切詰めです。将来、ローカル要約器やリポジトリ索引を追加する余地があります。

## Responses API互換範囲

実装対象:

- text message output
- function call output
- custom tool call output
- non-streaming response
- SSE streaming
- usageの概算
- gzip / zstd request body

未実装または限定的:

- hosted tools
- computer use固有の完全なitem semantics
- image/audio推論
- server-side previous response storage
- remote compaction
- WebSocket transport
- Responses APIの全フィールド

## 失敗時の原則

モデル出力が不正な場合、未検証のツール要求をCodexへ渡しません。再生成に失敗した場合は、ツールを実行せず、検証失敗を示す通常メッセージへフォールバックします。
