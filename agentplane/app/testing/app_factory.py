"""Build an app around in-process backends for isolated app tests, never for deployment."""

import inspect
from typing import Any

from fastapi import FastAPI

from agentplane.app.api import create_app as production_app
from agentplane.sandbox_service.provisioning import Provisioning


def create_app(*args: Any, **kwargs: Any) -> FastAPI:
    arguments = inspect.signature(production_app).bind_partial(*args, **kwargs)
    arguments.apply_defaults()
    values = arguments.arguments
    values["provisioner"] = Provisioning(
        values["inventory"],
        values["egress"],
        values["action_policy"],
        values["kubernetes_grants"] or {},
        values["kubernetes_bindings"],
    )
    return production_app(*arguments.args, **arguments.kwargs)
