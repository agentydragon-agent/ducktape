import { deriveSelectedModuleTarget } from "./planner.mjs";

const ANALYSIS_OWNER_BY_ID_CACHE = new WeakMap();
const ANALYSIS_OWNER_MATCH_INDEX_CACHE = new WeakMap();
const LOGICAL_MODULE_OPERATIONS_CACHE = new WeakMap();
const LOGICAL_MODULE_CHUNK_OPERATIONS_CACHE = new WeakMap();
const LOGICAL_MODULE_CHUNK_GROUPS_CACHE = new WeakMap();
const LOGICAL_MEMBER_OWNER_ID_CACHE = new WeakMap();
const OWNER_LOCAL_DEPENDENCY_IDS_CACHE = new WeakMap();
const NULL_OWNER_ID = Symbol("logical_module.null_owner_id");

export function getLogicalModuleOperations(operations) {
  if (!(operations instanceof Array)) {
    return normalizeLogicalModuleOperations([]);
  }
  const cached = LOGICAL_MODULE_OPERATIONS_CACHE.get(operations);
  if (cached) {
    return cached;
  }
  const normalized = normalizeLogicalModuleOperations(
    operations.filter(
      (operation) =>
        operation?.operation === "define_logical_module" || operation?.operation === "define_residual_module"
    )
  );
  LOGICAL_MODULE_OPERATIONS_CACHE.set(operations, normalized);
  return normalized;
}

export function buildLogicalModulePlans(currentModules, operations, { analysis = null, chunkId, targetDir }) {
  const logicalOperations = getChunkLogicalModuleOperations(operations, chunkId);
  if (logicalOperations.length === 0) {
    return {
      counts: {
        blockedMembers: 0,
        explicitModules: 0,
        residualModules: 0,
        totalModules: currentModules.length,
        unmatchedMembers: 0,
      },
      modules: currentModules.map(cloneModulePlan),
      reports: [],
    };
  }

  const ownerById = getOwnerByIdForAnalysis(analysis);
  const claimableAtomicModules = [...currentModules].sort(
    (left, right) => left.startOrdinal - right.startOrdinal || left.id.localeCompare(right.id)
  );
  const moduleById = new Map(claimableAtomicModules.map((modulePlan) => [modulePlan.id, modulePlan]));
  const modulesByOwnerId = buildModulesByOwnerId(claimableAtomicModules);
  const modulesBySymbol = buildModulesBySymbol(claimableAtomicModules);
  const dependencyIdsByModuleId = buildModuleDependencyIdsByModuleId(claimableAtomicModules, {
    analysis,
    modulesByOwnerId,
  });
  const { availableModuleIds, blockingReasonsByModuleId } = computeExtractorAvailability(currentModules, {
    analysis,
    dependencyIdsByModuleId,
    ownerById,
  });
  const lowerableAtomicModules = claimableAtomicModules.filter((modulePlan) => availableModuleIds.has(modulePlan.id));
  const directClaimedModuleIds = new Map();
  const finalClaimedModuleIds = new Map();
  const preparedExplicitOperations = [];
  const explicitModulePlans = [];
  const reports = [];
  let residualOperation = null;
  let blockedMembers = 0;
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
        availableModuleIds,
        analysis,
        blockingReasonsByModuleId,
        modulesByOwnerId,
        modulesBySymbol,
        operationId: operation.id,
      });
      const requestedBinding = {
        blockingReasons: [...resolvedMember.blockingReasons],
        blocked: resolvedMember.blocked,
        anchor: !importMember,
        lowerable: resolvedMember.lowerable,
        name: member.name,
        id: member.id,
        kind: member.selector.binding.kind,
        matched: resolvedMember.matched,
        moduleId: resolvedMember.modulePlan?.id ?? null,
        sourceName: member.selector.binding.name,
        status: resolvedMember.status,
        ownerId: resolvedMember.ownerId ?? null,
        changedName: member.name !== member.selector.binding.name,
      };
      requestedBindings.push(requestedBinding);
      if (importMember) {
        continue;
      }
      if (!resolvedMember.matched) {
        unmatchedMembers += 1;
        continue;
      }
      if (!resolvedMember.lowerable || !resolvedMember.modulePlan) {
        blockedMembers += 1;
        continue;
      }
      const modulePlan = resolvedMember.modulePlan;
      if (!selectedModuleIdSet.has(modulePlan.id)) {
        selectedModuleIdSet.add(modulePlan.id);
        selectedModules.push(modulePlan);
      }
    }
    if (selectedModules.length === 0) {
      preparedExplicitOperations.push({
        directSelectedModules: [],
        operation,
        requestedBindings,
      });
      continue;
    }
    selectedModules.sort((left, right) => left.startOrdinal - right.startOrdinal || left.id.localeCompare(right.id));
    for (const modulePlan of selectedModules) {
      const priorOwner = directClaimedModuleIds.get(modulePlan.id);
      if (priorOwner) {
        throw new Error(
          `define_logical_module operations overlap on atomic module ${modulePlan.id}: ${priorOwner} and ${operation.id}; owners=${modulePlan.ownerIds.join(",")} members=${modulePlan.memberNames.join(",")}`
        );
      }
      directClaimedModuleIds.set(modulePlan.id, operation.id);
    }
    preparedExplicitOperations.push({
      directSelectedModules: selectedModules,
      operation,
      requestedBindings,
    });
  }

  const reachableDependencyIdsByOperationId = buildReachableDependencyIdsByOperationId(preparedExplicitOperations, {
    claimedModuleIds: directClaimedModuleIds,
    dependencyIdsByModuleId,
    moduleById,
  });

  for (const { directSelectedModules, operation, requestedBindings } of preparedExplicitOperations) {
    if (directSelectedModules.length === 0) {
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
    const dependencyClosedModules = expandSelectedModuleDependencyClosure(directSelectedModules, {
      dependencyIdsByModuleId,
      moduleById,
      reachableDependencyIds: reachableDependencyIdsByOperationId.get(operation.id) ?? new Set(),
    });
    dependencyClosedModules.sort(
      (left, right) => left.startOrdinal - right.startOrdinal || left.id.localeCompare(right.id)
    );
    for (const modulePlan of dependencyClosedModules) {
      const priorOwner = finalClaimedModuleIds.get(modulePlan.id);
      if (priorOwner && priorOwner !== operation.id) {
        throw new Error(
          `define_logical_module operations overlap on atomic module ${modulePlan.id}: ${priorOwner} and ${operation.id}; owners=${modulePlan.ownerIds.join(",")} members=${modulePlan.memberNames.join(",")}`
        );
      }
      finalClaimedModuleIds.set(modulePlan.id, operation.id);
    }
    const mergedPlan = mergeModuleGroup(dependencyClosedModules, operation, explicitModulePlans.length, {
      requestedBindings,
      targetDir,
    });
    explicitModulePlans.push(mergedPlan);
    reports.push({
      path: mergedPlan.modulePath,
      emittedMemberNames: [...mergedPlan.memberNames],
      id: operation.id,
      materialized: true,
      matchedAtomicModuleIds: dependencyClosedModules.map((modulePlan) => modulePlan.id),
      matchedAtomicModules: dependencyClosedModules.map((modulePlan) => ({
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

  const residualModules = lowerableAtomicModules.filter((modulePlan) => !finalClaimedModuleIds.has(modulePlan.id));
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
      blockedMembers,
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
  for (const operation of getChunkLogicalModuleOperations(operations, chunkId)) {
    if (operation.operation !== "define_logical_module") {
      continue;
    }
    for (const member of operation.members) {
      const ownerId = resolveCanonicalOwnerIdForLogicalMember(member, {
        analysis,
        operationId: operation.id,
      });
      if (typeof ownerId === "string" && ownerId !== "") {
        ownerIds.add(ownerId);
      }
    }
  }
  if (ownerIds.size === 0) {
    return null;
  }
  return closeSelectedOwnerIdsOverDependencyGraph(ownerIds, {
    analysis,
    callerName: "logicalSelectedOwnerIdsForChunk",
  });
}

export function closeSelectedOwnerIdsOverDependencyGraph(
  seedOwnerIds,
  { analysis = null, callerName = "closeSelectedOwnerIdsOverDependencyGraph" } = {}
) {
  const selectedOwnerIds = new Set(seedOwnerIds ?? []);
  if (!analysis?.owners || selectedOwnerIds.size === 0) {
    return selectedOwnerIds;
  }
  const ownerById = getOwnerByIdForAnalysis(analysis);
  const unknownOwnerIds = [...selectedOwnerIds].filter((ownerId) => !ownerById.has(ownerId));
  if (unknownOwnerIds.length > 0) {
    const sample = unknownOwnerIds.slice(0, 8).join(", ");
    const remainder = unknownOwnerIds.length > 8 ? ` (+${unknownOwnerIds.length - 8} more)` : "";
    throw new Error(`${callerName} referenced unknown owners outside analysis.owners: ${sample}${remainder}`);
  }
  return expandLogicalOwnerDependencyClosure(selectedOwnerIds, ownerById);
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

function getChunkLogicalModuleOperations(operations, chunkId) {
  const normalizedChunkId = normalizeRelativeFile(chunkId);
  if (!(operations instanceof Array)) {
    return [];
  }
  let cachedByChunk = LOGICAL_MODULE_CHUNK_OPERATIONS_CACHE.get(operations);
  if (!cachedByChunk) {
    cachedByChunk = new Map();
    LOGICAL_MODULE_CHUNK_OPERATIONS_CACHE.set(operations, cachedByChunk);
  }
  const cached = cachedByChunk.get(normalizedChunkId);
  if (cached) {
    return cached;
  }
  const logicalOperations = getLogicalModuleOperations(operations).filter(
    (operation) => operation.selector.chunkId === normalizedChunkId
  );
  cachedByChunk.set(normalizedChunkId, logicalOperations);
  return logicalOperations;
}

function normalizeLogicalTarget(target, operationId) {
  if (!target || typeof target !== "object") {
    throw new Error(`logical module ${operationId} requires target`);
  }
  const targetPath =
    typeof target.path === "string" && target.path !== "" ? normalizeRelativeModulePath(target.path) : null;
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
  if (
    !member.selector.binding ||
    typeof member.selector.binding?.name !== "string" ||
    member.selector.binding.name === ""
  ) {
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
      throw new Error(
        `define_logical_module ${operation.id} member[${index}] requires member.name to be a non-empty string`
      );
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

function currentExtractorCompatibilityReasons(modulePlan, ownerById) {
  const reasons = [];
  for (const ownerId of modulePlan.ownerIds ?? []) {
    const owner = ownerById.get(ownerId);
    if (!owner || owner.currentExtractorCompatible !== false) {
      continue;
    }
    const fragmentCount = (modulePlan.ownerFragments ?? []).filter((fragment) => fragment.ownerId === ownerId).length;
    if (owner.type === "VariableDeclaration" && fragmentCount > 0) {
      continue;
    }
    reasons.push(`owner_not_current_extractor_compatible:${ownerId}`);
  }
  return reasons;
}

function computeExtractorAvailability(currentModules, { analysis, dependencyIdsByModuleId = null, ownerById }) {
  if (!analysis?.owners) {
    return {
      availableModuleIds: new Set(currentModules.map((modulePlan) => modulePlan.id)),
      blockingReasonsByModuleId: new Map(),
    };
  }
  const allModules = [...currentModules];
  const availableModuleIds = new Set();
  const blockingReasonsByModuleId = new Map();
  for (const modulePlan of allModules) {
    const blockingReasons = currentExtractorCompatibilityReasons(modulePlan, ownerById);
    if (blockingReasons.length === 0) {
      availableModuleIds.add(modulePlan.id);
      continue;
    }
    blockingReasonsByModuleId.set(modulePlan.id, blockingReasons);
  }
  const effectiveDependencyIdsByModuleId =
    dependencyIdsByModuleId ??
    buildModuleDependencyIdsByModuleId(allModules, {
      analysis,
      modulesByOwnerId: buildModulesByOwnerId(allModules),
    });
  // Availability is a fixed point, not a one-shot per-owner predicate. Propagate
  // blockers through the reverse dependency graph instead of repeatedly scanning
  // every module until convergence.
  const dependentModuleIdsByDependencyId = new Map();
  for (const [moduleId, dependencyModuleIds] of effectiveDependencyIdsByModuleId.entries()) {
    for (const dependencyModuleId of dependencyModuleIds) {
      if (!dependentModuleIdsByDependencyId.has(dependencyModuleId)) {
        dependentModuleIdsByDependencyId.set(dependencyModuleId, []);
      }
      dependentModuleIdsByDependencyId.get(dependencyModuleId).push(moduleId);
    }
  }
  const unavailableQueue = allModules
    .filter((modulePlan) => !availableModuleIds.has(modulePlan.id))
    .map((modulePlan) => modulePlan.id);
  for (let queueIndex = 0; queueIndex < unavailableQueue.length; queueIndex++) {
    const unavailableModuleId = unavailableQueue[queueIndex];
    for (const dependentModuleId of dependentModuleIdsByDependencyId.get(unavailableModuleId) ?? []) {
      if (!availableModuleIds.has(dependentModuleId)) {
        continue;
      }
      availableModuleIds.delete(dependentModuleId);
      const dependencyReasons = blockingReasonsByModuleId.get(unavailableModuleId) ?? [];
      const blockingReasons = [`depends_on_unavailable_module:${unavailableModuleId}`, ...dependencyReasons].filter(
        (reason, index, array) => array.indexOf(reason) === index
      );
      blockingReasonsByModuleId.set(dependentModuleId, blockingReasons);
      unavailableQueue.push(dependentModuleId);
    }
  }
  return {
    availableModuleIds,
    blockingReasonsByModuleId,
  };
}

function buildModuleDependencyIdsByModuleId(modulePlans, { analysis, modulesByOwnerId }) {
  const dependencyIdsByModuleId = new Map(modulePlans.map((modulePlan) => [modulePlan.id, new Set()]));
  if (!analysis?.owners) {
    return dependencyIdsByModuleId;
  }
  const ownerById = new Map(analysis.owners.map((owner) => [owner.id, owner]));
  for (const modulePlan of modulePlans) {
    const dependencyIds = dependencyIdsByModuleId.get(modulePlan.id);
    for (const ownerId of modulePlan.ownerIds) {
      const owner = ownerById.get(ownerId);
      if (!owner) {
        continue;
      }
      for (const dependencyOwnerId of localDeclarationDependencyOwnerIds(owner, ownerById)) {
        for (const dependencyModule of modulesByOwnerId.get(dependencyOwnerId) ?? []) {
          if (dependencyModule.id !== modulePlan.id) {
            dependencyIds.add(dependencyModule.id);
          }
        }
      }
    }
  }
  return dependencyIdsByModuleId;
}

function buildReachableDependencyIdsByOperationId(
  preparedExplicitOperations,
  { claimedModuleIds, dependencyIdsByModuleId, moduleById }
) {
  const reachableDependencyIdsByOperationId = new Map();
  const assignedDependencyOperationIdByModuleId = new Map();
  const prioritizedOperations = preparedExplicitOperations
    .map(({ directSelectedModules, operation }, operationIndex) => ({
      directSelectedModules,
      operation,
      operationIndex,
      startOrdinal:
        directSelectedModules.length === 0
          ? Number.POSITIVE_INFINITY
          : Math.min(...directSelectedModules.map((modulePlan) => modulePlan.startOrdinal)),
    }))
    .sort(
      (left, right) =>
        left.startOrdinal - right.startOrdinal ||
        left.operationIndex - right.operationIndex ||
        left.operation.id.localeCompare(right.operation.id)
    );

  for (const { operation } of preparedExplicitOperations) {
    reachableDependencyIdsByOperationId.set(operation.id, new Set());
  }

  for (const { directSelectedModules, operation } of prioritizedOperations) {
    if (directSelectedModules.length === 0) {
      continue;
    }
    const reachableDependencyIds = reachableDependencyIdsByOperationId.get(operation.id);
    const stack = directSelectedModules.map((modulePlan) => modulePlan.id);
    const scannedModuleIds = new Set(stack);
    while (stack.length > 0) {
      const moduleId = stack.pop();
      for (const dependencyModuleId of dependencyIdsByModuleId.get(moduleId) ?? []) {
        if (!moduleById.has(dependencyModuleId)) {
          continue;
        }
        if (claimedModuleIds.has(dependencyModuleId)) {
          continue;
        }
        if (assignedDependencyOperationIdByModuleId.has(dependencyModuleId)) {
          continue;
        }
        assignedDependencyOperationIdByModuleId.set(dependencyModuleId, operation.id);
        reachableDependencyIds.add(dependencyModuleId);
        if (!scannedModuleIds.has(dependencyModuleId)) {
          scannedModuleIds.add(dependencyModuleId);
          stack.push(dependencyModuleId);
        }
      }
    }
  }

  return reachableDependencyIdsByOperationId;
}

function expandSelectedModuleDependencyClosure(
  selectedModules,
  { dependencyIdsByModuleId, moduleById, reachableDependencyIds }
) {
  const selectedModuleIds = new Set(selectedModules.map((modulePlan) => modulePlan.id));
  const stack = [...selectedModuleIds];
  while (stack.length > 0) {
    const moduleId = stack.pop();
    for (const dependencyModuleId of dependencyIdsByModuleId.get(moduleId) ?? []) {
      if (selectedModuleIds.has(dependencyModuleId)) {
        continue;
      }
      if (!reachableDependencyIds.has(dependencyModuleId)) {
        continue;
      }
      if (!moduleById.has(dependencyModuleId)) {
        continue;
      }
      selectedModuleIds.add(dependencyModuleId);
      stack.push(dependencyModuleId);
    }
  }
  return [...selectedModuleIds].map((moduleId) => moduleById.get(moduleId));
}

function resolveLogicalMember(
  member,
  { availableModuleIds, analysis, blockingReasonsByModuleId, modulesByOwnerId, modulesBySymbol, operationId }
) {
  if (isImportKind(member.selector.binding.kind ?? null)) {
    return {
      blocked: false,
      blockingReasons: [],
      lowerable: true,
      matched: true,
      modulePlan: null,
      ownerId: null,
      status: "matched",
    };
  }
  const ownerId = resolveCanonicalOwnerIdForLogicalMember(member, {
    analysis,
    operationId,
  });
  const symbolMatches = modulesBySymbol.get(member.selector.binding.name) ?? [];
  if (ownerId) {
    const ownerMatches = modulesByOwnerId.get(ownerId) ?? [];
    if (ownerMatches.length === 0) {
      return resolveUniqueSymbolMatch(symbolMatches, {
        availableModuleIds,
        blockingReasonsByModuleId,
        member,
        operationId,
        ownerId,
      });
    }
    const ownerSymbolMatches = ownerMatches.filter((modulePlan) =>
      modulePlan.memberNames.includes(member.selector.binding.name)
    );
    if (ownerSymbolMatches.length === 1) {
      return classifyResolvedModule(ownerSymbolMatches[0], { availableModuleIds, blockingReasonsByModuleId, ownerId });
    }
    if (ownerSymbolMatches.length > 1) {
      throw new Error(
        `define_logical_module ${operationId} member ${member.id} matched multiple owner fragments for ${member.selector.binding.name}: ${ownerSymbolMatches
          .map((modulePlan) => modulePlan.id)
          .join(", ")}`
      );
    }
    return resolveUniqueSymbolMatch(symbolMatches, {
      availableModuleIds,
      blockingReasonsByModuleId,
      member,
      operationId,
      ownerId,
    });
  }
  if (symbolMatches.length === 0) {
    return {
      blocked: false,
      blockingReasons: [],
      lowerable: false,
      matched: false,
      modulePlan: null,
      ownerId: null,
      status: "unmatched",
    };
  }
  if (symbolMatches.length > 1) {
    throw new Error(
      `define_logical_module ${operationId} member ${member.id} matched multiple atomic modules for ${member.selector.binding.name}: ${symbolMatches
        .map((modulePlan) => modulePlan.id)
        .join(", ")}`
    );
  }
  return classifyResolvedModule(symbolMatches[0], { availableModuleIds, blockingReasonsByModuleId, ownerId: null });
}

function resolveUniqueSymbolMatch(
  matches,
  { availableModuleIds, blockingReasonsByModuleId, member, operationId, ownerId }
) {
  if (matches.length === 0) {
    return {
      blocked: false,
      blockingReasons: [],
      lowerable: false,
      matched: false,
      modulePlan: null,
      ownerId,
      status: "unmatched",
    };
  }
  if (matches.length > 1) {
    throw new Error(
      `define_logical_module ${operationId} member ${member.id} matched multiple atomic modules for ${member.selector.binding.name}: ${matches
        .map((modulePlan) => modulePlan.id)
        .join(", ")}`
    );
  }
  return classifyResolvedModule(matches[0], { availableModuleIds, blockingReasonsByModuleId, ownerId });
}

function classifyResolvedModule(modulePlan, { availableModuleIds, blockingReasonsByModuleId, ownerId }) {
  const lowerable = availableModuleIds.has(modulePlan.id);
  return {
    blocked: !lowerable,
    blockingReasons: [...(blockingReasonsByModuleId.get(modulePlan.id) ?? [])],
    lowerable,
    matched: true,
    modulePlan,
    ownerId,
    status: lowerable ? "matched" : "blocked",
  };
}

function groupLogicalModuleOperations(logicalOperations) {
  const cached = LOGICAL_MODULE_CHUNK_GROUPS_CACHE.get(logicalOperations);
  if (cached) {
    return cached;
  }
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
  const normalizedGroups = [
    ...grouped.values(),
    ...residualOperations.map((operation) => ({ ...operation, operationIds: [operation.id] })),
  ];
  LOGICAL_MODULE_CHUNK_GROUPS_CACHE.set(logicalOperations, normalizedGroups);
  return normalizedGroups;
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

function resolveCanonicalOwnerIdForLogicalMember(member, { analysis = null, operationId = "<logical-module>" } = {}) {
  const selectorOwnerId = member.selector.owner?.id ?? null;
  if (!analysis || isImportKind(member.selector.binding.kind ?? null)) {
    return selectorOwnerId;
  }
  // For logical-module planning, boundary analysis is the authoritative source of
  // binding ownership. Checked-in owner ids are useful disambiguation hints, but
  // they can drift as we refine fragment splitting. We therefore resolve against
  // the analyzed binding first and only fall back to the selector owner hint when
  // analysis cannot identify the binding.
  return getResolvedOwnerIdFromAnalysis(analysis, member, { operationId }) ?? selectorOwnerId;
}

function getResolvedOwnerIdFromAnalysis(analysis, member, { operationId = "<logical-module>" } = {}) {
  let cachedByMember = LOGICAL_MEMBER_OWNER_ID_CACHE.get(analysis);
  if (!cachedByMember) {
    cachedByMember = new WeakMap();
    LOGICAL_MEMBER_OWNER_ID_CACHE.set(analysis, cachedByMember);
  }
  if (cachedByMember.has(member)) {
    const cached = cachedByMember.get(member);
    return cached === NULL_OWNER_ID ? null : cached;
  }
  const resolved = resolveOwnerIdFromAnalysis(analysis, member, { operationId });
  cachedByMember.set(member, resolved ?? NULL_OWNER_ID);
  return resolved;
}

function resolveOwnerIdFromAnalysis(analysis, member, { operationId = "<logical-module>" } = {}) {
  const resolvedName = member.selector.binding.name;
  const expectedType = manifestDeclarationKind(member.selector.binding.kind ?? null);
  const ownerLine = member.selector.owner?.line ?? null;
  const matchIndex = getOwnerMatchIndexForAnalysis(analysis);
  const matches = getIndexedOwnerMatches(matchIndex, {
    expectedType,
    line: ownerLine,
    name: resolvedName,
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
  const cached = OWNER_LOCAL_DEPENDENCY_IDS_CACHE.get(owner);
  if (cached) {
    return cached;
  }
  const dependencyOwnerIds = [];
  const seenDependencyOwnerIds = new Set();
  for (const bucket of [owner.readsTopLevel, owner.writesTopLevel, owner.memberWritesTopLevel]) {
    for (const phase of ["eager", "lazy"]) {
      for (const access of bucket?.[phase] ?? []) {
        if (access.kind !== "local_declaration" || !access.ownerId || access.ownerId === owner.id) {
          continue;
        }
        if (!ownerById.has(access.ownerId)) {
          continue;
        }
        if (seenDependencyOwnerIds.has(access.ownerId)) {
          continue;
        }
        seenDependencyOwnerIds.add(access.ownerId);
        dependencyOwnerIds.push(access.ownerId);
      }
    }
  }
  OWNER_LOCAL_DEPENDENCY_IDS_CACHE.set(owner, dependencyOwnerIds);
  return dependencyOwnerIds;
}

function getOwnerByIdForAnalysis(analysis) {
  if (!analysis?.owners) {
    return new Map();
  }
  const cached = ANALYSIS_OWNER_BY_ID_CACHE.get(analysis);
  if (cached) {
    return cached;
  }
  const ownerById = new Map(analysis.owners.map((owner) => [owner.id, owner]));
  ANALYSIS_OWNER_BY_ID_CACHE.set(analysis, ownerById);
  return ownerById;
}

function getOwnerMatchIndexForAnalysis(analysis) {
  const cached = ANALYSIS_OWNER_MATCH_INDEX_CACHE.get(analysis);
  if (cached) {
    return cached;
  }
  const byName = new Map();
  const byNameAndLine = new Map();
  const byNameAndType = new Map();
  const byNameTypeAndLine = new Map();
  for (const owner of analysis.owners ?? []) {
    for (const name of owner.names ?? []) {
      appendIndexedOwner(byName, name, owner);
      appendIndexedOwner(byNameAndType, `${name}\u0000${owner.type}`, owner);
      if (owner.line !== undefined && owner.line !== null) {
        appendIndexedOwner(byNameAndLine, `${name}\u0000${owner.line}`, owner);
        appendIndexedOwner(byNameTypeAndLine, `${name}\u0000${owner.type}\u0000${owner.line}`, owner);
      }
    }
  }
  const matchIndex = {
    byName,
    byNameAndLine,
    byNameAndType,
    byNameTypeAndLine,
  };
  ANALYSIS_OWNER_MATCH_INDEX_CACHE.set(analysis, matchIndex);
  return matchIndex;
}

function appendIndexedOwner(index, key, owner) {
  if (!index.has(key)) {
    index.set(key, []);
  }
  index.get(key).push(owner);
}

function getIndexedOwnerMatches(matchIndex, { expectedType, line, name }) {
  if (expectedType && line !== null) {
    return matchIndex.byNameTypeAndLine.get(`${name}\u0000${expectedType}\u0000${line}`) ?? [];
  }
  if (expectedType) {
    return matchIndex.byNameAndType.get(`${name}\u0000${expectedType}`) ?? [];
  }
  if (line !== null) {
    return matchIndex.byNameAndLine.get(`${name}\u0000${line}`) ?? [];
  }
  return matchIndex.byName.get(name) ?? [];
}

function manifestDeclarationKind(kind) {
  return kind === "VariableDeclarator" ? "VariableDeclaration" : kind;
}

function isImportKind(kind) {
  return kind === "ImportSpecifier" || kind === "ImportDefaultSpecifier" || kind === "ImportNamespaceSpecifier";
}
