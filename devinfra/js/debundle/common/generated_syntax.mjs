import { parse } from "@babel/parser";
import traverseModule from "@babel/traverse";
import { topLevelDeclarationNames } from "./program_analysis.mjs";
import { DEFAULT_PARSER_OPTIONS } from "./parser_options.mjs";

const traverse = traverseModule.default ?? traverseModule;

export const DEFAULT_GENERATED_JS_GLOBALS = Object.freeze(
  new Set([
    "AbortController",
    "AbortSignal",
    "Array",
    "ArrayBuffer",
    "AsyncDisposableStack",
    "Atomics",
    "BigInt",
    "BigInt64Array",
    "BigUint64Array",
    "Blob",
    "Boolean",
    "BroadcastChannel",
    "CSS",
    "CustomEvent",
    "DOMParser",
    "DataView",
    "Date",
    "DisposableStack",
    "Error",
    "EvalError",
    "Event",
    "EventTarget",
    "Float32Array",
    "Float64Array",
    "FormData",
    "Function",
    "Headers",
    "Infinity",
    "Int16Array",
    "Int32Array",
    "Int8Array",
    "Intl",
    "JSON",
    "Map",
    "Math",
    "NaN",
    "Number",
    "Object",
    "Promise",
    "Proxy",
    "RangeError",
    "ReadableStream",
    "ReferenceError",
    "Reflect",
    "RegExp",
    "Request",
    "Response",
    "Set",
    "SharedArrayBuffer",
    "String",
    "SuppressedError",
    "Symbol",
    "SyntaxError",
    "TextDecoder",
    "TextEncoder",
    "TypeError",
    "URIError",
    "URL",
    "URLSearchParams",
    "Uint16Array",
    "Uint32Array",
    "Uint8Array",
    "Uint8ClampedArray",
    "WeakMap",
    "WeakRef",
    "WeakSet",
    "WebAssembly",
    "Worker",
    "arguments",
    "atob",
    "btoa",
    "clearInterval",
    "clearTimeout",
    "console",
    "crypto",
    "document",
    "fetch",
    "globalThis",
    "history",
    "indexedDB",
    "isFinite",
    "isNaN",
    "location",
    "localStorage",
    "navigator",
    "parseFloat",
    "parseInt",
    "performance",
    "queueMicrotask",
    "self",
    "sessionStorage",
    "setInterval",
    "setTimeout",
    "structuredClone",
    "undefined",
    "window",
  ])
);

export function createGeneratedJsSyntaxValidator({
  allowlistedGlobals = DEFAULT_GENERATED_JS_GLOBALS,
  checkResolution = true,
  stageName = "generated JS syntax validation",
} = {}) {
  const checkedPaths = new Set();
  const files = [];
  const resolutionFiles = [];

  return {
    checkFile({
      path,
      code,
      checkResolution: fileCheckResolution = checkResolution,
      context = undefined,
      parserOptions = DEFAULT_PARSER_OPTIONS,
    }) {
      validateCheckInput(path, code);
      if (checkedPaths.has(path)) {
        return false;
      }
      checkedPaths.add(path);
      const ast = parseGeneratedJsSyntax({
        code,
        parserOptions,
        path,
        stageName,
      });
      if (fileCheckResolution) {
        validateGeneratedJsResolutionAst({
          allowlistedGlobals,
          ast,
          context,
          path,
          stageName,
        });
      }
      files.push(path);
      if (fileCheckResolution) {
        resolutionFiles.push(path);
      }
      return true;
    },

    manifest() {
      return {
        kind: "js.generated_js_syntax_validation_manifest",
        checks: resolutionFiles.length > 0 ? ["syntax", "resolution"] : ["syntax"],
        counts: {
          files: files.length,
          resolutionFiles: resolutionFiles.length,
        },
        files: [...files],
        resolutionFiles: [...resolutionFiles],
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
  parseGeneratedJsSyntax({
    code,
    parserOptions,
    path,
    stageName,
  });
}

export function validateGeneratedJsResolution({
  allowlistedGlobals = DEFAULT_GENERATED_JS_GLOBALS,
  code,
  context = undefined,
  parserOptions = DEFAULT_PARSER_OPTIONS,
  path,
  stageName = "generated JS resolution validation",
}) {
  validateCheckInput(path, code);
  const ast = parseGeneratedJsSyntax({
    code,
    parserOptions,
    path,
    stageName,
  });
  validateGeneratedJsResolutionAst({
    allowlistedGlobals,
    ast,
    context,
    path,
    stageName,
  });
}

function parseGeneratedJsSyntax({ code, parserOptions = DEFAULT_PARSER_OPTIONS, path, stageName }) {
  try {
    return parse(code, {
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

function validateGeneratedJsResolutionAst({
  allowlistedGlobals = DEFAULT_GENERATED_JS_GLOBALS,
  ast,
  context = undefined,
  path,
  stageName,
}) {
  const facts = collectModuleResolutionFacts(ast, allowlistedGlobals);

  const checkName = (name, node, reason = "reference") => {
    if (!name || facts.allowedGlobals.has(name)) {
      return;
    }
    const location = node?.loc?.start ?? null;
    throw new ReferenceError(
      `${stageName} emitted unresolved identifier: ${formatSyntaxLocation(path, { loc: location })}: ` +
        `${name} is not declared, imported, or allowlisted (${reason})${formatResolutionContext(context)}`
    );
  };

  traverse(ast, {
    ReferencedIdentifier(identifierPath) {
      const name = identifierPath.node.name;
      if (hasResolvedBinding(identifierPath.scope, name, facts)) {
        return;
      }
      checkName(name, identifierPath.node);
    },

    AssignmentExpression(expressionPath) {
      for (const identifier of assignmentTargetIdentifiers(expressionPath.node.left)) {
        if (hasResolvedBinding(expressionPath.scope, identifier.name, facts)) {
          continue;
        }
        checkName(identifier.name, identifier, "assignment target");
      }
    },

    ExportNamedDeclaration(exportPath) {
      if (exportPath.node.source) {
        return;
      }
      for (const specifier of exportPath.node.specifiers) {
        const local = specifier.local;
        if (local?.type !== "Identifier") {
          continue;
        }
        if (hasResolvedBinding(exportPath.scope, local.name, facts)) {
          continue;
        }
        checkName(local.name, local, "export specifier");
      }
    },

    ForInStatement(statementPath) {
      checkLoopAssignmentTarget(statementPath, checkName, facts);
    },

    ForOfStatement(statementPath) {
      checkLoopAssignmentTarget(statementPath, checkName, facts);
    },

    UpdateExpression(expressionPath) {
      for (const identifier of assignmentTargetIdentifiers(expressionPath.node.argument)) {
        if (hasResolvedBinding(expressionPath.scope, identifier.name, facts)) {
          continue;
        }
        checkName(identifier.name, identifier, "update target");
      }
    },
  });
}

function collectModuleResolutionFacts(ast, allowlistedGlobals) {
  return {
    allowedGlobals: new Set(allowlistedGlobals ?? []),
    importBindings: new Set(
      ast.program.body.flatMap((node) =>
        node.type === "ImportDeclaration" ? node.specifiers.map((specifier) => specifier.local.name) : []
      )
    ),
    topLevelDeclarations: new Set(ast.program.body.flatMap((node) => moduleTopLevelDeclarationNames(node))),
  };
}

function moduleTopLevelDeclarationNames(node) {
  if (node.type === "ExportNamedDeclaration" && node.declaration) {
    return topLevelDeclarationNames(node.declaration);
  }
  if (node.type === "ExportDefaultDeclaration" && node.declaration?.id?.name) {
    return [node.declaration.id.name];
  }
  return topLevelDeclarationNames(node);
}

function checkLoopAssignmentTarget(statementPath, checkName, facts) {
  if (statementPath.node.left?.type === "VariableDeclaration") {
    return;
  }
  for (const identifier of assignmentTargetIdentifiers(statementPath.node.left)) {
    if (hasResolvedBinding(statementPath.scope, identifier.name, facts)) {
      continue;
    }
    checkName(identifier.name, identifier, "loop assignment target");
  }
}

function hasResolvedBinding(scope, name, facts) {
  return (
    Boolean(scope.getBinding(name)) ||
    facts.importBindings.has(name) ||
    facts.topLevelDeclarations.has(name)
  );
}

function assignmentTargetIdentifiers(node) {
  if (!node) {
    return [];
  }
  if (node.type === "Identifier") {
    return [node];
  }
  if (node.type === "ArrayPattern") {
    return node.elements.flatMap((element) => assignmentTargetIdentifiers(element));
  }
  if (node.type === "AssignmentPattern") {
    return assignmentTargetIdentifiers(node.left);
  }
  if (node.type === "ObjectPattern") {
    return node.properties.flatMap((property) => {
      if (property.type === "RestElement") {
        return assignmentTargetIdentifiers(property.argument);
      }
      return assignmentTargetIdentifiers(property.value);
    });
  }
  if (node.type === "RestElement") {
    return assignmentTargetIdentifiers(node.argument);
  }
  if (
    node.type === "ParenthesizedExpression" ||
    node.type === "TSAsExpression" ||
    node.type === "TSNonNullExpression" ||
    node.type === "TSTypeAssertion"
  ) {
    return assignmentTargetIdentifiers(node.expression);
  }
  return [];
}

function validateCheckInput(path, code) {
  if (typeof path !== "string" || path === "") {
    throw new Error(`Generated JS validation requires a non-empty path, got: ${path}`);
  }
  if (typeof code !== "string") {
    throw new Error(`Generated JS validation requires string code for ${path}`);
  }
}

function formatSyntaxLocation(path, error) {
  if (error?.loc && Number.isInteger(error.loc.line) && Number.isInteger(error.loc.column)) {
    return `${path}:${error.loc.line}:${error.loc.column + 1}`;
  }
  return path;
}

function formatResolutionContext(context) {
  if (!context || typeof context !== "object") {
    return "";
  }
  const parts = [];
  if (context.chunkId) {
    parts.push(`chunk=${context.chunkId}`);
  }
  if (context.chunkFile) {
    parts.push(`chunkFile=${context.chunkFile}`);
  }
  if (context.role) {
    parts.push(`role=${context.role}`);
  }
  const moduleExtraction = context.moduleExtraction;
  if (moduleExtraction && typeof moduleExtraction === "object") {
    if (moduleExtraction.id) {
      parts.push(`module=${moduleExtraction.id}`);
    }
    if (moduleExtraction.nameHint) {
      parts.push(`nameHint=${moduleExtraction.nameHint}`);
    }
    if (Array.isArray(moduleExtraction.ownerIds) && moduleExtraction.ownerIds.length > 0) {
      parts.push(`owners=${moduleExtraction.ownerIds.join(",")}`);
    }
  }
  return parts.length > 0 ? ` [${parts.join("; ")}]` : "";
}
