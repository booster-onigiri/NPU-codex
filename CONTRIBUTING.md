# Contributing

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
```

NPUは通常の単体テストに不要です。OpenVINO backendを変更する場合は、mock testに加え、対象NPU上でモデルロード、1ターン、tool call、連続ターンを確認してください。

## Pull requests

- 変更目的を1つに絞る
- Responses APIの追加対応にはfixtureまたは単体テストを追加
- セキュリティ境界を緩和する変更は脅威と代替案を記載
- NPU依存versionを変更する場合は公式互換表とWindowsで確認
- モデル重み、キャッシュ、認証情報、業務データをcommitしない

## Design principles

1. モデルを信頼しない
2. ツール実行はCodex側に残す
3. loopback限定を既定にする
4. CPUフォールバックは明示的にする
5. 小型モデル向けにプロトコルを単純化する
6. 不正actionは実行せず安全に失敗する
