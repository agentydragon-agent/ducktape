import sys

from aiquota.models import AllQuotas


def render(quotas: AllQuotas) -> None:
    sys.stdout.write(quotas.model_dump_json(indent=2))
    sys.stdout.write("\n")
