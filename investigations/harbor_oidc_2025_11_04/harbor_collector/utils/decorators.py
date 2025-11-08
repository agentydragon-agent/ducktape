"""Decorators for Harbor OIDC investigation."""

from functools import wraps

from kubernetes.client.rest import ApiException


def handle_api_exception(return_on_error=""):
    """Decorator to handle K8s API exceptions consistently."""

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except ApiException as e:
                error_msg = f"Error in {func.__name__}: {e}"
                # Assume logger exists - it's always initialized in __init__
                self.logger.error(error_msg)
                return return_on_error if return_on_error else error_msg

        return wrapper

    return decorator
