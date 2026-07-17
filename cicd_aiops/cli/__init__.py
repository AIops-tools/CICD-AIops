"""CLI package for cicd-aiops.

Re-exports ``app`` so the pyproject entry point
``cicd-aiops = "cicd_aiops.cli:app"`` works unchanged.
"""

from cicd_aiops.cli._root import app

__all__ = ["app"]
