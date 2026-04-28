import * as t from "@babel/types";
import { referencedUndeclaredNames } from "../common/program_analysis.mjs";
import { packSelectedModuleGroups, planSelectedModuleGroupExtractions } from "./decl_graph.mjs";

const SELECTED_ATOMIC_UNIT_ID_PREFIX = "selected_atomic_unit_";
const ATOMIC_MODULE_ID_PREFIX = "atomic_module_";
const GENERATED_INIT_PREFIX = "__dt_generated_init__";
const ANALYSIS_OWNER_BY_ID_CACHE = new WeakMap();
const ANALYSIS_ITEM_BY_ID_CACHE = new WeakMap();
const ANALYSIS_DEFAULT_SELECTED_OWNER_IDS_CACHE = new WeakMap();

export function planSelectedAtomicModules(
  { analysis, code, itemMetricsById = null, programBody = null },
  { selectedOwnerIds: explicitSelectedOwnerIds = null } = {}
) {
  if (!analysis?.owners || !analysis?.programItems) {
    throw new Error("planSelectedAtomicModules requires analysis");
  }
  if (!Array.isArray(programBody) && !(itemMetricsById instanceof Map)) {
    throw new Error("planSelectedAtomicModules requires programBody or itemMetricsById");
  }

  const startedAt = process.hrtime.bigint();
  const ownerById = getOwnerByIdForAnalysis(analysis);
  const selectionStartedAt = process.hrtime.bigint();
  const selectedOwnerIds = explicitSelectedOwnerIds
    ? requireKnownOwnerIds(explicitSelectedOwnerIds, ownerById, "planSelectedAtomicModules explicit selectedOwnerIds")
    : selectedOwnerIdsFromDefaultClosureSelection(analysis, ownerById, "planSelectedAtomicModules");
  const selectionMs = durationMsSince(selectionStartedAt);
  const itemById = getItemByIdForAnalysis(analysis);
  const buildUnitsStartedAt = process.hrtime.bigint();
  const rawAtomicUnits = buildSelectedAtomicUnits({
    analysis,
    ownerById,
    selectedOwnerIds,
  });
  const expandedAtomicUnits = splitPureVariableDeclarationAtomicUnits(rawAtomicUnits, {
    ownerById,
    programBody,
  });
  const buildUnitsMs = durationMsSince(buildUnitsStartedAt);
  const finalizeUnitsStartedAt = process.hrtime.bigint();
  const atomicUnits = expandedAtomicUnits.map((unit, index) =>
    finalizeAtomicUnit(unit, {
      code,
      id: `${SELECTED_ATOMIC_UNIT_ID_PREFIX}${index.toString().padStart(4, "0")}`,
      index,
      itemMetricsById,
      itemById,
      ownerById,
      programBody,
    })
  );
  const finalizeUnitsMs = durationMsSince(finalizeUnitsStartedAt);

  const finalizeModulesStartedAt = process.hrtime.bigint();
  const modulePlans = atomicUnits.map((atomicUnit, index) =>
    finalizeModulePlan(newModuleFromAtomicUnit(atomicUnit), {
      id: `${ATOMIC_MODULE_ID_PREFIX}${index.toString().padStart(4, "0")}`,
      index,
      ownerById,
    })
  );
  const finalizeModulesMs = durationMsSince(finalizeModulesStartedAt);

  return {
    kind: "js.atomic_module_plan",
    atomicUnitCount: atomicUnits.length,
    atomicUnits,
    modulePlans,
    selectedOwnerCount: selectedOwnerIds.size,
    timingsMs: {
      buildAtomicUnits: buildUnitsMs,
      finalizeAtomicUnits: finalizeUnitsMs,
      finalizeModules: finalizeModulesMs,
      selectOwners: selectionMs,
      total: durationMsSince(startedAt),
    },
  };
}

export function buildSelectedModuleOperations(plan, options = {}) {
  const chunkId = options.chunkId ?? "<chunk>";
  const file = options.file ? normalizeRelativeFile(options.file) : null;
  const targetDir = normalizeRelativeFile(options.targetDir ?? "regions");
  const idPrefix = options.idPrefix ?? "selected_module";
  const filePrefix = options.filePrefix ?? "";
  const initPrefix = options.initPrefix ?? GENERATED_INIT_PREFIX;

  return plan.modulePlans.map((modulePlan, index) => {
    const target = deriveSelectedModuleTarget(modulePlan, index, { filePrefix, initPrefix, targetDir });
    return {
      id: `${idPrefix}__${modulePlan.id}`,
      ...(Array.isArray(modulePlan.atomicBoundaryUnits)
        ? {
            atomicBoundaryUnits: modulePlan.atomicBoundaryUnits.map((unit) => ({
              attachedItemIds: [...unit.attachedItemIds],
              id: unit.id,
              memberNames: [...unit.memberNames],
              ownerIds: [...unit.ownerIds],
              ownerFragments: cloneOwnerFragments(unit.ownerFragments),
              startOrdinal: unit.startOrdinal,
              unitIds: [...unit.unitIds],
            })),
          }
        : {}),
      ...(Array.isArray(modulePlan.bindingPlacements)
        ? {
            bindingPlacements: modulePlan.bindingPlacements.map((entry) => ({ ...entry })),
          }
        : {}),
      graphGenerated: true,
      lowering: "staged_shell",
      operation: "lower_selected_module_region",
      selector: {
        attachedItemIds: [...modulePlan.attachedItemIds],
        chunkId,
        ownerIds: [...modulePlan.ownerIds],
        ...(Array.isArray(modulePlan.ownerFragments)
          ? {
              ownerFragments: cloneOwnerFragments(modulePlan.ownerFragments),
            }
          : {}),
        ...(file ? { file } : {}),
      },
      target: {
        file: target.file,
        init: target.init,
      },
    };
  });
}

export function deriveSelectedModuleTarget(
  modulePlan,
  index,
  { filePrefix = "", initPrefix = GENERATED_INIT_PREFIX, targetDir = "modules" } = {}
) {
  const normalizedTargetDir = normalizeRelativeFile(targetDir);
  const modulePath =
    modulePlan.modulePath ??
    `${modulePlan.id}__${modulePlan.nameHint ?? `module_${index}`}`;
  return {
    file: modulePlan.targetFile ?? `${normalizedTargetDir}/${filePrefix}${modulePath}.js`,
    init: modulePlan.initName ?? sanitizeIdentifier(`${initPrefix}${modulePath}`),
  };
}

function selectedOwnerIdsFromDefaultClosureSelection(analysis, ownerById, callerName) {
  const cachedSelectedOwnerIds = ANALYSIS_DEFAULT_SELECTED_OWNER_IDS_CACHE.get(analysis);
  if (cachedSelectedOwnerIds) {
    return cachedSelectedOwnerIds;
  }
  const plan = planSelectedModuleGroupExtractions(analysis);
  const packed = packSelectedModuleGroups(plan, { lowering: "staged_shell" });
  const selectedOwnerIds = requireKnownOwnerIds(
    packed.batchPlans.flatMap((batchPlan) => batchPlan.ownerIds),
    ownerById,
    `${callerName} default closure selection`
  );
  ANALYSIS_DEFAULT_SELECTED_OWNER_IDS_CACHE.set(analysis, selectedOwnerIds);
  return selectedOwnerIds;
}

function getOwnerByIdForAnalysis(analysis) {
  const cached = ANALYSIS_OWNER_BY_ID_CACHE.get(analysis);
  if (cached) {
    return cached;
  }
  const ownerById = new Map();
  for (const owner of analysis.owners) {
    ownerById.set(owner.id, owner);
  }
  ANALYSIS_OWNER_BY_ID_CACHE.set(analysis, ownerById);
  return ownerById;
}

function getItemByIdForAnalysis(analysis) {
  const cached = ANALYSIS_ITEM_BY_ID_CACHE.get(analysis);
  if (cached) {
    return cached;
  }
  const itemById = new Map();
  for (const item of analysis.programItems) {
    itemById.set(item.id, item);
  }
  ANALYSIS_ITEM_BY_ID_CACHE.set(analysis, itemById);
  return itemById;
}

function requireKnownOwnerIds(ownerIds, ownerById, source) {
  // `analysis.owners` is the authoritative owner universe for a boundary-analysis
  // snapshot. Selected-owner sets must be subsets of that universe. If we ever see
  // an unknown id here, that indicates either a bad caller-supplied selector set or
  // an internal planner inconsistency, and we want to fail at the boundary instead
  // of silently dropping it and masking the source of the corruption.
  const normalizedOwnerIds = new Set(ownerIds);
  const unknownOwnerIds = [...normalizedOwnerIds].filter((ownerId) => !ownerById.has(ownerId));
  if (unknownOwnerIds.length > 0) {
    const sample = unknownOwnerIds.slice(0, 8).join(", ");
    const remainder = unknownOwnerIds.length > 8 ? ` (+${unknownOwnerIds.length - 8} more)` : "";
    throw new Error(`${source} referenced unknown owner ids outside analysis.owners: ${sample}${remainder}`);
  }
  return normalizedOwnerIds;
}

function buildSelectedAtomicUnits({ analysis, ownerById, selectedOwnerIds }) {
  requireKnownOwnerIds(selectedOwnerIds, ownerById, "buildSelectedAtomicUnits selectedOwnerIds");
  const mustLinkAdjacency = new Map([...selectedOwnerIds].map((ownerId) => [ownerId, new Set()]));
  const replayableSideEffects = [];
  const linkOwners = (leftOwnerId, rightOwnerId) => {
    if (leftOwnerId === rightOwnerId) {
      return;
    }
    mustLinkAdjacency.get(leftOwnerId)?.add(rightOwnerId);
    mustLinkAdjacency.get(rightOwnerId)?.add(leftOwnerId);
  };

  const selectedOwners = [...selectedOwnerIds]
    .map((ownerId) => ownerById.get(ownerId))
    .sort((left, right) => left.ordinal - right.ordinal);

  for (const owner of selectedOwners) {
    forEachTopLevelAccess(owner, (access, bucket, phase) => {
      if (access.kind !== "local_declaration" || !access.ownerId || !selectedOwnerIds.has(access.ownerId)) {
        return true;
      }
      if (bucket === "reads") {
        if (phase !== "eager") {
          return true;
        }
        if (access.ownerId === owner.id) {
          return true;
        }
        const targetOwner = ownerById.get(access.ownerId);
        if (targetOwner && targetOwner.ordinal > owner.ordinal) {
          linkOwners(owner.id, targetOwner.id);
        }
        return true;
      }
      linkOwners(owner.id, access.ownerId);
      return true;
    });
  }

  for (const sideEffect of analysis.sideEffects) {
    if (!isReplayableAttachedSideEffectNode(sideEffect)) {
      continue;
    }
    const touchedOwnerIds = touchedSelectedOwnerIds(sideEffect, selectedOwnerIds);
    if (!touchedOwnerIds) {
      continue;
    }
    replayableSideEffects.push({ touchedOwnerIds, sideEffectId: sideEffect.id });
    if (touchedOwnerIds.length < 2) {
      continue;
    }
    for (let index = 1; index < touchedOwnerIds.length; index++) {
      linkOwners(touchedOwnerIds[0], touchedOwnerIds[index]);
    }
  }

  const visited = new Set();
  const units = [];
  for (const owner of selectedOwners) {
    if (visited.has(owner.id)) {
      continue;
    }
    const ownerIds = [];
    const stack = [owner.id];
    visited.add(owner.id);
    while (stack.length > 0) {
      const currentOwnerId = stack.pop();
      ownerIds.push(currentOwnerId);
      for (const dependencyOwnerId of mustLinkAdjacency.get(currentOwnerId) ?? []) {
        if (visited.has(dependencyOwnerId)) {
          continue;
        }
        visited.add(dependencyOwnerId);
        stack.push(dependencyOwnerId);
      }
    }
    ownerIds.sort((left, right) => ownerById.get(left).ordinal - ownerById.get(right).ordinal);
    units.push({
      attachedItemIds: [],
      ownerIds,
    });
  }

  const unitIndexByOwnerId = new Map();
  units.forEach((unit, index) => {
    for (const ownerId of unit.ownerIds) {
      unitIndexByOwnerId.set(ownerId, index);
    }
  });

  for (const { touchedOwnerIds, sideEffectId } of replayableSideEffects) {
    if (touchedOwnerIds.length === 0) {
      continue;
    }
    const firstUnitIndex = unitIndexByOwnerId.get(touchedOwnerIds[0]);
    if (firstUnitIndex === undefined) {
      continue;
    }
    let sameUnit = true;
    for (let index = 1; index < touchedOwnerIds.length; index++) {
      if (unitIndexByOwnerId.get(touchedOwnerIds[index]) !== firstUnitIndex) {
        sameUnit = false;
        break;
      }
    }
    if (!sameUnit) {
      continue;
    }
    units[firstUnitIndex].attachedItemIds.push(sideEffectId);
  }

  return units;
}

function splitPureVariableDeclarationAtomicUnits(rawAtomicUnits, { ownerById, programBody }) {
  const expanded = [];
  for (const unit of rawAtomicUnits) {
    const splitUnits = splitPureVariableDeclarationAtomicUnit(unit, { ownerById, programBody });
    expanded.push(...(splitUnits ?? [unit]));
  }
  return expanded;
}

function splitPureVariableDeclarationAtomicUnit(unit, { ownerById, programBody }) {
  if (unit.attachedItemIds.length > 0 || unit.ownerIds.length !== 1) {
    return null;
  }
  const [ownerId] = unit.ownerIds;
  const owner = ownerById.get(ownerId);
  if (!owner || owner.type !== "VariableDeclaration" || ownerHasAnyTopLevelAccess(owner)) {
    return null;
  }
  const statement = programBody?.[owner.ordinal];
  const declaration = unwrapTopLevelDeclarationNode(statement);
  if (!t.isVariableDeclaration(declaration) || declaration.declarations.length <= 1) {
    return null;
  }
  const fragments = declaration.declarations.map((declarator, index) =>
    buildPureVariableDeclaratorFragment(owner, declarator, index)
  );
  if (fragments.some((fragment) => fragment === null)) {
    return null;
  }
  return fragments.map((fragment) => ({
    attachedItemIds: [],
    ownerFragments: [fragment],
    ownerIds: [owner.id],
  }));
}

function buildPureVariableDeclaratorFragment(owner, declarator, index) {
  if (!t.isIdentifier(declarator.id)) {
    return null;
  }
  if (!isStaticallyPureFragmentInitializer(declarator.init)) {
    return null;
  }
  if (referencedUndeclaredNames(declarator.init).length > 0) {
    return null;
  }
  return {
    declaratorIndices: [index],
    id: `${owner.id}::declarator_${index}`,
    kind: "variable_declarator",
    memberNames: [declarator.id.name],
    orderIndex: index,
    ownerId: owner.id,
  };
}

function isStaticallyPureFragmentInitializer(node) {
  if (!node) {
    return true;
  }
  if (
    t.isStringLiteral(node) ||
    t.isNumericLiteral(node) ||
    t.isBooleanLiteral(node) ||
    t.isNullLiteral(node) ||
    t.isBigIntLiteral(node) ||
    t.isRegExpLiteral(node)
  ) {
    return true;
  }
  if (t.isTemplateLiteral(node)) {
    return node.expressions.length === 0;
  }
  if (t.isArrayExpression(node)) {
    return node.elements.every((element) => {
      if (!element) {
        return true;
      }
      if (t.isSpreadElement(element)) {
        return false;
      }
      return isStaticallyPureFragmentInitializer(element);
    });
  }
  if (t.isObjectExpression(node)) {
    return node.properties.every((property) => {
      if (t.isSpreadElement(property)) {
        return false;
      }
      if (property.computed && !isStaticallyPureFragmentInitializer(property.key)) {
        return false;
      }
      return isStaticallyPureFragmentInitializer(property.value);
    });
  }
  if (t.isUnaryExpression(node)) {
    return isStaticallyPureFragmentInitializer(node.argument);
  }
  if (t.isBinaryExpression(node) || t.isLogicalExpression(node)) {
    return isStaticallyPureFragmentInitializer(node.left) && isStaticallyPureFragmentInitializer(node.right);
  }
  if (t.isConditionalExpression(node)) {
    return (
      isStaticallyPureFragmentInitializer(node.test) &&
      isStaticallyPureFragmentInitializer(node.consequent) &&
      isStaticallyPureFragmentInitializer(node.alternate)
    );
  }
  if (t.isParenthesizedExpression(node)) {
    return isStaticallyPureFragmentInitializer(node.expression);
  }
  return false;
}

function ownerHasAnyTopLevelAccess(owner) {
  let hasAccess = false;
  forEachTopLevelAccess(owner, () => {
    hasAccess = true;
    return false;
  });
  return hasAccess;
}

function touchedSelectedOwnerIds(sideEffect, selectedOwnerIds) {
  const touchedOwnerIds = [];
  const touchedOwnerIdSet = new Set();
  const seenNonSelected = forEachTopLevelAccess(sideEffect, (access) => {
    if (access.kind !== "local_declaration" || !access.ownerId) {
      return true;
    }
    if (!selectedOwnerIds.has(access.ownerId)) {
      return false;
    }
    if (!touchedOwnerIdSet.has(access.ownerId)) {
      touchedOwnerIdSet.add(access.ownerId);
      touchedOwnerIds.push(access.ownerId);
    }
    return true;
  });
  if (!seenNonSelected) {
    return null;
  }
  return touchedOwnerIds;
}

function finalizeAtomicUnit(unit, { code, id, index, itemMetricsById, itemById, ownerById, programBody }) {
  const itemIds = [...unit.ownerIds, ...unit.attachedItemIds];
  let lines = 0;
  let bytes = typeof code === "string" ? 0 : null;
  let startOrdinal = Number.POSITIVE_INFINITY;
  if (Array.isArray(unit.ownerFragments) && unit.ownerFragments.length > 0) {
    for (const fragment of unit.ownerFragments) {
      const metrics = statementMetricForOwnerFragment(fragment, { code, itemById, programBody });
      lines += metrics.lines;
      if (bytes !== null) {
        bytes += metrics.bytes;
      }
      const baseOrdinal = itemById.get(fragment.ownerId)?.ordinal ?? Number.POSITIVE_INFINITY;
      const fragmentOrdinal = baseOrdinal + fragment.orderIndex / 1000;
      if (fragmentOrdinal < startOrdinal) {
        startOrdinal = fragmentOrdinal;
      }
    }
  } else {
    for (const itemId of itemIds) {
      const metrics = statementMetricForItem(itemId, { code, itemMetricsById, itemById, programBody });
      lines += metrics.lines;
      if (bytes !== null) {
        bytes += metrics.bytes;
      }
      const ordinal = itemById.get(itemId)?.ordinal ?? Number.POSITIVE_INFINITY;
      if (ordinal < startOrdinal) {
        startOrdinal = ordinal;
      }
    }
  }
  return {
    attachedItemIds: [...unit.attachedItemIds],
    bytes,
    id,
    index,
    lines,
    memberNames:
      Array.isArray(unit.ownerFragments) && unit.ownerFragments.length > 0
        ? unit.ownerFragments.flatMap((fragment) => fragment.memberNames).sort()
        : unit.ownerIds.flatMap((ownerId) => ownerById.get(ownerId)?.names ?? []).sort(),
    ownerIds: [...unit.ownerIds],
    ownerFragments: cloneOwnerFragments(unit.ownerFragments),
    startOrdinal,
  };
}

function statementMetricForOwnerFragment(fragment, { code, itemById, programBody }) {
  const item = itemById.get(fragment.ownerId);
  const statement = unwrapTopLevelDeclarationNode(programBody?.[item?.ordinal]);
  if (!t.isVariableDeclaration(statement)) {
    return { bytes: 0, lines: 0 };
  }
  const lines = fragment.declaratorIndices.reduce((sum, declaratorIndex) => {
    const declaration = statement.declarations[declaratorIndex];
    if (!declaration?.loc) {
      return sum;
    }
    return sum + declaration.loc.end.line - declaration.loc.start.line + 1;
  }, 0);
  const bytes =
    typeof code === "string"
      ? fragment.declaratorIndices.reduce((sum, declaratorIndex) => {
          const declaration = statement.declarations[declaratorIndex];
          if (typeof declaration?.start !== "number" || typeof declaration?.end !== "number") {
            return sum;
          }
          return sum + Buffer.byteLength(code.slice(declaration.start, declaration.end));
        }, 0)
      : 0;
  return { bytes, lines };
}

function statementMetricForItem(itemId, { code, itemMetricsById, itemById, programBody }) {
  const fromIndex = itemMetricsById?.get(itemId);
  if (fromIndex) {
    return {
      bytes: fromIndex.bytes ?? 0,
      lines: fromIndex.lines ?? 0,
    };
  }
  return {
    bytes: statementByteCountForItem(itemId, { code, itemById, programBody }),
    lines: statementLineCountForItem(itemId, { itemById, programBody }),
  };
}

function newModuleFromAtomicUnit(atomicUnit) {
  return {
    attachedItemIds: [...atomicUnit.attachedItemIds],
    bytes: atomicUnit.bytes,
    lines: atomicUnit.lines,
    memberNames: [...atomicUnit.memberNames],
    ownerIds: [...atomicUnit.ownerIds],
    ownerFragments: cloneOwnerFragments(atomicUnit.ownerFragments),
    startOrdinal: atomicUnit.startOrdinal,
    unitIds: [atomicUnit.id],
  };
}

function finalizeModulePlan(modulePlan, { id, index, ownerById }) {
  const uniqueMemberNames = [...new Set(modulePlan.memberNames)].sort();
  const nameHint = moduleNameHint(uniqueMemberNames, index);
  const modulePath = normalizeRelativeFile(modulePlan.modulePath ?? sanitizeIdentifier(`${id}__${nameHint}`));
  return {
    attachedItemIds: [...new Set(modulePlan.attachedItemIds)].sort(),
    bytes: modulePlan.bytes,
    id,
    index,
    lines: modulePlan.lines,
    memberNames: uniqueMemberNames,
    modulePath,
    nameHint,
    ownerIds: [...new Set(modulePlan.ownerIds)].sort(
      (leftOwnerId, rightOwnerId) => ownerById.get(leftOwnerId).ordinal - ownerById.get(rightOwnerId).ordinal
    ),
    ownerFragments: cloneOwnerFragments(modulePlan.ownerFragments),
    startOrdinal: modulePlan.startOrdinal,
    unitIds: [...modulePlan.unitIds],
  };
}

function moduleNameHint(memberNames, index) {
  const descriptiveNames = memberNames.filter(isDescriptiveModuleName).slice(0, 3);
  const sourceNames = descriptiveNames.length > 0 ? descriptiveNames : memberNames.slice(0, 3);
  const hint = sourceNames.join("_");
  return sanitizeIdentifier(hint || `module_${index.toString().padStart(4, "0")}`);
}

function isDescriptiveModuleName(name) {
  return /[A-Z_]/.test(name) || name.length >= 5;
}

function statementLineCountForItem(itemId, { itemById, programBody }) {
  const item = itemById.get(itemId);
  const statement = programBody[item?.ordinal];
  if (!statement?.loc) {
    return 0;
  }
  return statement.loc.end.line - statement.loc.start.line + 1;
}

function statementByteCountForItem(itemId, { code, itemById, programBody }) {
  if (typeof code !== "string") {
    return 0;
  }
  const item = itemById.get(itemId);
  const statement = programBody[item?.ordinal];
  if (typeof statement?.start !== "number" || typeof statement?.end !== "number") {
    return 0;
  }
  return Buffer.byteLength(code.slice(statement.start, statement.end));
}

function selectedModuleEagerReadAccesses(record) {
  return topLevelAccesses(record, "reads", "eager");
}

function selectedModuleLazyReadAccesses(record) {
  return topLevelAccesses(record, "reads", "lazy");
}

function selectedModuleWriteAccesses(record) {
  return topLevelAccesses(record, "writes", "eager");
}

function selectedModuleLazyWriteAccesses(record) {
  return topLevelAccesses(record, "writes", "lazy");
}

function selectedModuleEagerMemberWriteAccesses(record) {
  return topLevelAccesses(record, "memberWrites", "eager");
}

function selectedModuleLazyMemberWriteAccesses(record) {
  return topLevelAccesses(record, "memberWrites", "lazy");
}

function topLevelAccesses(record, bucket, phase) {
  const finalized = record?.[`${bucket}TopLevel`]?.[phase];
  if (Array.isArray(finalized)) {
    return finalized;
  }
  const rawBucketName = `${phase}${bucket[0].toUpperCase()}${bucket.slice(1)}`;
  const rawBucket = record?.[rawBucketName];
  if (!rawBucket) {
    return [];
  }
  if (typeof rawBucket.values === "function") {
    return [...rawBucket.values()];
  }
  if (Array.isArray(rawBucket)) {
    return rawBucket;
  }
  return [];
}

function forEachTopLevelAccess(record, callback) {
  for (const access of selectedModuleEagerReadAccesses(record)) {
    if (callback(access, "reads", "eager") === false) {
      return false;
    }
  }
  for (const access of selectedModuleLazyReadAccesses(record)) {
    if (callback(access, "reads", "lazy") === false) {
      return false;
    }
  }
  for (const access of selectedModuleWriteAccesses(record)) {
    if (callback(access, "writes", "eager") === false) {
      return false;
    }
  }
  for (const access of selectedModuleLazyWriteAccesses(record)) {
    if (callback(access, "writes", "lazy") === false) {
      return false;
    }
  }
  for (const access of selectedModuleEagerMemberWriteAccesses(record)) {
    if (callback(access, "memberWrites", "eager") === false) {
      return false;
    }
  }
  for (const access of selectedModuleLazyMemberWriteAccesses(record)) {
    if (callback(access, "memberWrites", "lazy") === false) {
      return false;
    }
  }
  return true;
}

function isReplayableAttachedSideEffectNode(sideEffectNodeOrRecord) {
  const type = sideEffectNodeOrRecord?.type ?? sideEffectNodeOrRecord?.node?.type ?? null;
  if (type !== "ExpressionStatement") {
    return false;
  }
  return !(
    sideEffectNodeOrRecord?.effects?.containsDirectEval ||
    sideEffectNodeOrRecord?.effects?.containsImportMeta ||
    sideEffectNodeOrRecord?.effects?.containsTopLevelAwait
  );
}

function normalizeRelativeFile(value) {
  return value.replace(/^\.\/+/, "").replace(/\\/g, "/");
}

function sanitizeIdentifier(value) {
  return value
    .replace(/[^A-Za-z0-9_$]+/g, "_")
    .replace(/^[^A-Za-z_$]+/, "_");
}

function unwrapTopLevelDeclarationNode(node) {
  if (t.isExportNamedDeclaration(node) && node.declaration) {
    return node.declaration;
  }
  return node;
}

function cloneOwnerFragments(ownerFragments) {
  return Array.isArray(ownerFragments)
    ? ownerFragments.map((fragment) => ({
        ...fragment,
        declaratorIndices: [...fragment.declaratorIndices],
        memberNames: [...fragment.memberNames],
      }))
    : undefined;
}

function durationMsSince(startedAt) {
  return Number(process.hrtime.bigint() - startedAt) / 1_000_000;
}
