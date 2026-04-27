import { deriveSelectedModuleTarget } from "./planner.mjs";

export function getLogicalModuleOperations(operations) {
  return normalizeLogicalModuleOperations(
    operations.filter(
      (operation) =>
        operation?.operation === "define_logical_module" || operation?.operation === "define_residual_module"
    )
  );
}

export function expandLogicalModuleRenameOperations(operations) {
  const renameOperations = [];
  for (const operation of getLogicalModuleOperations(operations)) {
    if (operation.operation !== "define_logical_module") {
      continue;
    }
    for (const member of operation.members) {
      const originalName = member.selector.binding.name;
      const targetName = member.target?.name ?? null;
      if (!targetName || targetName === originalName) {
        continue;
      }
      renameOperations.push({
        id: member.id,
        operation: "rename_binding",
        selector: {
          chunkId: operation.selector.chunkId,
          ...(operation.selector.file ? { file: operation.selector.file } : {}),
          ...member.selector,
          ...(member.selector.file ? { file: member.selector.file } : {}),
        },
        ...(member.selector.fingerprint ? { fingerprint: member.selector.fingerprint } : {}),
        target: {
          name: targetName,
        },
      });
    }
  }
  return renameOperations;
}

export function buildLogicalModulePlans(currentModules, operations, { chunkId, targetDir }) {
  const logicalOperations = getLogicalModuleOperations(operations).filter(
    (operation) => operation.selector.chunkId === normalizeRelativeFile(chunkId)
  );
  if (logicalOperations.length === 0) {
    return {
      counts: {
        explicitModules: 0,
        residualModules: 0,
        totalModules: currentModules.length,
        unmatchedMembers: 0,
      },
      modules: currentModules.map(cloneModulePlan),
      reports: [],
    };
  }

  const atomicModules = [...currentModules].sort(
    (left, right) => left.startOrdinal - right.startOrdinal || left.id.localeCompare(right.id)
  );
  const modulesBySymbol = buildModulesBySymbol(atomicModules);
  const claimedModuleIds = new Map();
  const explicitModulePlans = [];
  const reports = [];
  let residualOperation = null;
  let unmatchedMembers = 0;

  for (const operation of groupLogicalModuleOperations(logicalOperations)) {
    if (operation.operation === "define_residual_module") {
      if (residualOperation) {
        throw new Error(`define_residual_module operations overlap on chunk ${chunkId}`);
      }
      residualOperation = operation;
      continue;
    }
    const selectedModules = [];
    const selectedModuleIdSet = new Set();
    const requestedMembers = [];
    for (const member of operation.members) {
      const resolvedName = member.target?.name ?? member.selector.binding.name;
      const importMember = isImportKind(member.selector.binding.kind ?? null);
      requestedMembers.push({
        anchor: !importMember,
        id: member.id,
        matched: true,
        name: resolvedName,
        renamed: Boolean(member.target?.name && member.target.name !== member.selector.binding.name),
      });
      if (importMember) {
        continue;
      }
      const matches = modulesBySymbol.get(resolvedName) ?? [];
      if (matches.length === 0) {
        requestedMembers[requestedMembers.length - 1].matched = false;
        unmatchedMembers += 1;
        continue;
      }
      if (matches.length > 1) {
        throw new Error(
          `define_logical_module ${operation.id} member ${member.id} matched multiple atomic modules for ${resolvedName}: ${matches
            .map((modulePlan) => modulePlan.id)
            .join(", ")}`
        );
      }
      const modulePlan = matches[0];
      if (!selectedModuleIdSet.has(modulePlan.id)) {
        selectedModuleIdSet.add(modulePlan.id);
        selectedModules.push(modulePlan);
      }
    }
    if (selectedModules.length === 0) {
      reports.push({
        basename: operation.target.basename,
        emittedMemberNames: [],
        id: operation.id,
        materialized: false,
        matchedAtomicModuleIds: [],
        matchedAtomicModules: [],
        operationIds: [...operation.operationIds],
        renamedMemberCount: requestedMembers.filter((member) => member.renamed).length,
        requestedMembers,
        residual: false,
      });
      continue;
    }
    selectedModules.sort((left, right) => left.startOrdinal - right.startOrdinal || left.id.localeCompare(right.id));
    for (const modulePlan of selectedModules) {
      const priorOwner = claimedModuleIds.get(modulePlan.id);
      if (priorOwner) {
        throw new Error(
          `define_logical_module operations overlap on atomic module ${modulePlan.id}: ${priorOwner} and ${operation.id}`
        );
      }
      claimedModuleIds.set(modulePlan.id, operation.id);
    }
    const mergedPlan = mergeModuleGroup(selectedModules, operation, explicitModulePlans.length, { targetDir });
    explicitModulePlans.push(mergedPlan);
    reports.push({
      basename: mergedPlan.basename,
      emittedMemberNames: [...mergedPlan.memberNames],
      id: operation.id,
      materialized: true,
      matchedAtomicModuleIds: selectedModules.map((modulePlan) => modulePlan.id),
      matchedAtomicModules: selectedModules.map((modulePlan) => ({
        id: modulePlan.id,
        memberNames: [...modulePlan.memberNames],
        startOrdinal: modulePlan.startOrdinal,
      })),
      operationIds: [...operation.operationIds],
      renamedMemberCount: requestedMembers.filter((member) => member.renamed).length,
      requestedMembers,
      residual: false,
    });
  }

  const residualModules = atomicModules.filter((modulePlan) => !claimedModuleIds.has(modulePlan.id));
  const finalPlans = [...explicitModulePlans];
  if (residualOperation && residualModules.length > 0) {
    const residualPlan = mergeModuleGroup(residualModules, residualOperation, finalPlans.length, { targetDir });
    finalPlans.push(residualPlan);
    reports.push({
      basename: residualPlan.basename,
      emittedMemberNames: [...residualPlan.memberNames],
      id: residualOperation.id,
      matchedAtomicModuleIds: residualModules.map((modulePlan) => modulePlan.id),
      matchedAtomicModules: residualModules.map((modulePlan) => ({
        id: modulePlan.id,
        memberNames: [...modulePlan.memberNames],
        startOrdinal: modulePlan.startOrdinal,
      })),
      renamedMemberCount: 0,
      requestedMembers: [],
      residual: true,
    });
  } else {
    for (const modulePlan of residualModules) {
      finalPlans.push(cloneModulePlan(modulePlan));
    }
  }

  finalPlans.sort((left, right) => left.startOrdinal - right.startOrdinal || left.id.localeCompare(right.id));
  return {
    counts: {
      explicitModules: explicitModulePlans.length,
      residualModules: residualOperation ? (residualModules.length > 0 ? 1 : 0) : residualModules.length,
      totalModules: finalPlans.length,
      unmatchedMembers,
    },
    modules: finalPlans,
    reports,
  };
}

export function logicalSelectedOwnerIdsForChunk(operations, { analysis = null, chunkId }) {
  const ownerIds = new Set();
  for (const operation of getLogicalModuleOperations(operations)) {
    if (operation.operation !== "define_logical_module") {
      continue;
    }
    if (operation.selector.chunkId !== normalizeRelativeFile(chunkId)) {
      continue;
    }
    for (const member of operation.members) {
      let ownerId = member.selector.owner?.id ?? null;
      if (!ownerId && analysis && !isImportKind(member.selector.binding.kind ?? null)) {
        ownerId = resolveOwnerIdFromAnalysis(analysis, member);
      }
      if (typeof ownerId === "string" && ownerId !== "") {
        ownerIds.add(ownerId);
      }
    }
  }
  return ownerIds.size > 0 ? ownerIds : null;
}

function normalizeLogicalModuleOperations(operations) {
  return operations.map((operation) => {
    if (typeof operation?.id !== "string" || operation.id === "") {
      throw new Error(`${operation?.operation ?? "logical module operation"} requires id`);
    }
    if (typeof operation?.selector?.chunkId !== "string" || operation.selector.chunkId === "") {
      throw new Error(`${operation.operation} ${operation.id} requires selector.chunkId`);
    }
    const selector = {
      chunkId: normalizeRelativeFile(operation.selector.chunkId),
      ...(operation.selector.file ? { file: normalizeRelativeFile(operation.selector.file) } : {}),
    };
    if (operation.operation === "define_residual_module") {
      return {
        ...operation,
        selector,
        target: normalizeLogicalTarget(operation.target, operation.id),
      };
    }
    if (!Array.isArray(operation.members) || operation.members.length === 0) {
      throw new Error(`define_logical_module ${operation.id} requires non-empty members`);
    }
    return {
      ...operation,
      members: operation.members.map((member, index) => normalizeLogicalMember(member, operation, index)),
      selector,
      target: normalizeLogicalTarget(operation.target, operation.id),
    };
  });
}

function normalizeLogicalTarget(target, operationId) {
  if (!target || typeof target !== "object") {
    throw new Error(`logical module ${operationId} requires target`);
  }
  if (typeof target.basename !== "string" || target.basename === "") {
    throw new Error(`logical module ${operationId} requires target.basename`);
  }
  return {
    ...target,
    basename: sanitizeIdentifier(target.basename),
    ...(target.file ? { file: normalizeRelativeFile(target.file) } : {}),
  };
}

function normalizeLogicalMember(member, operation, index) {
  if (!member || typeof member !== "object") {
    throw new Error(`define_logical_module ${operation.id} member[${index}] must be an object`);
  }
  if (typeof member.id !== "string" || member.id === "") {
    throw new Error(`define_logical_module ${operation.id} member[${index}] requires id`);
  }
  if (!member.selector || typeof member.selector !== "object") {
    throw new Error(`define_logical_module ${operation.id} member ${member.id} requires selector`);
  }
  if (!member.selector.binding || typeof member.selector.binding?.name !== "string" || member.selector.binding.name === "") {
    throw new Error(`define_logical_module ${operation.id} member ${member.id} requires selector.binding.name`);
  }
  return {
    ...member,
    selector: {
      ...member.selector,
      binding: {
        ...member.selector.binding,
      },
      ...(member.selector.file ? { file: normalizeRelativeFile(member.selector.file) } : {}),
    },
    ...(member.target ? { target: { ...member.target } } : {}),
  };
}

function buildModulesBySymbol(modulePlans) {
  const modulesBySymbol = new Map();
  for (const modulePlan of modulePlans) {
    for (const symbol of modulePlan.memberNames) {
      if (!modulesBySymbol.has(symbol)) {
        modulesBySymbol.set(symbol, []);
      }
      modulesBySymbol.get(symbol).push(modulePlan);
    }
  }
  return modulesBySymbol;
}

function groupLogicalModuleOperations(logicalOperations) {
  const residualOperations = logicalOperations.filter((operation) => operation.operation === "define_residual_module");
  const grouped = new Map();
  for (const operation of logicalOperations) {
    if (operation.operation !== "define_logical_module") {
      continue;
    }
    const key = JSON.stringify({
      basename: operation.target.basename,
      file: operation.target.file ?? null,
      init: operation.target.init ?? null,
    });
    if (!grouped.has(key)) {
      grouped.set(key, {
        id: `logical_module__${operation.target.basename}`,
        members: [],
        operation: "define_logical_module",
        operationIds: [],
        selector: { ...operation.selector },
        target: { ...operation.target },
      });
    }
    const group = grouped.get(key);
    group.members.push(...operation.members);
    group.operationIds.push(operation.id);
  }
  return [...grouped.values(), ...residualOperations.map((operation) => ({ ...operation, operationIds: [operation.id] }))];
}

function mergeModuleGroup(selectedModules, operation, index, { targetDir }) {
  const targetBasename = operation.target.basename;
  const attachedItemIds = [];
  const attachedItemIdSet = new Set();
  const memberNames = [];
  const memberNameSet = new Set();
  const ownerIds = [];
  const ownerIdSet = new Set();
  const unitIds = [];
  const unitIdSet = new Set();
  let bytes = 0;
  let hasNullBytes = false;
  let lines = 0;
  let startOrdinal = Number.POSITIVE_INFINITY;
  for (const modulePlan of selectedModules) {
    lines += modulePlan.lines;
    if (modulePlan.bytes === null) {
      hasNullBytes = true;
    } else if (!hasNullBytes) {
      bytes += modulePlan.bytes;
    }
    if (modulePlan.startOrdinal < startOrdinal) {
      startOrdinal = modulePlan.startOrdinal;
    }
    for (const itemId of modulePlan.attachedItemIds) {
      if (!attachedItemIdSet.has(itemId)) {
        attachedItemIdSet.add(itemId);
        attachedItemIds.push(itemId);
      }
    }
    for (const memberName of modulePlan.memberNames) {
      if (!memberNameSet.has(memberName)) {
        memberNameSet.add(memberName);
        memberNames.push(memberName);
      }
    }
    for (const ownerId of modulePlan.ownerIds) {
      if (!ownerIdSet.has(ownerId)) {
        ownerIdSet.add(ownerId);
        ownerIds.push(ownerId);
      }
    }
    for (const unitId of modulePlan.unitIds) {
      if (!unitIdSet.has(unitId)) {
        unitIdSet.add(unitId);
        unitIds.push(unitId);
      }
    }
  }
  const baseModule = {
    attachedItemIds: attachedItemIds.sort(),
    basename: targetBasename,
    bytes: hasNullBytes ? null : bytes,
    id: operation.id,
    index,
    lines,
    memberNames: memberNames.sort(),
    nameHint: targetBasename,
    ownerIds,
    startOrdinal,
    unitIds,
  };
  const derivedTarget = deriveSelectedModuleTarget(baseModule, index, { targetDir });
  return {
    ...baseModule,
    initName:
      typeof operation.target?.init === "string" && operation.target.init !== ""
        ? operation.target.init
        : derivedTarget.init,
    targetFile:
      typeof operation.target?.file === "string" && operation.target.file !== ""
        ? normalizeRelativeFile(operation.target.file)
        : derivedTarget.file,
  };
}

function cloneModulePlan(modulePlan) {
  return {
    attachedItemIds: [...modulePlan.attachedItemIds],
    basename: modulePlan.basename,
    ...(modulePlan.bytes === null ? { bytes: null } : { bytes: modulePlan.bytes }),
    id: modulePlan.id,
    index: modulePlan.index,
    ...(modulePlan.initName ? { initName: modulePlan.initName } : {}),
    lines: modulePlan.lines,
    memberNames: [...modulePlan.memberNames],
    nameHint: modulePlan.nameHint,
    ownerIds: [...modulePlan.ownerIds],
    startOrdinal: modulePlan.startOrdinal,
    ...(modulePlan.targetFile ? { targetFile: modulePlan.targetFile } : {}),
    unitIds: [...modulePlan.unitIds],
  };
}

function normalizeRelativeFile(value) {
  if (typeof value !== "string" || value === "") {
    throw new Error(`Expected a non-empty relative path, got: ${value}`);
  }
  const normalized = value.replace(/^\.\/+/, "").replace(/\\/g, "/");
  if (normalized === "." || normalized.startsWith("/") || normalized.split("/").includes("..")) {
    throw new Error(`Invalid relative path: ${value}`);
  }
  return normalized;
}

function sanitizeIdentifier(value) {
  return value
    .replace(/[^A-Za-z0-9_$]+/g, "_")
    .replace(/^[^A-Za-z_$]+/, "_")
    .replace(/_+/g, "_");
}

function resolveOwnerIdFromAnalysis(analysis, member) {
  const resolvedName = member.target?.name ?? member.selector.binding.name;
  const expectedType = manifestDeclarationKind(member.selector.binding.kind ?? null);
  const matches = analysis.owners.filter((owner) => {
    if (!owner.names?.includes(resolvedName)) {
      return false;
    }
    if (expectedType && owner.type !== expectedType) {
      return false;
    }
    return true;
  });
  if (matches.length === 0) {
    return null;
  }
  if (matches.length > 1) {
    throw new Error(
      `logical member ${member.id} matched multiple analysis owners for ${resolvedName}: ${matches
        .map((owner) => owner.id)
        .join(", ")}`
    );
  }
  return matches[0].id;
}

function manifestDeclarationKind(kind) {
  return kind === "VariableDeclarator" ? "VariableDeclaration" : kind;
}

function isImportKind(kind) {
  return kind === "ImportSpecifier" || kind === "ImportDefaultSpecifier" || kind === "ImportNamespaceSpecifier";
}
