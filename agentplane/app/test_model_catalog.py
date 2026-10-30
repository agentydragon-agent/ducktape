import pytest
import pytest_bazel

from agentplane.app.model_catalog import CentralSamplerChoice, ModelCatalog, ModelOption
from agentplane.runner.harness import Harness


def test_central_sampler_models_require_a_named_runtime() -> None:
    models = [ModelOption(model="central", display_name="Central", reasoning_efforts=["high"])]
    harnesses = {Harness.CLAUDE: [], Harness.CODEX: [], Harness.CENTRAL_SAMPLER: ["central"]}
    with pytest.raises(ValueError, match="central_sampler"):
        ModelCatalog(models=models, harnesses=harnesses)
    catalog = ModelCatalog(models=models, harnesses=harnesses, central_sampler=CentralSamplerChoice(service="central"))
    assert catalog.central_sampler is not None
    assert catalog.central_sampler.service == "central"


def test_native_catalog_does_not_offer_central_sampler_by_default() -> None:
    catalog = ModelCatalog(
        models=[ModelOption(model="native", display_name="Native", reasoning_efforts=[])],
        harnesses={Harness.CLAUDE: ["native"], Harness.CODEX: ["native"]},
    )
    assert catalog.central_sampler is None
    assert Harness.CENTRAL_SAMPLER not in catalog.harnesses


if __name__ == "__main__":
    pytest_bazel.main()
