import { deriveSelectedModuleTarget } from "./planner.mjs";

export function getLogicalModuleOperations(operations) {
  return normalizeLogicalModuleOperations(
    operations.filter(
      (operation) =>
        operation?.operation === "define_logical_module" || operation?.operation === "define_residual_module"
    )
  );
}

export function buildLogicalModulePlans(currentModules, operations, { analysis = null, chunkId, targetDir }) {
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
  const modulesByOwnerId = buildModulesByOwnerId(atomicModules);
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
    const requestedBindings = [];
    for (const member of operation.members) {
      const importMember = isImportKind(member.selector.binding.kind ?? null);
      const resolvedMember = resolveLogicalMember(member, {
        analysis,
        modulesByOwnerId,
        modulesBySymbol,
        operationId: operation.id,
      });
      const requestedBinding = {
        anchor: !importMember,
        name: member.name,
        id: member.id,
        kind: member.selector.binding.kind,
        matched: resolvedMember.matched,
        moduleId: resolvedMember.modulePlan?.id ?? null,
        sourceName: member.selector.binding.name,
        ownerId: resolvedMember.ownerId ?? null,
        changedName: member.name !== member.selector.binding.name,
      };
      requestedBindings.push(requestedBinding);
      if (importMember) {
        continue;
      }
      if (!resolvedMember.modulePlan) {
        unmatchedMembers += 1;
        continue;
      }
      const modulePlan = resolvedMember.modulePlan;
      if (!selectedModuleIdSet.has(modulePlan.id)) {
        selectedModuleIdSet.add(modulePlan.id);
        selectedModules.push(modulePlan);
      }
    }
    if (selectedModules.length === 0) {
      reports.push({
        path: operation.target.path,
        emittedMemberNames: [],
        id: operation.id,
        materialized: false,
        matchedAtomicModuleIds: [],
        matchedAtomicModules: [],
        operationIds: [...operation.operationIds],
        changedNameCount: requestedBindings.filter((binding) => binding.changedName).length,
        requestedBindings,
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
    const mergedPlan = mergeModuleGroup(selectedModules, operation, explicitModulePlans.length, {
      requestedBindings,
      targetDir,
    });
    explicitModulePlans.push(mergedPlan);
    reports.push({
      path: mergedPlan.modulePath,
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
      changedNameCount: requestedBindings.filter((binding) => binding.changedName).length,
      requestedBindings,
      residual: false,
    });
  }

  const residualModules = atomicModules.filter((modulePlan) => !claimedModuleIds.has(modulePlan.id));
  const finalPlans = [...explicitModulePlans];
  if (residualOperation && residualModules.length > 0) {
    const residualPlan = mergeModuleGroup(residualModules, residualOperation, finalPlans.length, { targetDir });
    finalPlans.push(residualPlan);
    reports.push({
      path: residualPlan.modulePath,
      emittedMemberNames: [...residualPlan.memberNames],
      id: residualOperation.id,
      matchedAtomicModuleIds: residualModules.map((modulePlan) => modulePlan.id),
      matchedAtomicModules: residualModules.map((modulePlan) => ({
        id: modulePlan.id,
        memberNames: [...modulePlan.memberNames],
        startOrdinal: modulePlan.startOrdinal,
      })),
      changedNameCount: 0,
      requestedBindings: [],
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
  if (ownerIds.size === 0) {
    return null;
  }
  if (!analysis?.owners) {
    return ownerIds;
  }
  const ownerById = new Map(analysis.owners.map((owner) => [owner.id, owner]));
  const unknownOwnerIds = [...ownerIds].filter((ownerId) => !ownerById.has(ownerId));
  if (unknownOwnerIds.length > 0) {
    const sample = unknownOwnerIds.slice(0, 8).join(", ");
    const remainder = unknownOwnerIds.length > 8 ? ` (+${unknownOwnerIds.length - 8} more)` : "";
    throw new Error(`logicalSelectedOwnerIdsForChunk referenced unknown owners outside analysis.owners: ${sample}${remainder}`);
  }
  return expandLogicalOwnerDependencyClosure(ownerIds, ownerById);
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
  const targetPath = typeof target.path === "string" && target.path !== "" ? normalizeRelativeModulePath(target.path) : null;
  if (!targetPath) {
    throw new Error(`logical module ${operationId} requires target.path`);
  }
  return {
    ...target,
    path: targetPath,
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
    name: normalizeLogicalMemberName(member, operation, index),
    selector: {
      ...member.selector,
      binding: {
        ...member.selector.binding,
      },
      ...(member.selector.file ? { file: normalizeRelativeFile(member.selector.file) } : {}),
    },
  };
}

function normalizeLogicalMemberName(member, operation, index) {
  if (member.name !== undefined) {
    if (typeof member.name !== "string" || member.name === "") {
      throw new Error(`define_logical_module ${operation.id} member[${index}] requires member.name to be a non-empty string`);
    }
    return member.name;
  }
  return member.selector.binding.name;
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

function buildModulesByOwnerId(modulePlans) {
  const modulesByOwnerId = new Map();
  for (const modulePlan of modulePlans) {
    for (const ownerId of modulePlan.ownerIds) {
      if (!modulesByOwnerId.has(ownerId)) {
        modulesByOwnerId.set(ownerId, []);
      }
      modulesByOwnerId.get(ownerId).push(modulePlan);
    }
  }
  return modulesByOwnerId;
}

function resolveLogicalMember(member, { analysis, modulesByOwnerId, modulesBySymbol, operationId }) {
  if (isImportKind(member.selector.binding.kind ?? null)) {
    return {
      matched: true,
      modulePlan: null,
      ownerId: null,
    };
  }
  const ownerId =
    member.selector.owner?.id ??
    (analysis ? resolveOwnerIdFromAnalysis(analysis, member, { operationId }) : null);
  if (ownerId) {
    const ownerMatches = modulesByOwnerId.get(ownerId) ?? [];
    if (ownerMatches.length === 0) {
      return {
        matched: false,
        modulePlan: null,
        ownerId,
      };
    }
    const symbolMatches = ownerMatches.filter((modulePlan) => modulePlan.memberNames.includes(member.selector.binding.name));
    if (symbolMatches.length === 1) {
      return {
        matched: true,
        modulePlan: symbolMatches[0],
        ownerId,
      };
    }
    if (symbolMatches.length > 1) {
      throw new Error(
        `define_logical_module ${operationId} member ${member.id} matched multiple owner fragments for ${member.selector.binding.name}: ${symbolMatches
          .map((modulePlan) => modulePlan.id)
          .join(", ")}`
      );
    }
    if (ownerMatches.length > 1) {
      throw new Error(
        `define_logical_module ${operationId} member ${member.id} matched owner ${ownerId} but no fragment exposed ${member.selector.binding.name}`
      );
    }
    return {
      matched: true,
      modulePlan: ownerMatches[0],
      ownerId,
    };
  }
  const matches = modulesBySymbol.get(member.selector.binding.name) ?? [];
  if (matches.length === 0) {
    return {
      matched: false,
      modulePlan: null,
      ownerId: null,
    };
  }
  if (matches.length > 1) {
    throw new Error(
      `define_logical_module ${operationId} member ${member.id} matched multiple atomic modules for ${member.selector.binding.name}: ${matches
        .map((modulePlan) => modulePlan.id)
        .join(", ")}`
    );
  }
  return {
    matched: true,
    modulePlan: matches[0],
    ownerId: null,
  };
}

function groupLogicalModuleOperations(logicalOperations) {
  const residualOperations = logicalOperations.filter((operation) => operation.operation === "define_residual_module");
  const grouped = new Map();
  for (const operation of logicalOperations) {
    if (operation.operation !== "define_logical_module") {
      continue;
    }
    const key = JSON.stringify({
      file: operation.target.file ?? null,
      init: operation.target.init ?? null,
      path: operation.target.path,
    });
    if (!grouped.has(key)) {
      const targetPath = operation.target.path;
      grouped.set(key, {
        id: `logical_module__${sanitizeIdentifier(targetPath.split("/").join("__"))}`,
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

function mergeModuleGroup(selectedModules, operation, index, { requestedBindings = [], targetDir }) {
  const targetPath = operation.target.path;
  const attachedItemIds = [];
  const attachedItemIdSet = new Set();
  const atomicBoundaryUnits = [];
  const memberNames = [];
  const memberNameSet = new Set();
  const ownerIds = [];
  const ownerIdSet = new Set();
  const ownerFragments = [];
  const unitIds = [];
  const unitIdSet = new Set();
  let bytes = 0;
  let hasNullBytes = false;
  let lines = 0;
  let startOrdinal = Number.POSITIVE_INFINITY;
  const bindingPlacements = requestedBindings
    .filter((binding) => binding.matched && binding.name !== binding.sourceName)
    .map((binding) => ({
      id: binding.id,
      kind: binding.kind,
      name: binding.name,
      ownerId: binding.ownerId,
      sourceName: binding.sourceName,
    }));
  for (const modulePlan of selectedModules) {
    atomicBoundaryUnits.push({
      attachedItemIds: [...modulePlan.attachedItemIds],
      id: modulePlan.id,
      memberNames: [...modulePlan.memberNames],
      ownerIds: [...modulePlan.ownerIds],
      ownerFragments: cloneOwnerFragments(modulePlan.ownerFragments),
      startOrdinal: modulePlan.startOrdinal,
      unitIds: [...modulePlan.unitIds],
    });
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
    for (const ownerFragment of modulePlan.ownerFragments ?? []) {
      ownerFragments.push({
        ...ownerFragment,
        declaratorIndices: [...ownerFragment.declaratorIndices],
        memberNames: [...ownerFragment.memberNames],
      });
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
    atomicBoundaryUnits,
    bytes: hasNullBytes ? null : bytes,
    id: operation.id,
    index,
    modulePath: targetPath,
    lines,
    memberNames: applyBindingPlacementsToMemberNames(memberNames, bindingPlacements),
    nameHint: sanitizeIdentifier(targetPath.split("/").at(-1) ?? targetPath),
    ownerIds,
    ownerFragments,
    bindingPlacements,
    requestedBindings: requestedBindings.map((binding) => ({ ...binding })),
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
    ...(Array.isArray(modulePlan.atomicBoundaryUnits)
      ? {
          atomicBoundaryUnits: modulePlan.atomicBoundaryUnits.map((unit) => ({
            attachedItemIds: [...unit.attachedItemIds],
            id: unit.id,
            memberNames: [...unit.memberNames],
            ownerIds: [...unit.ownerIds],
            ...(Array.isArray(unit.ownerFragments)
              ? {
                  ownerFragments: cloneOwnerFragments(unit.ownerFragments),
                }
              : {}),
            startOrdinal: unit.startOrdinal,
            unitIds: [...unit.unitIds],
          })),
        }
      : {}),
    ...(modulePlan.bytes === null ? { bytes: null } : { bytes: modulePlan.bytes }),
    id: modulePlan.id,
    index: modulePlan.index,
    ...(modulePlan.initName ? { initName: modulePlan.initName } : {}),
    lines: modulePlan.lines,
    memberNames: [...modulePlan.memberNames],
    modulePath: modulePlan.modulePath,
    nameHint: modulePlan.nameHint,
    ownerIds: [...modulePlan.ownerIds],
    ...(Array.isArray(modulePlan.ownerFragments)
      ? {
          ownerFragments: cloneOwnerFragments(modulePlan.ownerFragments),
        }
      : {}),
    ...(Array.isArray(modulePlan.bindingPlacements)
      ? {
          bindingPlacements: modulePlan.bindingPlacements.map((entry) => ({ ...entry })),
        }
      : {}),
    ...(Array.isArray(modulePlan.requestedBindings)
      ? {
          requestedBindings: modulePlan.requestedBindings.map((binding) => ({ ...binding })),
        }
      : {}),
    startOrdinal: modulePlan.startOrdinal,
    ...(modulePlan.targetFile ? { targetFile: modulePlan.targetFile } : {}),
    unitIds: [...modulePlan.unitIds],
  };
}

function applyBindingPlacementsToMemberNames(memberNames, bindingPlacements) {
  const renamed = new Map(bindingPlacements.map((entry) => [entry.sourceName, entry.name]));
  return memberNames
    .map((memberName) => renamed.get(memberName) ?? memberName)
    .filter((memberName, index, array) => array.indexOf(memberName) === index)
    .sort();
}

function cloneOwnerFragments(ownerFragments) {
  return ownerFragments.map((fragment) => ({
    ...fragment,
    declaratorIndices: [...fragment.declaratorIndices],
    memberNames: [...fragment.memberNames],
  }));
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

function normalizeRelativeModulePath(value) {
  const normalized = normalizeRelativeFile(value);
  return normalized.endsWith(".js") ? normalized.slice(0, -3) : normalized;
}

function sanitizeIdentifier(value) {
  return value
    .replace(/[^A-Za-z0-9_$]+/g, "_")
    .replace(/^[^A-Za-z_$]+/, "_")
    .replace(/_+/g, "_");
}

function resolveOwnerIdFromAnalysis(analysis, member, { operationId = "<logical-module>" } = {}) {
  const resolvedName = member.selector.binding.name;
  const expectedType = manifestDeclarationKind(member.selector.binding.kind ?? null);
  const matches = analysis.owners.filter((owner) => {
    if (!owner.names?.includes(resolvedName)) {
      return false;
    }
    if (expectedType && owner.type !== expectedType) {
      return false;
    }
    if (member.selector.owner?.line && owner.line !== member.selector.owner.line) {
      return false;
    }
    return true;
  });
  if (matches.length === 0) {
    return null;
  }
  if (matches.length > 1) {
    throw new Error(
      `logical member ${member.id} in ${operationId} matched multiple analysis owners for ${resolvedName}: ${matches
        .map((owner) => owner.id)
        .join(", ")}`
    );
  }
  return matches[0].id;
}

function expandLogicalOwnerDependencyClosure(seedOwnerIds, ownerById) {
  const selectedOwnerIds = new Set(seedOwnerIds);
  const stack = [...selectedOwnerIds];
  while (stack.length > 0) {
    const owner = ownerById.get(stack.pop());
    if (!owner) {
      continue;
    }
    for (const dependencyOwnerId of localDeclarationDependencyOwnerIds(owner, ownerById)) {
      if (selectedOwnerIds.has(dependencyOwnerId)) {
        continue;
      }
      selectedOwnerIds.add(dependencyOwnerId);
      stack.push(dependencyOwnerId);
    }
  }
  return selectedOwnerIds;
}

function localDeclarationDependencyOwnerIds(owner, ownerById) {
  const dependencyOwnerIds = new Set();
  for (const bucket of [owner.readsTopLevel, owner.writesTopLevel, owner.memberWritesTopLevel]) {
    for (const phase of ["eager", "lazy"]) {
      for (const access of bucket?.[phase] ?? []) {
        if (access.kind !== "local_declaration" || !access.ownerId || access.ownerId === owner.id) {
          continue;
        }
        if (!ownerById.has(access.ownerId)) {
          continue;
        }
        dependencyOwnerIds.add(access.ownerId);
      }
    }
  }
  return dependencyOwnerIds;
}

function manifestDeclarationKind(kind) {
  return kind === "VariableDeclarator" ? "VariableDeclaration" : kind;
}

function isImportKind(kind) {
  return kind === "ImportSpecifier" || kind === "ImportDefaultSpecifier" || kind === "ImportNamespaceSpecifier";
}
