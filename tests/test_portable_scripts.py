from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_runtime_resolver_prefers_portable_python_and_codex() -> None:
    text = (ROOT / "scripts" / "runtime-paths.ps1").read_text(encoding="utf-8")
    assert 'runtime\\python\\python.exe' in text
    assert 'runtime\\codex\\codex.exe' in text
    assert text.index("$PortablePython") < text.index("$VenvPython", text.index("function"))


def test_portable_entry_points_use_shared_runtime_resolver() -> None:
    names = [
        "configure-codex.ps1",
        "doctor.ps1",
        "smoke-test.ps1",
        "start-bridge.ps1",
        "start-local-codex.ps1",
    ]
    for name in names:
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "runtime-paths.ps1" in text, name
        assert "Get-NpuCodexPython" in text, name


def test_portable_workflow_does_not_require_target_pc_toolchain() -> None:
    text = (ROOT / ".github" / "workflows" / "portable-bundle.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch" in text
    assert "build-portable-bundle.ps1" in text
    assert "initialize-portable.ps1" in text
