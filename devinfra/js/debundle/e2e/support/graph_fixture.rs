//! Real JS/spec inputs for graph-backed query and edit workflows.

use super::*;

pub struct GraphFixture {
    run: TreeRun,
    pub modules: PathBuf,
    pub graph: PathBuf,
}

impl GraphFixture {
    /// Module paths are relative to this fixture's single `main` chunk tree.
    pub fn new(source: &str, modules: &[(&str, &str)]) -> Self {
        let files: Vec<_> = modules.iter().map(|(path, yaml)| (format!("main/{path}"), *yaml)).collect();
        let files: Vec<_> = files.iter().map(|(path, yaml)| (path.as_str(), *yaml)).collect();
        let run = run_tree_fixture(&TreeFixture {
            chunks: &[("main", source)],
            module_roots: &[("main", "main")],
            modules: if files.is_empty() { &[("main/empty.yaml", "members: []\n")] } else { &files },
        }, &[]);
        assert!(run.result.status.success(), "{}", run.result.stderr);
        let modules_root = run._root.path().join("modules/main");
        if files.is_empty() { fs::remove_file(modules_root.join("empty.yaml")).unwrap(); }
        Self { graph: run.report_root.join("main/owner_graph.json"), modules: modules_root, run }
    }

    pub fn command(&self, args: &[&str]) -> std::process::Output {
        Command::new(debundler_path()).args(args)
            .arg("--modules").arg(&self.modules).arg("--graph").arg(&self.graph)
            .env("DEBUNDLE_SOURCE_ROOT", self.run._root.path().join("snapshot"))
            .output().expect("run graph-backed command")
    }

    pub fn json(&self, args: &[&str]) -> Value {
        let mut args = args.to_vec();
        args.extend(["--format", "json"]);
        let out = self.command(&args);
        assert!(out.status.success(), "{args:?}: {}", String::from_utf8_lossy(&out.stderr));
        parse_stdout_json(&out)
    }

    /// Re-run the edited spec, then execute its emitted entry under Node.
    pub fn assert_runs(&self, expected: &str) {
        let root = self.run._root.path();
        let out = Command::new(debundler_path()).arg("run")
            .arg("--tree-config").arg(root.join("spec_config.yaml"))
            .arg("--tree-modules").arg(root.join("modules"))
            .arg("--tree-vendor-marks").arg(root.join("vendor_marks.yaml"))
            .arg("--tree-source-root").arg(root)
            .arg("--out-root").arg(&self.run.out_root).output().unwrap();
        assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
        write_text_file(&self.run.out_root.join("app/package.json"), "{\"type\":\"module\"}\n");
        assert_node_output(&self.run.out_root.join("app/main/entry.js"), expected, "");
    }

    pub fn owner_graph(&self) -> OwnerGraphReport { read_json(&self.graph) }
}
