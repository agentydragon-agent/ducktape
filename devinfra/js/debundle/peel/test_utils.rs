use analysis::{BindingReport, ModuleReportRef};

pub fn member(binding: &str, export_name: &str) -> BindingReport {
    BindingReport {
        binding: binding.into(),
        export_name: export_name.into(),
    }
}

pub fn binding(name: &str) -> BindingReport {
    member(name, name)
}

pub fn module_ref(id: &str, residual: bool) -> ModuleReportRef {
    ModuleReportRef {
        id: id.to_string(),
        label: id.to_string(),
        residual,
        index: None,
        target_file: (!residual).then(|| id.to_string()),
    }
}
