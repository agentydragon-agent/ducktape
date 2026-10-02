//! Raw ECMAScript parsing for structural analysis tests.
//!
//! Unlike `js_ast::parse_js_module`, this uses default ES syntax, does not
//! resolve bindings, and leaves all identifier contexts empty. Recoverable
//! parser diagnostics are intentionally not rejected here: these unit tests
//! also exercise syntax admission independently of production parse admission.
//! Tests of production parsing must use `js_ast` instead.

use swc_common::{FileName, SourceMap, sync::Lrc};
use swc_ecma_ast::Module;
use swc_ecma_parser::{Parser, StringInput, Syntax, lexer::Lexer};

pub fn parse_with_source_map(source: &str) -> (Module, Lrc<SourceMap>) {
    let cm: Lrc<SourceMap> = Default::default();
    let fm = cm.new_source_file(
        FileName::Custom("test.js".into()).into(),
        source.to_string(),
    );
    let lexer = Lexer::new(
        Syntax::Es(Default::default()),
        Default::default(),
        StringInput::from(&*fm),
        None,
    );
    (Parser::new_from(lexer).parse_module().unwrap(), cm)
}

pub fn parse(source: &str) -> Module {
    parse_with_source_map(source).0
}
