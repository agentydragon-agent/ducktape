use super::*;

pub fn source_match_declared_binding_names(
    request_id: &str,
    source_match: &SourceMatch,
) -> Result<Vec<String>> {
    declared_binding_names_for_source_match(
        request_id,
        "binding_groups[].source_match",
        source_match,
    )
}

fn declared_binding_names_for_source_match(
    request_id: &str,
    selector_label: &'static str,
    source_match: &SourceMatch,
) -> Result<Vec<String>> {
    Ok(parsed_source_match(request_id, selector_label, source_match)?.declared_binding_names())
}

fn parsed_source_match(
    request_id: &str,
    selector_label: &'static str,
    source_match: &SourceMatch,
) -> Result<ParsedSourceMatchSelector> {
    ParsedSourceMatchSelector::parse(
        request_id,
        selector_label,
        format!("<binding group source_match in {request_id}>"),
        &source_match.selector(),
        selector_label,
    )
}

pub fn source_match_claim_member_selectors(
    request_id: &str,
    claim: &SourceMatchClaim,
) -> Result<Vec<BindingGroupMemberSelector>> {
    if claim.bindings.is_empty() {
        bail!("logical_module {request_id}: source_matches[] must include non-empty `bindings`");
    }

    let source_match = claim.source_match();
    let parsed = parsed_source_match(request_id, "source_matches[]", &source_match)?;
    let declared = parsed.declared_binding_names();
    let mut declared_set = BTreeSet::new();
    let mut duplicate_declared = BTreeSet::new();
    for name in declared {
        if !declared_set.insert(name.clone()) {
            duplicate_declared.insert(name);
        }
    }
    if !duplicate_declared.is_empty() {
        bail!(
            "logical_module {request_id}: source_matches[] declares duplicate \
             selector-local binding names: {}",
            duplicate_declared
                .into_iter()
                .collect::<Vec<_>>()
                .join(", ")
        );
    }

    let mut seen_locals = BTreeSet::new();
    let mut seen_names = BTreeSet::new();
    let mut out = Vec::new();
    for binding in &claim.bindings {
        let local = binding.local();
        if !seen_locals.insert(local.to_string()) {
            bail!("logical_module {request_id}: source_matches[].bindings repeats `{local}`");
        }
        let name = binding.name();
        if !seen_names.insert(name.to_string()) {
            bail!(
                "logical_module {request_id}: source_matches[].bindings repeats readable name \
                 `{name}`"
            );
        }
        if !declared_set.contains(local) {
            bail!(
                "logical_module {request_id}: source_matches[].bindings entry `{local}` is \
                 not declared by source_matches[].match"
            );
        }
        let parsed_selector = parsed.with_target_binding(Some(local.to_string()));
        let selector = parsed_selector.selector().clone();
        out.push(BindingGroupMemberSelector {
            export_name: name.to_string(),
            selector,
            parsed_selector,
            comment: None,
            note: None,
        });
    }
    Ok(out)
}

pub fn binding_group_member_selectors(
    request_id: &str,
    group: &BindingGroup,
) -> Result<Vec<BindingGroupMemberSelector>> {
    if group.source_match.target_binding.is_some() {
        bail!(
            "logical_module {request_id}: binding_groups[].source_match must not include \
             `target_binding`; use the `exports` keys to choose selector-local bindings"
        );
    }
    let parsed = parsed_source_match(
        request_id,
        "binding_groups[].source_match",
        &group.source_match,
    )?;
    let exports = effective_binding_group_exports(group, request_id, &parsed)?;
    let unknown_comments = group
        .comments
        .keys()
        .filter(|name| !exports.contains_key(*name))
        .cloned()
        .collect::<Vec<_>>();
    if !unknown_comments.is_empty() {
        bail!(
            "logical_module {request_id}: binding_groups[].comments names bindings that \
             are not exported by the group: {}",
            unknown_comments.join(", ")
        );
    }
    let unknown_notes = group
        .notes
        .keys()
        .filter(|name| !exports.contains_key(*name))
        .cloned()
        .collect::<Vec<_>>();
    if !unknown_notes.is_empty() {
        bail!(
            "logical_module {request_id}: binding_groups[].notes names bindings that \
             are not exported by the group: {}",
            unknown_notes.join(", ")
        );
    }
    Ok(exports
        .into_iter()
        .map(|(target_binding, export_name)| {
            let comment = group.comments.get(&target_binding).cloned();
            let note = group.notes.get(&target_binding).cloned();
            let parsed_selector = parsed.with_target_binding(Some(target_binding));
            let selector = parsed_selector.selector().clone();
            BindingGroupMemberSelector {
                export_name,
                selector,
                parsed_selector,
                comment,
                note,
            }
        })
        .collect())
}

pub(crate) fn effective_binding_group_exports(
    group: &BindingGroup,
    request_id: &str,
    parsed: &ParsedSourceMatchSelector,
) -> Result<BTreeMap<String, String>> {
    let mut exports = match &group.adopt_names {
        BindingGroupAdoptNames::None | BindingGroupAdoptNames::All(false) => BTreeMap::new(),
        BindingGroupAdoptNames::All(true) => {
            let names = declared_selector_binding_names(group, request_id, parsed)?;
            names
                .into_iter()
                .map(|name| (name.clone(), name))
                .collect::<BTreeMap<_, _>>()
        }
        BindingGroupAdoptNames::Names(names) => {
            let declared = declared_selector_binding_names(group, request_id, parsed)?;
            let declared_set = declared.into_iter().collect::<BTreeSet<_>>();
            let mut adopted = BTreeMap::new();
            for name in names {
                if !declared_set.contains(name) {
                    bail!(
                        "logical_module {request_id}: binding_groups[].adopt_names entry \
                         `{name}` is not declared by source_match.match"
                    );
                }
                if adopted.insert(name.clone(), name.clone()).is_some() {
                    bail!(
                        "logical_module {request_id}: binding_groups[].adopt_names repeats \
                         `{name}`"
                    );
                }
            }
            adopted
        }
    };
    exports.extend(group.exports.clone());
    if exports.is_empty() {
        bail!(
            "logical_module {request_id}: binding_groups[] must include non-empty `exports` \
             or `adopt_names`"
        );
    }
    Ok(exports)
}

pub(crate) fn declared_selector_binding_names(
    _group: &BindingGroup,
    request_id: &str,
    parsed: &ParsedSourceMatchSelector,
) -> Result<Vec<String>> {
    let names = parsed.declared_binding_names();
    let mut seen = BTreeSet::new();
    let mut duplicates = BTreeSet::new();
    for name in &names {
        if !seen.insert(name.clone()) {
            duplicates.insert(name.clone());
        }
    }
    if !duplicates.is_empty() {
        bail!(
            "logical_module {request_id}: binding_groups[].source_match declares duplicate \
             selector-local binding names: {}",
            duplicates.into_iter().collect::<Vec<_>>().join(", ")
        );
    }
    if names.is_empty() {
        bail!(
            "logical_module {request_id}: binding_groups[].adopt_names found no declared \
             bindings in source_match.match"
        );
    }
    Ok(names)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_match_claim_rejects_duplicate_readable_names() {
        let claim = SourceMatchClaim {
            identifiers: SourceMatchIdentifierMode::AlphaAll,
            match_source: "const left = 1, right = 2;".to_string(),
            bindings: vec![
                spec::SourceMatchBinding::Detailed(spec::SourceMatchBindingDetail {
                    local: "left".to_string(),
                    name: Some("Duplicate".to_string()),
                }),
                spec::SourceMatchBinding::Detailed(spec::SourceMatchBindingDetail {
                    local: "right".to_string(),
                    name: Some("Duplicate".to_string()),
                }),
            ],
            note: None,
        };
        let result =
            js_ast::with_swc_globals(|| source_match_claim_member_selectors("test/module", &claim));
        let Err(error) = result else {
            panic!("duplicate readable names should be rejected");
        };
        let message = format!("{error:#}");
        assert!(
            message.contains("repeats readable name `Duplicate`"),
            "unexpected error: {message}"
        );
    }
}
