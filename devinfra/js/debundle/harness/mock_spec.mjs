export function createMockBrowserBundleTransformSpec({
  appRoot,
  assetSummaryPath,
  jsListPath,
  snapshotRoot,
  transformedRoot,
}) {
  return {
    kind: "js.ast_transform_spec",
    pipeline: [
      {
        id: "load_mock_bundle",
        operation: "load_js_chunks",
        args: {
          inputRoot: snapshotRoot,
          jsListPath,
        },
      },
      {
        id: "parse_mock_bundle",
        operation: "compute_js_asts",
      },
      {
        id: "split_mock_bundle",
        operation: "normalize_js_chunks",
        args: {
          jobs: 1,
        },
      },
      {
        id: "rewrite_mock_bundle_chunk_links",
        operation: "rewrite_chunk_entry_specifiers",
      },
      {
        id: "write_mock_bundle",
        operation: "write_js_tree",
        args: {
          force: true,
          outDir: transformedRoot,
        },
      },
      {
        id: "emit_mock_harness",
        operation: "emit_browser_harness",
        args: {
          assetSummaryPath,
          force: true,
          outDir: appRoot,
          scriptSource: "split",
          snapshotRoot,
        },
      },
    ],
  };
}
