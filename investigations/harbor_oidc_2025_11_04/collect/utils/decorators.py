"""Decorators for Harbor OIDC investigation."""

from functools import wraps

from kubernetes.client.rest import ApiException


def handle_api_exception(return_on_error=""):
    """Decorator to handle expected K8s API exceptions.

    Only handles:
    - 404 (Not Found) - resource doesn't exist
    - 409 (Conflict) - resource was modified
    - 400 (Bad Request) - e.g., no previous container logs

    Does NOT catch programming errors or unexpected exceptions.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except ApiException as e:
                # Only handle expected error codes
                if e.status in [400, 404, 409]:
                    error_msg = f"Error in {func.__name__}: {e}"
                    # Assume logger exists - it's always initialized in __init__
                    self.logger.error(error_msg)
                    return return_on_error if return_on_error else error_msg
                # Re-raise unexpected API errors
                raise

        return wrapper

    return decorator
