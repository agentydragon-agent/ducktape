from __future__ import annotations

import pytest

from tests._markers import REQUIRES_SANDBOX_EXEC

pytestmark = [*REQUIRES_SANDBOX_EXEC, pytest.mark.shell]
