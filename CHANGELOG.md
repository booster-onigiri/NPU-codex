# Changelog

## Unreleased

- Add a GitHub Actions-built Windows portable bundle with embedded Python and Codex CLI.
- Add portable runtime resolution, first-run initialization, and validation log collection.
- Allow optional Qwen2.5-Coder-1.5B INT4 OpenVINO model export in the bundle workflow.

## 0.1.0 - 2026-08-21

### Added

- OpenAI Responses API互換のloopback bridge
- Intel NPU向けOpenVINO GenAI backend
- mock backend
- message、function call、custom tool call
- SSE streamingとkeep-alive
- gzip / zstd request decoding
- tool nameと基本JSON Schema検証
- 不正model actionの限定再生成
- 専用Codex config生成
- Windows導入、診断、モデル変換、offline bundleスクリプト
- Windows／Linux CI
