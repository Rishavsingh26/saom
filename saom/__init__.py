"""SAOM - Self-Improving Agent Operating Memory."""

from saom.agent import SAOMAgent
from saom.config import get_memory_dir, ensure_memory

__version__ = "12.0.0"
__all__ = ["SAOMAgent", "get_memory_dir", "ensure_memory"]
