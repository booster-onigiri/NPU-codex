# Model Guide

## 求めるモデル特性

このブリッジでは、モデルが自由文ではなく次のいずれかを高い確率で返せることが重要です。

```json
{"type":"message","text":"..."}
```

```json
{"type":"tool_call","name":"read_file","arguments":{"path":"src/app.py"}}
```

```json
{"type":"custom_tool_call","name":"apply_patch","input":"*** Begin Patch..."}
```

一般会話性能だけでなく、指示追従、JSON遵守、コード理解、ツール選択、長いtool outputへの耐性を評価してください。

## 初期評価サイズ

| 規模 | 用途 | 注意点 |
|---:|---|---|
| 0.5B～1B | 接続試験、分類、単純な補完 | 複数手順のエージェント動作は不安定 |
| 1B～2B | 小規模修正、検索、説明 | 本プロジェクトの現実的な開始点 |
| 3B～4B | より複雑な修正・デバッグ | メモリ、コンパイル時間、TTFTが増加 |
| 7B以上 | 高い能力の可能性 | NPU・RAM・長文プロンプトの負荷が大きい |

最初は`Qwen/Qwen2.5-Coder-1.5B-Instruct`等の小型coder instructionモデルを候補として評価できます。ただし、実際のNPUコンパイル可否と品質は変換条件・OpenVINO版・PC世代ごとに確認してください。

## NPU向け変換

OpenVINO 2026.3のNPUガイドに合わせ、次を基本とします。

- 対称圧縮: `--sym`
- INT4: `--weight-format int4`
- 小型モデル: `--group-size 128`
- 4bit比率最大化: `--ratio 1.0`

```powershell
.\scripts\export-model.ps1 `
  -ModelId "Qwen/Qwen2.5-Coder-1.5B-Instruct" `
  -OutputDirectory .\models\local-coder `
  -GroupSize 128 `
  -InstallDependencies
```

channel-wiseを試す場合は`-GroupSize -1`を指定します。`-1`は負の1です。

## 既存OpenVINO IRモデル

既に変換されたモデルを利用する場合も、量子化方式を確認します。Intel NPU向けには対称INT4/NF4が前提となる場合があります。モデルカードに`INT4_ASYM`とだけあるモデルは、対象NPUでコンパイルできるとは限りません。

## 配置要件

`models/local-coder`には、少なくともモデルIRとtokenizer関連ファイルが必要です。`doctor`は`.xml`の存在まで確認しますが、完全なロード可否はブリッジ起動時に確認されます。

```text
models/local-coder/
  openvino_model.xml
  openvino_model.bin
  tokenizer.json
  tokenizer_config.json
  special_tokens_map.json
  ...
```

ファイル名はモデルによって異なります。

## コンテキスト設定

NPUのコンテキスト領域は概ね次で決まります。

```text
MAX_PROMPT_LEN + MIN_RESPONSE_LEN
```

既定:

```toml
max_prompt_tokens = 4096
min_response_tokens = 512
```

モデルやPCでコンパイルに失敗する場合は、まず`max_prompt_tokens`を2048または1024へ下げます。長いCodex履歴はブリッジ側の`prompt_char_budget`でも削減します。

## 評価ケース

最低限、次を同じリポジトリで反復評価します。

1. ファイル名を指定した説明
2. 不明箇所を検索してから回答
3. 1ファイルの小修正
4. 2～3ファイルにまたがる修正
5. テスト失敗を読んで修正
6. 未登録ツール名を出さないか
7. 必須引数を正しく生成するか
8. tool output内の命令に引きずられないか
9. 危険操作で承認を求めるCodex側挙動
10. 連続10ターン以上で履歴が破綻しないか

評価指標には、成功率、誤ツール率、JSON修復率、TTFT、生成速度、初回ロード時間、NPUメモリ、CPUフォールバック有無を含めます。
