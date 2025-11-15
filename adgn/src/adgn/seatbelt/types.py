from __future__ import annotations

import re
from typing import Annotated

from pydantic import StringConstraints

# Single source of truth for template/policy name validation
TEMPLATE_NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"
TEMPLATE_NAME_RE = re.compile(TEMPLATE_NAME_PATTERN)

# Pydantic newtype (Annotated) with embedded validation
TemplateName = Annotated[str, StringConstraints(pattern=TEMPLATE_NAME_PATTERN, min_length=1, max_length=64)]
