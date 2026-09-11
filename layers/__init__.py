"""Root forwarding shim for agi_memory.layers."""
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import agi_memory.layers as _mod

class _ModuleWrapper(sys.modules[__name__].__class__):
    def __getattr__(self, name):
        return getattr(_mod, name)
    def __setattr__(self, name, value):
        setattr(_mod, name, value)
        super().__setattr__(name, value)

sys.modules[__name__].__class__ = _ModuleWrapper
from agi_memory.layers import *  # noqa: F401, F403
