import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT_PATH = REPO_ROOT / "scripts" / "install.py"


def _load_install_module():
    spec = importlib.util.spec_from_file_location("auto_template_install_script", INSTALL_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def install_module(tmp_path, monkeypatch):
    module = _load_install_module()

    lib_dir = tmp_path / "lib"
    projects_root = tmp_path / "projects"
    scripts_edit_dir = tmp_path / "resolve_scripts" / "Edit"
    scripts_utility_dir = tmp_path / "resolve_scripts" / "Utility"

    monkeypatch.setattr(module, "LIB_INSTALL_DIR", lib_dir)
    monkeypatch.setattr(module, "PROJECTS_ROOT", projects_root)
    monkeypatch.setattr(module, "SCRIPTS_EDIT_DIR", scripts_edit_dir)
    monkeypatch.setattr(module, "LEGACY_SCRIPTS_UTILITY_DIR", scripts_utility_dir)

    return module


def test_lua_string_literal_escapes_backslashes_and_quotes(install_module):
    assert install_module._lua_string_literal(r"C:\Users\giand\App") == r"C:\\Users\\giand\\App"
    assert install_module._lua_string_literal('say "hi"') == 'say \\"hi\\"'


def test_install_copies_package_and_writes_bootstrap(install_module, tmp_path):
    install_module.install()

    dest_package = install_module.LIB_INSTALL_DIR / "resolve_plugin"
    assert dest_package.is_dir()
    assert (dest_package / "analyze_cli.py").exists()

    run_analysis = install_module.LIB_INSTALL_DIR / "run_analysis.py"
    assert run_analysis.exists()
    content = run_analysis.read_text(encoding="utf-8")
    assert "from resolve_plugin.analyze_cli import main" in content
    assert str(install_module.LIB_INSTALL_DIR) in content

    assert install_module.PROJECTS_ROOT.is_dir()


def test_install_writes_lua_launcher_with_placeholders_substituted(install_module):
    install_module.install()

    lua_path = install_module.SCRIPTS_EDIT_DIR / "Auto Template.lua"
    assert lua_path.exists()
    content = lua_path.read_text(encoding="utf-8")

    assert "__PYTHON_EXE__" not in content
    assert "__LIB_DIR__" not in content
    assert "__PROJECTS_ROOT__" not in content
    assert 'PYTHON_EXE = "python"' in content


def test_install_removes_stale_legacy_python_launcher(install_module):
    install_module.LEGACY_SCRIPTS_UTILITY_DIR.mkdir(parents=True, exist_ok=True)
    stale_file = install_module.LEGACY_SCRIPTS_UTILITY_DIR / "Auto Template.py"
    stale_file.write_text("# old launcher", encoding="utf-8")

    install_module.install()

    assert not stale_file.exists()
