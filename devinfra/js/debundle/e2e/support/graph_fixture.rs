//! Real JS/spec inputs for graph-backed query and edit workflows.

use super::*;
use std::collections::BTreeMap;

pub struct GraphFixture {
    run: TreeRun,
    pub modules: PathBuf,
    pub graph: PathBuf,
}

impl GraphFixture {
    /// Module paths are relative to this fixture's single `main` chunk tree.
    pub fn new(source: &str, modules: &[(&str, &str)]) -> Self {
        let files: Vec<_> = modules
            .iter()
            .map(|(path, yaml)| (format!("main/{path}"), *yaml))
            .collect();
        let files: Vec<_> = files
            .iter()
            .map(|(path, yaml)| (path.as_str(), *yaml))
            .collect();
        let run = run_tree_fixture(
            &TreeFixture {
                chunks: &[("main", source)],
                module_roots: &[("main", "main")],
                modules: if files.is_empty() {
                    &[("main/empty.yaml", "members: []\n")]
                } else {
                    &files
                },
            },
            &[],
        );
        assert!(run.result.status.success(), "{}", run.result.stderr);
        let modules_root = run._root.path().join("modules/main");
        if files.is_empty() {
            fs::remove_file(modules_root.join("empty.yaml")).unwrap();
        }
        Self {
            graph: run.report_root.join("main/owner_graph.json"),
            modules: modules_root,
            run,
        }
    }

    /// A real rebind forces these two declarations into one atomic unit.
    pub fn atomic_pair() -> Self {
        Self::new(
            "let alpha = 0;\nfunction beta() { alpha = 1; }\nconsole.log(alpha, typeof beta);\n",
            &[(
                "home/atom.yaml",
                "members: [{selector: {binding: {name: alpha}}}, {selector: {binding: {name: beta}}}]\n",
            )],
        )
    }

    pub fn acyclic_pair() -> Self {
        Self::new(
            "const beta = 1;\nconst alpha = beta + 1;\nconsole.log(alpha);\n",
            &[
                (
                    "a.yaml",
                    "members: [{selector: {binding: {name: alpha}}}]\n",
                ),
                ("b.yaml", "members: [{selector: {binding: {name: beta}}}]\n"),
            ],
        )
    }

    pub fn assert_success(&self, args: &[&str]) {
        let out = self.command(args);
        assert!(
            out.status.success(),
            "{args:?}: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    }

    /// Both edit modes must refuse for the intended reason, without changing
    /// any spec bytes or creating/deleting files (including nested modules).
    pub fn assert_rejected_unchanged(&self, args: &[&str], diagnostics: &[&str]) {
        fn snapshot(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
            let mut files = BTreeMap::new();
            for entry in fs::read_dir(root).unwrap() {
                let path = entry.unwrap().path();
                if path.is_dir() {
                    files.extend(snapshot(&path));
                } else {
                    files.insert(path.clone(), fs::read(path).unwrap());
                }
            }
            files
        }
        let before = snapshot(&self.modules);
        let mut codes = Vec::new();
        for dry_run in [true, false] {
            let mut args = args.to_vec();
            if dry_run {
                args.push("--dry-run");
            }
            let out = self.command(&args);
            let stderr = String::from_utf8_lossy(&out.stderr);
            assert!(!out.status.success(), "{args:?}: expected rejection");
            for diagnostic in diagnostics {
                assert!(stderr.contains(diagnostic), "{args:?}: {stderr}");
            }
            assert_eq!(
                snapshot(&self.modules),
                before,
                "{args:?}: spec changed after refusal"
            );
            codes.push(out.status.code());
        }
        assert_eq!(codes[0], codes[1], "dry-run and apply must agree");
    }

    pub fn command(&self, args: &[&str]) -> std::process::Output {
        Command::new(debundler_path())
            .args(args)
            .arg("--modules")
            .arg(&self.modules)
            .arg("--graph")
            .arg(&self.graph)
            .env(
                "DEBUNDLE_SOURCE_ROOT",
                self.run._root.path().join("snapshot"),
            )
            .output()
            .expect("run graph-backed command")
    }

    pub fn json(&self, args: &[&str]) -> Value {
        let mut args = args.to_vec();
        args.extend(["--format", "json"]);
        let out = self.command(&args);
        assert!(
            out.status.success(),
            "{args:?}: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        parse_stdout_json(&out)
    }

    /// Re-run the edited spec, then execute its emitted entry under Node.
    pub fn assert_runs(&self, expected: &str) {
        let root = self.run._root.path();
        let out = Command::new(debundler_path())
            .arg("run")
            .arg("--tree-config")
            .arg(root.join("spec_config.yaml"))
            .arg("--tree-modules")
            .arg(root.join("modules"))
            .arg("--tree-vendor-marks")
            .arg(root.join("vendor_marks.yaml"))
            .arg("--tree-source-root")
            .arg(root)
            .arg("--out-root")
            .arg(&self.run.out_root)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        write_text_file(
            &self.run.out_root.join("app/package.json"),
            "{\"type\":\"module\"}\n",
        );
        assert_node_output(&self.run.out_root.join("app/main/main.js"), expected, "");
    }

    pub fn owner_graph(&self) -> OwnerGraphReport {
        read_json(&self.graph)
    }
}
