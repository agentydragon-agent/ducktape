import { parse } from "@babel/parser";
import { DEFAULT_PARSER_OPTIONS } from "./parser_options.mjs";

export function createGeneratedJsSyntaxValidator({ stageName = "generated JS syntax validation" } = {}) {
  const checkedPaths = new Set();
  const files = [];

  return {
    checkFile({ path, code, parserOptions = DEFAULT_PARSER_OPTIONS }) {
      validateCheckInput(path, code);
      if (checkedPaths.has(path)) {
        return false;
      }
      checkedPaths.add(path);
      validateGeneratedJsSyntax({
        code,
        parserOptions,
        path,
        stageName,
      });
      files.push(path);
      return true;
    },

    manifest() {
      return {
        kind: "js.generated_js_syntax_validation_manifest",
        counts: {
          files: files.length,
        },
        files: [...files],
      };
    },
  };
}

export function validateGeneratedJsSyntax({
  code,
  parserOptions = DEFAULT_PARSER_OPTIONS,
  path,
  stageName = "generated JS syntax validation",
}) {
  validateCheckInput(path, code);
  try {
    parse(code, {
      ...(parserOptions && typeof parserOptions === "object" ? parserOptions : DEFAULT_PARSER_OPTIONS),
      errorRecovery: false,
      sourceFilename: path,
    });
  } catch (error) {
    const wrapped = new SyntaxError(
      `${stageName} emitted invalid JavaScript: ${formatSyntaxLocation(path, error)}: ${error.message}`
    );
    wrapped.cause = error;
    throw wrapped;
  }
}

function validateCheckInput(path, code) {
  if (typeof path !== "string" || path === "") {
    throw new Error(`Generated JS syntax validation requires a non-empty path, got: ${path}`);
  }
  if (typeof code !== "string") {
    throw new Error(`Generated JS syntax validation requires string code for ${path}`);
  }
}

function formatSyntaxLocation(path, error) {
  if (error?.loc && Number.isInteger(error.loc.line) && Number.isInteger(error.loc.column)) {
    return `${path}:${error.loc.line}:${error.loc.column + 1}`;
  }
  return path;
}
