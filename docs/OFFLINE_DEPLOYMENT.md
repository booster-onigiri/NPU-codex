# Offline Deployment

## 準備用PCがない場合（portable bundle）

GitHub Actionsの`portable-windows-bundle`を手動実行すると、対象PCへPython、
Node.js、Codex CLIをインストールせずに使える`NPUCodexPortable.zip`を生成できます。

1. GitHubの**Actions**から`portable-windows-bundle`を選ぶ
2. **Run workflow**を開く
3. 最初の接続確認だけなら`include_model=false`、物理NPU試験なら`true`を選ぶ
4. 完了後、Artifactsの`NPUCodexPortable-<commit>`をダウンロードする
5. ZIPと`.sha256.txt`を対象PCへ持ち込み、ハッシュを照合する

対象PCでは次だけを実行します。

```powershell
Expand-Archive .\NPUCodexPortable.zip -DestinationPath C:\Tools\NPUCodex
cd C:\Tools\NPUCodex
powershell -ExecutionPolicy Bypass -File .\scripts\initialize-portable.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\collect-validation.ps1
```

モデルなしartifactでは`initialize-portable.ps1 -Mock`を使用してください。生成された
`validation-<日時>.zip`を解析用に共有できます。ログには認証情報や文書本文を収集しません。

> [!IMPORTANT]
> GitHubホストrunnerで作成したbundleであり、物理Intel NPU上の動作を保証するものでは
> ありません。`include_model=true`はモデル取得・変換に時間がかかり、artifact容量制限で
> 失敗する可能性があります。その場合はruntimeとモデルを別artifactへ分割します。

## 前提

閉域PCへ持ち込む前に、組織のソフトウェア導入申請、媒体検査、ライセンス確認、脆弱性確認を完了してください。ここでいう「offline」は、Python依存関係とモデルを外部通信なしで導入できることを指し、OSレベルの通信遮断を自動設定するものではありません。

## 準備用PC

リポジトリを取得し、Python 3.11または3.12を用意します。

```powershell
git clone https://github.com/booster-onigiri/NPU-codex.git
cd NPU-codex
powershell -ExecutionPolicy Bypass -File .\scripts\prepare-offline-bundle.ps1 `
  -OutputDirectory C:\Temp\NPUCodexOffline `
  -IncludeExporter
```

出力内容:

```text
NPUCodexOffline\
  wheelhouse\
  scripts\
  docs\
  README.md
  LICENSE
  config.example.toml
  SHA256SUMS.txt
NPUCodexOffline.zip
NPUCodexOffline.zip.sha256.txt
```

`-IncludeExporter`はモデル変換用依存関係もwheelhouseへ含めます。業務PCでは変換せず、準備用PCで変換済みモデルを持ち込む方が依存関係と通信経路を減らせます。

## モデルを含める

ライセンス上許可され、容量にも問題がない場合だけ明示します。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare-offline-bundle.ps1 `
  -OutputDirectory C:\Temp\NPUCodexOffline `
  -ModelDirectory C:\Models\QwenCoder15B-INT4-SYM-G128
```

モデルは`models\local-coder`へコピーされます。モデルカード、ライセンス、取得元URL、取得日、SHA-256を別途記録してください。

## ハッシュ確認

準備用PCで生成されたZIPハッシュを照合します。

```powershell
Get-FileHash .\NPUCodexOffline.zip -Algorithm SHA256
Get-Content .\NPUCodexOffline.zip.sha256.txt
```

展開後は`SHA256SUMS.txt`と各ファイルを照合します。組織のマルウェア検査も実施してください。

## 閉域PCへ導入

```powershell
Expand-Archive .\NPUCodexOffline.zip -DestinationPath C:\Tools\NPUCodex
cd C:\Tools\NPUCodex
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 `
  -Wheelhouse .\wheelhouse
```

mockだけを導入する場合:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 `
  -Wheelhouse .\wheelhouse `
  -Mock
```

## 外部通信を抑止する補助設定

`start-local-codex.ps1 -Offline`は、Hugging Face関連ライブラリのoffline環境変数を設定します。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-codex.ps1 `
  -Workspace C:\Work\Repository `
  -Offline
```

これは一般的なHTTP通信を完全には遮断しません。厳格な閉域運用では、Windows Firewall、プロキシ、アプリケーション制御、ネットワーク分離を組織側で設定してください。

## 更新

更新時は差分だけを上書きせず、新しいbundleを別フォルダへ展開して次を確認します。

1. wheelとモデルのハッシュ
2.依存バージョン
3. `CHANGELOG.md`
4. mock test
5. NPU doctor
6. 実リポジトリのコピーを使った回帰試験

`.codex-local`と`config.local.toml`は環境固有です。更新bundleへ安易に同梱しないでください。
