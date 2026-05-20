# Legacy Augur Market Models

This directory parks market-model code that is no longer part of the active
Augur runtime surface.

The active `augur/model` provider union now keeps only `noop`, `simple`, and
native `vecm`. The old generic `MacroMarketBundleProvider` path and unported
exploratory models live here for later porting to `SampledMarketBundle` or
deletion.

The files are intentionally not wired into active Bazel targets.
