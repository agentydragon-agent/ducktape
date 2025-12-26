"""Enhanced FastMCP with batteries included.

This module provides EnhancedFastMCP, a FastMCP subclass that bundles common enhancements:
- Session capturing & out-of-band notification broadcasts
- Structured ValidationError formatting (for flat-model tools)
- OpenAI strict mode schema validation (optional, enabled by default)
- Auto-advertise subscribe capability
- Experimental capabilities support
- .flat_model() convenience method
"""

from mcp_infra.enhanced.server import EnhancedFastMCP

__all__ = ["EnhancedFastMCP"]
