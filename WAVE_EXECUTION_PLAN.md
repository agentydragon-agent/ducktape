# Wave Execution Plan

**Status**: Waves D-I complete (see FINAL_VERIFICATION.md for results)

**Completed Waves**:
- ✅ Wave D: HTTP/WebSocket → MCP Migration (28 agents, D1-D4 complete)
- ✅ Wave E: Token-Based Routing (1 agent complete)
- ✅ Wave F: Code Quality Scans (30 agents complete)
- ✅ Wave G: Violation Analysis (1 agent complete)
- ✅ Wave H: Parallel Cleanup (5 agents, 129 violations fixed)
- ✅ Wave I: Documentation & Misc Cleanups (6 agents complete)

For details on completed work, see:
- `FINAL_VERIFICATION.md` - Verification results and remaining issues
- `VIOLATION_ANALYSIS.md` - Code quality scan analysis
- `adgn/docs/mcp-architecture.md` - MCP architecture documentation
- Git history commits `d9072043` through `a530c8b3`

---

## Remaining Work

### Post-Commit Cleanup Tasks

Based on FINAL_VERIFICATION.md, the following issues need to be addressed:

#### 1. Ruff Violations (34 remaining)
Run with unsafe fixes enabled to resolve remaining issues:
```bash
cd adgn
uv run ruff check src/adgn/agent tests/agent --fix --unsafe-fixes
```

Common violations:
- PT011: `pytest.raises(Exception)` too broad - needs specific exception types
- F841: Unused local variables
- Other code quality issues

#### 2. Mypy Type Errors (12 errors)

**Priority fixes**:
- `src/adgn/agent/persist/sqlite.py:355,382` - ProposalStatus string conversion
- `src/adgn/agent/mcp_bridge/servers/agents.py:520` - InfrastructureRegistry.get() method
- `src/adgn/agent/mcp_bridge/servers/agents.py:730` - server_spec needs type annotation
- Other type mismatches in reducer.py, runtime.py, agent.py

#### 3. Test Infrastructure Issues

**Test failures** (66 failed, 45 errors):
- Many failures related to WebSocket/HTTP endpoint removal (expected)
- Tests need updating to use new MCP-based APIs
- Some tests import from deleted modules

**Action**: Review failing tests and either:
- Update to use MCP resources/tools instead of HTTP endpoints
- Delete if testing removed infrastructure
- Fix import errors from refactoring

#### 4. Frontend Tests

NPM tests not available (vitest dependency missing or Svelte 6 incompatibility).

**Action**:
```bash
cd adgn/src/adgn/agent/web
npm install
npm test
```

If tests fail due to Svelte 6 incompatibility, document in issue tracker.

---

## Execution Commands

### Fix Ruff + Mypy Issues
```bash
cd adgn
uv run ruff check src/adgn/agent tests/agent --fix --unsafe-fixes
uv run python -m mypy src/adgn/agent
```

### Run Tests
```bash
cd adgn
.venv/bin/pytest tests/agent -q -m "not live_llm"
```

### Frontend Tests
```bash
cd adgn/src/adgn/agent/web
npm install
npm test
```

---

## Success Criteria

### Code Quality
- ✅ Ruff clean (no linting errors)
- ✅ Mypy clean (no type errors)

### Testing
- ✅ All pytest unit/integration tests pass
- ✅ All npm frontend tests pass

### Documentation
- ✅ All new features documented
- ✅ Migration guide updated
- ✅ Architecture docs current

---

## Timeline Estimate

- Ruff/Mypy fixes: ~1 hour
- Test updates: ~2-3 hours
- Frontend tests: ~30 minutes
- **Total**: ~4 hours of focused work
