# Large Web Corpus Debundle Profile, 2026-05-20

This profile was captured from a private consumer corpus using the source-built
Ducktape debundler target (`@ducktape//devinfra/js/debundle:debundle`), not the
prebuilt binary. Private product names, snapshot identifiers, repository paths,
and module names are intentionally omitted.

## Input Scale

- Main chunk requested logical modules: 2,006.
- Main chunk final modules: 2,006.
- Main chunk selected owners: 7,532.
- Owner graph nodes: 9,709.
- Owner graph edges: 26,444.
- Module graph nodes: 2,007.
- Module graph edges: 7,516.
- Report files emitted: 2,898.
- Runtime files emitted: 2,071.

## Runs

The first Bazel build used a fresh output base and the source-built Ducktape
target. Remote cache was still enabled for normal build inputs, so the cleanest
debundler-only measurement is the direct local replay of the Bazel action.

Fresh-output-base Bazel build:

| metric                                         |     value |
| ---------------------------------------------- | --------: |
| total Bazel runtime                            | 142.742 s |
| Bazel critical path                            |  38.223 s |
| source-built debundler binary on critical path |   1.631 s |
| debundle action on critical path               |   4.125 s |
| cached debundler stdout stage total            |  25.940 s |

Direct local action replay:

| metric                |       value |
| --------------------- | ----------: |
| debundler stage total |    34.447 s |
| `/usr/bin/time` wall  |     35.15 s |
| user time             |     19.79 s |
| system time           |     18.41 s |
| max RSS               | 815,796 KiB |
| major faults          |           1 |
| minor faults          |     213,274 |

Direct replay stage timings:

| stage                                |     time |
| ------------------------------------ | -------: |
| `emit_browser_harness`               | 18.781 s |
| `materialize_logical_modules`        | 13.196 s |
| `prepare_js_chunks`                  |  1.212 s |
| `apply_bundled_partial_vendor_swaps` |  0.506 s |
| `strip_swapped_vendor_exports`       |  0.209 s |
| `swap_vendor_chunks`                 |  0.178 s |
| `load_transform_spec`                |  0.107 s |
| `validate_emitted_exports`           |  0.088 s |
| `load_js_chunks`                     |  0.068 s |

## CPU Profile

`perf record -F 99 -e cycles:u --call-graph dwarf,8192` captured 3,755
samples. The useful host section is the `cpu_core/cycles/u` section.

Top CPU stacks:

| stack                                                                   | children |
| ----------------------------------------------------------------------- | -------: |
| `lowering::materialize::materialize_logical_chunk`                      |   72.33% |
| `analysis::chunk_factorization::ChunkFactorization::owner_graph_report` |   47.75% |
| `analysis::reports::build_owner_graph_report`                           |   15.65% |
| `lowering::materialize_logical_modules`                                 |    9.39% |
| `emit_harness::emit_browser_harness`                                    |    9.31% |
| libc write path (`__GI___libc_write`)                                   |    4.42% |
| `lowering::materialize::build_directory_dependency_facts`               |    2.40% |

The CPU profile says the main CPU bottleneck is still owner-graph and
peelability report generation inside logical-module materialization. Browser
harness emission is the largest wall-clock stage in the direct timing, but it
does not dominate sampled CPU as strongly; part of that stage appears to be
write-heavy output work.

## Heap Profile

Plain `heaptrack` was not used for public findings because the installed
wrapper auto-opened the GUI analysis step unless `--record-only` is passed.
Use `heaptrack --record-only` in future agent runs.

Massif was run with:

```sh
valgrind --tool=massif --trace-children=yes --time-unit=ms \
  --max-snapshots=100 --detailed-freq=1 --threshold=0.5
```

Massif direct replay:

| metric                       |         value |
| ---------------------------- | ------------: |
| Valgrind stage total         |     4m09.824s |
| peak snapshot                |            38 |
| peak total heap profile size | 610,158,840 B |
| peak useful heap             | 559,324,697 B |
| allocator overhead           |  50,834,143 B |

Peak retained heap is dominated by parsed JavaScript AST/source structures from
SWC parser paths. Massif did not point at owner-graph report structures as the
largest retained heap consumer, even though owner-graph generation dominates
CPU. That suggests CPU fixes should focus on graph/report work first, while
memory work should separately investigate AST/source lifetime after parsing and
materialization.

## Findings

1. `emit_browser_harness` is the largest wall-clock stage on this run.

   The direct run spent 18.781 s there, versus 13.196 s in
   `materialize_logical_modules`. CPU samples under `emit_harness` are much
   lower than the wall share, with visible write-path samples, so inspect
   output volume, duplicated serialization, and file write behavior before
   assuming a pure compute hotspot.

2. Owner-graph report generation remains the clearest CPU hotspot.

   `owner_graph_report` accounts for 47.75% children in the core CPU samples,
   with `build_owner_graph_report` at 15.65%. This keeps the earlier direction:
   separate the graph data needed for ordinary `debundle run` from expensive
   peelability/factorization report details where possible, or cache/reuse the
   realizability state used while producing those report sections.

3. Retained heap is mostly parser/AST state, not the graph report itself.

   Peak useful heap was about 533 MiB. The large Massif stacks are SWC parser
   allocation paths and many below-threshold parser allocations. Reprofile
   after CPU/report changes before doing lifetime work; if RSS remains high,
   investigate dropping raw source and parsed AST state earlier or streaming
   later output/report generation.

4. Future profile runs should use source-built profile targets.

   The consumer BUILD file should call Ducktape's
   `debundle_pipeline_with_profiles` so `:debundle_profile_time`,
   `:debundle_profile_perf`, `:debundle_profile_massif_heap`, and
   `:debundle_profile_heaptrack` use the exact Bazel action command without
   hand-built replay scripts. The heaptrack profile command must include
   `--record-only` to avoid opening `heaptrack_gui`.

## Raw Data Boundary

The raw profile bundle remains in the private consumer repository because it
contains product-specific paths, module names, snapshot identifiers, and
absolute filesystem paths. This public note keeps only generic scale, timings,
symbols, and optimization conclusions.
