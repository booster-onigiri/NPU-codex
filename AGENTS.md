# Repository Instructions

- Python 3.11以上を対象とする。
- 公開APIと設定変更にはテストを追加する。
- `python -m compileall -q src tests`、`python -m ruff check .`、`python -m pytest -q`を実行する。
- Responses API互換コードは、公式Codexの現在のwire formatを確認してから変更する。
- OpenVINO NPU設定と依存versionは、同一release familyで揃える。
- bridgeへシェル実行・ファイル編集機能を追加しない。ツール実行はCodex側の責務とする。
- loopback制約、Host検証、サイズ制限、ツール検証を弱めない。
- モデル、`.env`、`auth.json`、`.codex-local`、実データをcommitしない。
- 物理NPUで未検証の内容は、その旨を明記する。
