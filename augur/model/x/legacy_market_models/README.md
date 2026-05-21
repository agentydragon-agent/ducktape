# Legacy Augur Market Models

This directory parks market-model code that is no longer part of the active
Augur runtime surface.

The active `augur/model` provider union now keeps only `simple` and native
`vecm`. The old generic legacy-provider path and unported exploratory models
were removed when the core-shaped exogenous-bundle surface was deleted. Bring any
of those ideas back only by reimplementing them as native models that return
`SampledExogenousBundle`.
