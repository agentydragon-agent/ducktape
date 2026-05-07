use anyhow::{Result, bail};
use swc_common::sync::Lrc;
use swc_common::{BytePos, FileName, SourceMap};
use swc_ecma_ast::{Module, Str};
use swc_ecma_codegen::text_writer::JsWriter;
use swc_ecma_codegen::{Config, Emitter};
use swc_ecma_parser::{Parser, StringInput, Syntax, TsSyntax, lexer::Lexer};

#[derive(Clone)]
pub struct ParsedJsModule {
    pub cm: Lrc<SourceMap>,
    pub module: Module,
}

impl ParsedJsModule {
    pub fn line_index(&self) -> SourceLineIndex {
        SourceLineIndex::for_source_map(&self.cm)
    }
}

#[derive(Clone, Debug)]
pub struct SourceLineIndex {
    files: Vec<FileLineIndex>,
}

#[derive(Clone, Debug)]
struct FileLineIndex {
    start_pos: BytePos,
    line_starts: Vec<BytePos>,
}

impl SourceLineIndex {
    pub fn for_source_map(cm: &SourceMap) -> Self {
        let files = cm
            .files()
            .iter()
            .map(|file| FileLineIndex {
                start_pos: file.start_pos,
                line_starts: file.analyze().lines.clone(),
            })
            .collect();
        Self { files }
    }

    pub fn line_for_span(&self, span: swc_common::Span) -> Option<usize> {
        if span.is_dummy() {
            return None;
        }
        self.line_for_pos(span.lo())
    }

    pub fn line_range_for_span(&self, span: swc_common::Span) -> Option<(usize, usize)> {
        if span.is_dummy() {
            return None;
        }
        Some((self.line_for_pos(span.lo())?, self.line_for_pos(span.hi())?))
    }

    fn line_for_pos(&self, pos: BytePos) -> Option<usize> {
        if pos.is_dummy() {
            return None;
        }
        let file = self.file_for_pos(pos)?;
        Some(file.line_for_pos(pos))
    }

    fn file_for_pos(&self, pos: BytePos) -> Option<&FileLineIndex> {
        let index = self.files.partition_point(|file| file.start_pos <= pos);
        if index == 0 {
            None
        } else {
            self.files.get(index - 1)
        }
    }
}

impl FileLineIndex {
    fn line_for_pos(&self, pos: BytePos) -> usize {
        match self.line_starts.binary_search(&pos) {
            Ok(line_index) => line_index + 1,
            Err(0) => 0,
            Err(insert_index) => insert_index,
        }
    }
}

pub fn parse_js_module(source_name: &str, source: &str) -> Result<ParsedJsModule> {
    let cm: Lrc<SourceMap> = Default::default();
    let fm = source_file(&cm, source_name, source);
    let module = parse_module_from_source_file(source_name, &fm)?;
    Ok(ParsedJsModule { cm, module })
}

pub fn parse_js_module_ast(source_name: &str, source: &str) -> Result<Module> {
    let cm: Lrc<SourceMap> = Default::default();
    let fm = source_file(&cm, source_name, source);
    parse_module_from_source_file(source_name, &fm)
}

pub fn parsed_js_module_with_source_map(
    source_name: &str,
    source: &str,
    module: Module,
) -> ParsedJsModule {
    let cm: Lrc<SourceMap> = Default::default();
    let _fm = source_file(&cm, source_name, source);
    ParsedJsModule { cm, module }
}

fn source_file(
    cm: &Lrc<SourceMap>,
    source_name: &str,
    source: &str,
) -> Lrc<swc_common::SourceFile> {
    cm.new_source_file(
        FileName::Custom(source_name.to_string()).into(),
        source.to_string(),
    )
}

fn parse_module_from_source_file(source_name: &str, fm: &swc_common::SourceFile) -> Result<Module> {
    let lexer = Lexer::new(
        default_syntax(),
        Default::default(),
        StringInput::from(fm),
        None,
    );
    let mut parser = Parser::new_from(lexer);
    let module = parser
        .parse_module()
        .map_err(|error| anyhow::anyhow!("failed to parse {source_name}: {:?}", error.kind()))?;
    let recovered = parser.take_errors();
    if !recovered.is_empty() {
        bail!(
            "failed to parse {source_name}: {} recoverable parser error(s)",
            recovered.len()
        );
    }
    Ok(module)
}

pub fn emit_js_module(parsed: &ParsedJsModule, header_lines: &[String]) -> Result<String> {
    let mut buf = Vec::new();
    {
        let mut emitter = Emitter {
            cfg: Config::default(),
            cm: parsed.cm.clone(),
            comments: None,
            wr: JsWriter::new(parsed.cm.clone(), "\n", &mut buf, None),
        };
        emitter.emit_module(&parsed.module)?;
    }
    let code = String::from_utf8(buf)?;
    let mut out = String::new();
    for line in header_lines {
        out.push_str(line);
        out.push('\n');
    }
    out.push('\n');
    out.push_str(&code);
    out.push('\n');
    Ok(out)
}

pub fn line_for_span(parsed: &ParsedJsModule, span: swc_common::Span) -> Option<usize> {
    parsed.line_index().line_for_span(span)
}

pub fn line_range_for_span(
    parsed: &ParsedJsModule,
    span: swc_common::Span,
) -> Option<(usize, usize)> {
    parsed.line_index().line_range_for_span(span)
}

pub fn str_value(value: &Str) -> String {
    value.value.to_string_lossy().to_string()
}

pub fn set_str_value(value: &mut Str, next: String) {
    value.value = next.into();
    value.raw = None;
}

fn default_syntax() -> Syntax {
    Syntax::Typescript(TsSyntax {
        tsx: true,
        decorators: true,
        no_early_errors: true,
        ..Default::default()
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use swc_common::{DUMMY_SP, Spanned};

    #[test]
    fn source_line_index_matches_source_map_line_numbers() {
        let parsed = parse_js_module(
            "test.js",
            "import a from 'a';\n\nconst b =\n  a;\nexport { b };\n",
        )
        .unwrap();
        let line_index = parsed.line_index();

        for item in &parsed.module.body {
            let span = item.span();
            assert_eq!(
                line_index.line_for_span(span),
                Some(parsed.cm.lookup_char_pos(span.lo()).line)
            );
            assert_eq!(
                line_index.line_range_for_span(span),
                Some((
                    parsed.cm.lookup_char_pos(span.lo()).line,
                    parsed.cm.lookup_char_pos(span.hi()).line,
                ))
            );
        }
    }

    #[test]
    fn source_line_index_ignores_dummy_spans() {
        let parsed = parse_js_module("test.js", "const a = 1;\n").unwrap();
        let line_index = parsed.line_index();

        assert_eq!(line_for_span(&parsed, DUMMY_SP), None);
        assert_eq!(line_range_for_span(&parsed, DUMMY_SP), None);
        assert_eq!(line_index.line_for_span(DUMMY_SP), None);
        assert_eq!(line_index.line_range_for_span(DUMMY_SP), None);
    }
}
