"""Plugin entry point.

Resolve injects `bmd` (and `resolve`, `fusion`, `fu`) into the global
namespace of whatever script it executes from the Scripts menu -- it is
never something you `import`. To keep this module both correct under
Resolve and testable outside it, `main()` takes `bmd` as an explicit
argument; the actual script Resolve loads is a tiny generated launcher
(see scripts/install.py) that does `main(bmd)`, passing along the object
Resolve gave it.
"""
from __future__ import annotations

from typing import Any


def main(bmd: Any) -> None:
    from resolve_plugin.ui.main_window import AutoTemplateWindow

    window = AutoTemplateWindow(bmd)
    window.run()


if __name__ == "__main__":
    # Convenience path if this file itself is pasted directly as a Resolve
    # script (rather than installed via scripts/install.py) and
    # resolve_plugin is already importable (e.g. installed with `pip install
    # -e .`). Resolve puts `bmd` in this module's own globals in that case.
    main(globals().get("bmd"))
