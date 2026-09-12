"""agi-memory: Turnkey zero-dependency four-pillar cognitive memory framework for AI coding assistants."""
__version__ = "0.4.0"

from .layers.session_layer import SessionLayer
from .layers.graph_layer import GraphLayer
from .layers.episodic_layer import EpisodicLayer
from .layers.code_layer import CodeLayer
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
    "EpisodicLayer",
    "CodeLayer",
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
