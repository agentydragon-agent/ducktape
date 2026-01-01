"""High-level operations that compose workspace and export functionality.

This layer exists to break circular dependencies between workspace.py and export/convert.py.
"""

from tana.domain.types import NodeId
from tana.export.convert import export_node_as_tanapaste
from tana.query.nodes import get_image_url
from tana.workspace import Workspace

# Re-export for convenience
__all__ = ["export_tanapaste", "get_image_url"]


def export_tanapaste(workspace: Workspace, node_id: NodeId) -> str:
    """Export a node as TanaPaste format.

    Args:
        workspace: The workspace containing the node
        node_id: ID of the node to export

    Returns:
        TanaPaste formatted string
    """
    return export_node_as_tanapaste(workspace.graph, workspace.node(node_id))
