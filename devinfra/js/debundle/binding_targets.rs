use swc_ecma_ast::*;

pub trait TargetAccessRecorder {
    /// Called for update expressions like `a++`, where the target binding is
    /// both read and written. Validators that only care about writes can leave
    /// the default no-op in place.
    fn record_binding_read(&mut self, _name: &str) {}
    fn record_binding_write(&mut self, name: &str);
    /// Called for mutations through a binding, e.g. `obj.x = 1`.
    /// This is not a rebinding write to `obj`; validator collectors can ignore
    /// it when they only need to reject assignments to imported binding cells.
    fn record_member_write(&mut self, _name: &str) {}
}

pub fn binding_names(pattern: &Pat) -> impl Iterator<Item = String> + '_ {
    enum Work<'a> {
        Pat(&'a Pat),
        BindIdent(&'a BindingIdent),
    }
    let mut stack = vec![Work::Pat(pattern)];
    std::iter::from_fn(move || {
        loop {
            match stack.pop()? {
                Work::BindIdent(id) => return Some(id.id.sym.to_string()),
                Work::Pat(pat) => match pat {
                    Pat::Ident(id) => return Some(id.id.sym.to_string()),
                    Pat::Array(arr) => {
                        for elem in arr.elems.iter().flatten().rev() {
                            stack.push(Work::Pat(elem));
                        }
                    }
                    Pat::Object(obj) => {
                        for prop in obj.props.iter().rev() {
                            match prop {
                                ObjectPatProp::KeyValue(kv) => stack.push(Work::Pat(&kv.value)),
                                ObjectPatProp::Assign(a) => stack.push(Work::BindIdent(&a.key)),
                                ObjectPatProp::Rest(rest) => stack.push(Work::Pat(&rest.arg)),
                            }
                        }
                    }
                    Pat::Rest(rest) => stack.push(Work::Pat(&rest.arg)),
                    Pat::Assign(assign) => stack.push(Work::Pat(&assign.left)),
                    _ => {}
                },
            }
        }
    })
}

pub fn record_assign_target(target: &AssignTarget, recorder: &mut impl TargetAccessRecorder) {
    match target {
        AssignTarget::Simple(simple) => record_simple_assign_target(simple, recorder),
        AssignTarget::Pat(pattern) => record_assign_target_pat(pattern, recorder),
    }
}

fn record_simple_assign_target(
    target: &SimpleAssignTarget,
    recorder: &mut impl TargetAccessRecorder,
) {
    match target {
        SimpleAssignTarget::Ident(ident) => {
            recorder.record_binding_write(ident.id.sym.as_ref());
        }
        SimpleAssignTarget::Member(member) => {
            record_member_target(member, recorder);
        }
        SimpleAssignTarget::Paren(paren) => {
            record_assign_expr_target(&paren.expr, recorder);
        }
        SimpleAssignTarget::OptChain(opt_chain) => {
            if let Some(name) = opt_chain_base_name(opt_chain) {
                recorder.record_member_write(name);
            }
        }
        _ => {}
    }
}

fn record_assign_expr_target(target: &Expr, recorder: &mut impl TargetAccessRecorder) {
    match target {
        Expr::Ident(ident) => recorder.record_binding_write(ident.sym.as_ref()),
        Expr::Member(member) => record_member_target(member, recorder),
        Expr::Paren(paren) => record_assign_expr_target(&paren.expr, recorder),
        Expr::OptChain(opt_chain) => {
            if let Some(name) = opt_chain_base_name(opt_chain) {
                recorder.record_member_write(name);
            }
        }
        _ => {}
    }
}

fn record_assign_target_pat(target: &AssignTargetPat, recorder: &mut impl TargetAccessRecorder) {
    match target {
        AssignTargetPat::Array(array) => {
            for element in array.elems.iter().flatten() {
                record_pat_write(element, recorder);
            }
        }
        AssignTargetPat::Object(object) => {
            for prop in &object.props {
                match prop {
                    ObjectPatProp::KeyValue(key_value) => {
                        record_pat_write(&key_value.value, recorder);
                    }
                    ObjectPatProp::Assign(assign) => {
                        recorder.record_binding_write(assign.key.id.sym.as_ref());
                    }
                    ObjectPatProp::Rest(rest) => record_pat_write(&rest.arg, recorder),
                }
            }
        }
        AssignTargetPat::Invalid(_) => {}
    }
}

pub fn record_pat_write(pattern: &Pat, recorder: &mut impl TargetAccessRecorder) {
    for name in binding_names(pattern) {
        recorder.record_binding_write(&name);
    }
}

pub fn record_member_target(member: &MemberExpr, recorder: &mut impl TargetAccessRecorder) {
    if let Some(name) = member_root_ident(&member.obj) {
        recorder.record_member_write(name);
    }
}

pub fn record_update_target(target: &Expr, recorder: &mut impl TargetAccessRecorder) {
    match target {
        Expr::Ident(ident) => {
            recorder.record_binding_read(ident.sym.as_ref());
            recorder.record_binding_write(ident.sym.as_ref());
        }
        Expr::Member(member) => {
            if let Some(name) = member_root_ident(&member.obj) {
                recorder.record_binding_read(name);
                recorder.record_member_write(name);
            }
        }
        Expr::Paren(paren) => record_update_target(&paren.expr, recorder),
        Expr::OptChain(opt_chain) => {
            if let Some(name) = opt_chain_base_name(opt_chain) {
                recorder.record_binding_read(name);
                recorder.record_member_write(name);
            }
        }
        _ => {}
    }
}

pub fn member_root_ident(expr: &Expr) -> Option<&str> {
    match expr {
        Expr::Ident(ident) => Some(ident.sym.as_ref()),
        Expr::Member(member) => member_root_ident(&member.obj),
        Expr::OptChain(opt_chain) => match &*opt_chain.base {
            OptChainBase::Member(member) => member_root_ident(&member.obj),
            OptChainBase::Call(call) => member_root_ident(&call.callee),
        },
        Expr::Paren(paren) => member_root_ident(&paren.expr),
        _ => None,
    }
}

fn opt_chain_base_name(opt_chain: &OptChainExpr) -> Option<&str> {
    match &*opt_chain.base {
        OptChainBase::Member(member) => member_root_ident(&member.obj),
        OptChainBase::Call(call) => member_root_ident(&call.callee),
    }
}
