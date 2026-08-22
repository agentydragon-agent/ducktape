"""Canonical simulator state is represented by :mod:`finance.augur.sim.output`.

The simulator no longer maintains a parallel Polars state-history schema. Dense state
arrays retain their native month/rollout/slot axes and are consumed directly by the
engine, product projection, and focused behavioral tests. Event schemas live in
``sim.events`` because event decoding remains part of the public read model.
"""
