import { packOrderedInitOwnerClosures, planOrderedInitOwnerClosureExtractions } from "./declaration_component_graph_lib.mjs";

export function planGuidedSelectedOwnerModules(
  { analysis, code, itemMetricsById = null, programBody = null },
  {
    maxModuleLines = 20_000,
    minModuleLines = 500,
    selectedOwnerIds: explicitSelectedOwnerIds = null,
  } = {}
) {
  if (!analysis?.owners || !analysis?.programItems) {
    throw new Error("planGuidedSelectedOwnerModules requires analysis");
  }
  if (!Array.isArray(programBody) && !(itemMetricsById instanceof Map)) {
    throw new Error("planGuidedSelectedOwnerModules requires programBody or itemMetricsById");
  }

  const selectedOwnerIds = explicitSelectedOwnerIds
    ? new Set(explicitSelectedOwnerIds)
    : selectedOwnerIdsFromDefaultClosureSelection(analysis);
  const ownerById = new Map(analysis.owners.map((owner) => [owner.id, owner]));
  const itemById = new Map(analysis.programItems.map((item) => [item.id, item]));
  const selectedAtomicUnits = buildSelectedAtomicUnits({
    analysis,
    ownerById,
    selectedOwnerIds,
  }).map((unit, index) =>
    finalizeAtomicUnit(unit, {
      code,
      id: `guided_selected_owner_atomic_unit_${index.toString().padStart(4, "0")}`,
      index,
      itemMetricsById,
      itemById,
      ownerById,
      programBody,
    })
  );

  const modulePlans = mergeAtomicUnitsIntoModules(selectedAtomicUnits, {
    maxModuleLines,
    minModuleLines,
    ownerById,
  }).map((modulePlan, index) =>
    finalizeGuidedModulePlan(modulePlan, {
      id: `guided_selected_owner_module_${index.toString().padStart(4, "0")}`,
      index,
      ownerById,
    })
  );

  return {
    kind: "js.guided_selected_owner_module_plan",
    atomicUnitCount: selectedAtomicUnits.length,
    atomicUnits: selectedAtomicUnits,
    maxModuleLines,
    minModuleLines,
    modulePlans,
    selectedOwnerCount: selectedOwnerIds.size,
  };
}

export function buildGuidedSelectedOwnerModuleOperations(plan, options = {}) {
  const chunkId = options.chunkId ?? "<chunk>";
  const file = options.file ? normalizeRelativeFile(options.file) : null;
  const targetDir = normalizeRelativeFile(options.targetDir ?? "regions");
  const filePrefix = options.filePrefix ?? "guided_";
  const initPrefix = options.initPrefix ?? "init_guided_";

  return plan.modulePlans.map((modulePlan, index) => {
    const baseName = `${index.toString().padStart(4, "0")}_${modulePlan.nameHint}`;
    return {
      id: `${options.idPrefix ?? "guided_selected_owner_module"}__${modulePlan.id}`,
      graphGenerated: true,
      lowering: "staged_shell",
      operation: "extract_ordered_init_region",
      selector: {
        attachedItemIds: [...modulePlan.attachedItemIds],
        chunkId,
        ownerIds: [...modulePlan.ownerIds],
        ...(file ? { file } : {}),
      },
      target: {
        file: `${targetDir}/${filePrefix}${baseName}.js`,
        init: sanitizeIdentifier(`${initPrefix}${baseName}`),
      },
    };
  });
}

function selectedOwnerIdsFromDefaultClosureSelection(analysis) {
  const plan = planOrderedInitOwnerClosureExtractions(analysis);
  const packed = packOrderedInitOwnerClosures(plan, { lowering: "staged_shell" });
  return new Set(packed.batchPlans.flatMap((batchPlan) => batchPlan.ownerIds));
}

function buildSelectedAtomicUnits({ analysis, ownerById, selectedOwnerIds }) {
  const mustLinkAdjacency = new Map([...selectedOwnerIds].map((ownerId) => [ownerId, new Set()]));
  const linkOwners = (leftOwnerId, rightOwnerId) => {
    if (leftOwnerId === rightOwnerId) {
      return;
    }
    mustLinkAdjacency.get(leftOwnerId)?.add(rightOwnerId);
    mustLinkAdjacency.get(rightOwnerId)?.add(leftOwnerId);
  };

  for (const ownerId of selectedOwnerIds) {
    const owner = ownerById.get(ownerId);
    if (!owner) {
      continue;
    }
    for (const access of [
      ...orderedInitWriteAccesses(owner),
      ...orderedInitLazyWriteAccesses(owner),
      ...orderedInitEagerMemberWriteAccesses(owner),
      ...orderedInitLazyMemberWriteAccesses(owner),
    ]) {
      if (access.kind === "local_declaration" && access.ownerId && selectedOwnerIds.has(access.ownerId)) {
        linkOwners(owner.id, access.ownerId);
      }
    }
    for (const access of orderedInitEagerReadAccesses(owner)) {
      if (access.kind !== "local_declaration" || !access.ownerId || !selectedOwnerIds.has(access.ownerId)) {
        continue;
      }
      const targetOwner = ownerById.get(access.ownerId);
      if (targetOwner && targetOwner.ordinal > owner.ordinal) {
        linkOwners(owner.id, targetOwner.id);
      }
    }
  }

  for (const sideEffect of analysis.sideEffects) {
    if (!isReplayableAttachedSideEffectNode(sideEffect)) {
      continue;
    }
    if (touchesNonSelectedLocalDeclarations(sideEffect, selectedOwnerIds)) {
      continue;
    }
    const touchedOwnerIds = touchedSelectedOwnerIds(sideEffect, selectedOwnerIds);
    if (touchedOwnerIds.length < 2) {
      continue;
    }
    for (let index = 1; index < touchedOwnerIds.length; index++) {
      linkOwners(touchedOwnerIds[0], touchedOwnerIds[index]);
    }
  }

  const visited = new Set();
  const units = [];
  for (const ownerId of [...selectedOwnerIds].sort((left, right) => ownerById.get(left).ordinal - ownerById.get(right).ordinal)) {
    if (visited.has(ownerId)) {
      continue;
    }
    const ownerIds = [];
    const stack = [ownerId];
    visited.add(ownerId);
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

  units.sort((left, right) => ownerById.get(left.ownerIds[0]).ordinal - ownerById.get(right.ownerIds[0]).ordinal);
  const unitIndexByOwnerId = new Map();
  units.forEach((unit, index) => {
    for (const ownerId of unit.ownerIds) {
      unitIndexByOwnerId.set(ownerId, index);
    }
  });

  for (const sideEffect of analysis.sideEffects) {
    if (!isReplayableAttachedSideEffectNode(sideEffect)) {
      continue;
    }
    if (touchesNonSelectedLocalDeclarations(sideEffect, selectedOwnerIds)) {
      continue;
    }
    const touchedOwnerIds = touchedSelectedOwnerIds(sideEffect, selectedOwnerIds);
    if (touchedOwnerIds.length === 0) {
      continue;
    }
    const unitIndexes = new Set(touchedOwnerIds.map((ownerId) => unitIndexByOwnerId.get(ownerId)));
    if (unitIndexes.size !== 1) {
      continue;
    }
    units[[...unitIndexes][0]].attachedItemIds.push(sideEffect.id);
  }

  return units;
}

function touchedSelectedOwnerIds(sideEffect, selectedOwnerIds) {
  return [
    ...new Set(
      [
        ...orderedInitEagerReadAccesses(sideEffect),
        ...orderedInitLazyReadAccesses(sideEffect),
        ...orderedInitWriteAccesses(sideEffect),
        ...orderedInitLazyWriteAccesses(sideEffect),
        ...orderedInitEagerMemberWriteAccesses(sideEffect),
        ...orderedInitLazyMemberWriteAccesses(sideEffect),
      ]
        .filter((access) => access.kind === "local_declaration" && access.ownerId && selectedOwnerIds.has(access.ownerId))
        .map((access) => access.ownerId)
    ),
  ];
}

function touchesNonSelectedLocalDeclarations(sideEffect, selectedOwnerIds) {
  for (const access of [
    ...orderedInitEagerReadAccesses(sideEffect),
    ...orderedInitLazyReadAccesses(sideEffect),
    ...orderedInitWriteAccesses(sideEffect),
    ...orderedInitLazyWriteAccesses(sideEffect),
    ...orderedInitEagerMemberWriteAccesses(sideEffect),
    ...orderedInitLazyMemberWriteAccesses(sideEffect),
  ]) {
    if (access.kind === "local_declaration" && access.ownerId && !selectedOwnerIds.has(access.ownerId)) {
      return true;
    }
  }
  return false;
}

function finalizeAtomicUnit(unit, { code, id, index, itemMetricsById, itemById, ownerById, programBody }) {
  const itemIds = [...unit.ownerIds, ...unit.attachedItemIds];
  const lines = itemIds.reduce(
    (sum, itemId) => sum + statementMetricForItem(itemId, { code, itemMetricsById, itemById, programBody }).lines,
    0
  );
  const bytes =
    typeof code === "string"
      ? itemIds.reduce(
          (sum, itemId) =>
            sum + statementMetricForItem(itemId, { code, itemMetricsById, itemById, programBody }).bytes,
          0
        )
      : null;
  return {
    attachedItemIds: [...unit.attachedItemIds],
    bytes,
    id,
    index,
    lines,
    memberNames: unit.ownerIds.flatMap((ownerId) => ownerById.get(ownerId)?.names ?? []).sort(),
    ownerIds: [...unit.ownerIds],
    startOrdinal: Math.min(...itemIds.map((itemId) => itemById.get(itemId)?.ordinal ?? Number.MAX_SAFE_INTEGER)),
  };
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

function mergeAtomicUnitsIntoModules(atomicUnits, { maxModuleLines, minModuleLines, ownerById }) {
  const modules = [];
  let currentModule = null;

  for (const atomicUnit of atomicUnits) {
    if (!currentModule) {
      currentModule = newModuleFromAtomicUnit(atomicUnit);
      continue;
    }

    const nextLineCount = currentModule.lines + atomicUnit.lines;
    if (currentModule.lines < minModuleLines && nextLineCount <= maxModuleLines) {
      mergeAtomicUnitIntoModule(currentModule, atomicUnit);
      continue;
    }
    if (currentModule.lines < minModuleLines) {
      mergeAtomicUnitIntoModule(currentModule, atomicUnit);
      continue;
    }

    modules.push(currentModule);
    currentModule = newModuleFromAtomicUnit(atomicUnit);
  }

  if (currentModule) {
    modules.push(currentModule);
  }

  modules.sort((left, right) => ownerById.get(left.ownerIds[0]).ordinal - ownerById.get(right.ownerIds[0]).ordinal);
  return modules;
}

function newModuleFromAtomicUnit(atomicUnit) {
  return {
    attachedItemIds: [...atomicUnit.attachedItemIds],
    bytes: atomicUnit.bytes,
    lines: atomicUnit.lines,
    memberNames: [...atomicUnit.memberNames],
    ownerIds: [...atomicUnit.ownerIds],
    startOrdinal: atomicUnit.startOrdinal,
    unitIds: [atomicUnit.id],
  };
}

function mergeAtomicUnitIntoModule(modulePlan, atomicUnit) {
  modulePlan.attachedItemIds.push(...atomicUnit.attachedItemIds);
  modulePlan.bytes = modulePlan.bytes === null || atomicUnit.bytes === null ? null : modulePlan.bytes + atomicUnit.bytes;
  modulePlan.lines += atomicUnit.lines;
  modulePlan.memberNames.push(...atomicUnit.memberNames);
  modulePlan.ownerIds.push(...atomicUnit.ownerIds);
  modulePlan.unitIds.push(atomicUnit.id);
}

function finalizeGuidedModulePlan(modulePlan, { id, index, ownerById }) {
  const uniqueMemberNames = [...new Set(modulePlan.memberNames)].sort();
  return {
    attachedItemIds: [...new Set(modulePlan.attachedItemIds)].sort(),
    bytes: modulePlan.bytes,
    id,
    index,
    lines: modulePlan.lines,
    memberNames: uniqueMemberNames,
    nameHint: moduleNameHint(uniqueMemberNames, index),
    ownerIds: [...new Set(modulePlan.ownerIds)].sort(
      (leftOwnerId, rightOwnerId) => ownerById.get(leftOwnerId).ordinal - ownerById.get(rightOwnerId).ordinal
    ),
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
  const item = itemById.get(itemId);
  const statement = programBody[item?.ordinal];
  if (typeof statement?.start !== "number" || typeof statement?.end !== "number") {
    return 0;
  }
  return Buffer.byteLength(code.slice(statement.start, statement.end));
}

function orderedInitEagerReadAccesses(record) {
  return topLevelAccesses(record, "reads", "eager");
}

function orderedInitLazyReadAccesses(record) {
  return topLevelAccesses(record, "reads", "lazy");
}

function orderedInitWriteAccesses(record) {
  return topLevelAccesses(record, "writes", "eager");
}

function orderedInitLazyWriteAccesses(record) {
  return topLevelAccesses(record, "writes", "lazy");
}

function orderedInitEagerMemberWriteAccesses(record) {
  return topLevelAccesses(record, "memberWrites", "eager");
}

function orderedInitLazyMemberWriteAccesses(record) {
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
    .replace(/^[^A-Za-z_$]+/, "_")
    .replace(/_+/g, "_");
}
