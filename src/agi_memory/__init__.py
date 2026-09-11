"""agi-memory: Turnkey zero-dependency two-layer memory architecture for AI coding assistants."""
__version__ = "0.1.1"

from .layers.session_layer import SessionLayer
from .layers.graph_layer import GraphLayer
from .recall import recall
from .config import get_data_dir, get_vault_dir, get_default_db
from .vault import (
    init_vault,
    export_dirty_to_vault,
    import_from_vault,
    deduplicate_and_compact,
)
from .bootstrap import bootstrap_project

__all__ = [
    "SessionLayer",
    "GraphLayer",
    "recall",
    "get_data_dir",
    "get_vault_dir",
    "get_default_db",
    "init_vault",
    "export_dirty_to_vault",
    "import_from_vault",
    "deduplicate_and_compact",
    "bootstrap_project",
    "__version__",
]
