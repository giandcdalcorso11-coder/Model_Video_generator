import importlib.util
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


def test_install_copies_package_and_writes_build_bootstrap(install_module):
    install_module.install()

    dest_package = install_module.LIB_INSTALL_DIR / "resolve_plugin"
    assert dest_package.is_dir()
    assert (dest_package / "build_project.py").exists()
    assert (dest_package / "lua_codegen.py").exists()

    run_build = install_module.LIB_INSTALL_DIR / "run_build.py"
    assert run_build.exists()
    content = run_build.read_text(encoding="utf-8")
    assert "from resolve_plugin.build_project import main" in content
    assert str(install_module.LIB_INSTALL_DIR) in content

    assert install_module.PROJECTS_ROOT.is_dir()


def test_install_does_not_write_any_scripts_menu_launcher(install_module):
    """The new architecture has no static Resolve-facing script at all --
    each analyzed video gets its own generated .lua file, written later by
    build_project.py, not by install.py."""
    install_module.install()

    if install_module.SCRIPTS_EDIT_DIR.exists():
        assert list(install_module.SCRIPTS_EDIT_DIR.glob("*.lua")) == []
        assert list(install_module.SCRIPTS_EDIT_DIR.glob("*.py")) == []


def test_install_removes_stale_legacy_python_launcher(install_module):
    install_module.LEGACY_SCRIPTS_UTILITY_DIR.mkdir(parents=True, exist_ok=True)
    stale_file = install_module.LEGACY_SCRIPTS_UTILITY_DIR / "Auto Template.py"
    stale_file.write_text("# old launcher", encoding="utf-8")

    install_module.install()

    assert not stale_file.exists()


def test_install_removes_stale_edit_launchers_from_earlier_designs(install_module):
    install_module.SCRIPTS_EDIT_DIR.mkdir(parents=True, exist_ok=True)
    stale_py = install_module.SCRIPTS_EDIT_DIR / "Auto Template.py"
    stale_py.write_text("# old python launcher", encoding="utf-8")
    stale_lua = install_module.SCRIPTS_EDIT_DIR / "Auto Template.lua"
    stale_lua.write_text("-- old static lua launcher", encoding="utf-8")

    install_module.install()

    assert not stale_py.exists()
    assert not stale_lua.exists()
