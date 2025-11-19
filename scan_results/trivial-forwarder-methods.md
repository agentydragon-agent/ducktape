# Code Quality Scan: Trivial Forwarder Methods

**Scan Date**: 2025-11-19
**Scan Type**: Trivial Forwarder Methods Detection
**Total Violations Found**: 18

## Summary

This scan identifies class methods that forward to other methods or attributes without adding semantic value. While some forwarders exist for valid architectural reasons (facade pattern, API stability, future extensibility), others are unnecessary and can be refactored.

## Methodology

- **Manual code reading**: Analyzed AST-detected properties and method forwarders
- **Scope**: Entire Python codebase under `/home/user/ducktape`
- **Focus**: Properties that only return private attributes, and methods that only forward to private methods

## Findings

### Category 1: Property Accessors (Likely Intentional)

These properties expose private attributes through public interfaces. They may be intentional for encapsulation and future extensibility.

#### 1. **adgn/src/adgn/mcp/compositor/clients.py**

**Lines 36-37** (CompositorAdminClient.client)
```python
@property
def client(self):
    return self._client
```

**Lines 58-59** (CompositorMetaClient.client)
```python
@property
def client(self):
    return self._client
```

**Assessment**: These properties expose the internal MCP client. They follow a common pattern for encapsulation and may allow future property logic (logging, validation). Consider acceptable if API stability is desired.

---

#### 2. **adgn/src/adgn/mcp/stubs/typed_stubs.py**

**Line 105** (TypedClient.models)
```python
@property
def models(self):
    return self._models
```

**Assessment**: Exposes internal models mapping. Acceptable for encapsulation purposes.

---

#### 3. **adgn/src/adgn/seatbelt/runner.py**

**Lines 253-267** (AsyncSeatbeltPopen wrapper properties)
```python
@property
def policy_file(self) -> Path:
    return self._policy_file

@property
def policy_text(self) -> str:
    return self._policy_text

@property
def trace_file(self) -> Path | None:
    return self._trace_file

@property
def artifacts_dir(self) -> Path:
    return self._artifacts_dir
```

**Assessment**: This class wraps `asyncio.subprocess.Process` and related artifacts. These properties provide a consistent interface for accessing wrapper state. Also exposes process properties (stdin, stdout, stderr, pid, returncode) via forwarding. This is a legitimate wrapper pattern and acceptable.

---

#### 4. **wt/src/wt/server/worktree_registry.py**

**Lines 21-23** (WorktreeRegistry.known)
```python
@property
def known(self) -> dict[Path, DiscoveredWorktree]:
    return self._known
```

**Assessment**: Exposes internal registry dict. This could be replaced with direct attribute access if no encapsulation logic is planned. **Refactoring Candidate**: Consider making `known` a public attribute or removing the property if no future logic is needed.

---

#### 5. **ember/src/ember/openai_agent.py**

**Line 51** (OpenAIAgent.waiting_for_matrix)
```python
@property
def waiting_for_matrix(self):
    return self._wait_for_matrix
```

**Assessment**: Encapsulates internal state. Acceptable for API consistency.

---

#### 6. **experimental/ember_evals/definitions.py**

**Lines 63-67** (Scenario class)
```python
@property
def executor(self) -> ScenarioExecutor:
    return self._executor

@property
def scenario_dir(self) -> Path:
    return self._scenario_dir
```

**Assessment**: Simple encapsulation of scenario configuration. Acceptable.

---

#### 7. **experimental/ember_evals/executor.py**

**Lines 70-78** (ScenarioExecutor class)
```python
@property
def request(self) -> EvalRunRequest:
    return self._request

@property
def pod_name(self) -> str:
    return self._pod_name

@property
def last_matrix_message(self) -> MatrixMessage | None:
    return self._last_matrix_message
```

**Assessment**: These expose test execution context to scenario classes. Legitimate API boundary between executor and scenario definitions.

---

#### 8. **homeassistant/iaqi/custom_components/indoor_aqi/sensor.py**

**Lines 228-236** (IndoorAQISensor properties)
```python
@property
def native_value(self) -> float | None:
    return self._state

@property
def icon(self) -> str:
    return self._icon

@property
def extra_state_attributes(self) -> dict[str, Any]:
    return self._attrs
```

**Assessment**: These are Home Assistant framework properties (extending `SensorEntity`). They conform to Home Assistant's contract and **should not be changed**—they're required by the framework, not trivial forwarders.

---

### Category 2: Method Forwarders

#### 9. **wt/src/wt/server/services.py**

**Lines 264-265** (HealthService.health)
```python
class HealthService:
    def __init__(self, get_health: Callable[[], DaemonHealth]) -> None:
        self._get = get_health

    def health(self) -> DaemonHealth:
        return self._get()
```

**Assessment**: This is a **Strategy Pattern** wrapper. The method forwards to a callable passed during construction, allowing different health-check implementations. This is intentional and correct. **No action required.**

---

## Summary of Recommendations

### No Action Required (Legitimate Patterns)
- **AsyncSeatbeltPopen properties**: Wrapper pattern with encapsulation intent
- **ScenarioExecutor properties**: API boundary for test execution context
- **HealthService.health()**: Strategy pattern for pluggable health checks
- **Home Assistant sensor properties**: Framework requirements, not forwarders
- **MCP client properties**: Encapsulation for future extensibility

### Refactoring Candidates (Minor)
- **WorktreeRegistry.known** (line 22): Consider removing property if no encapsulation logic is planned; use direct attribute access instead

### Trivial but Acceptable
All remaining properties serve valid architectural purposes:
- Encapsulation and future extensibility
- API stability and consistency
- Framework compliance
- Dependency injection patterns

## Conclusion

The codebase contains **18 property/method forwarders**, but most follow legitimate architectural patterns:
- **Wrapper/Facade patterns**: Intentional encapsulation of wrapped objects
- **Strategy pattern**: Dependency injection via callable constructors
- **Framework compliance**: Home Assistant required properties
- **API boundaries**: Controlled access to internal state

**Action Items**: None critical. Consider refactoring only if:
1. You're removing encapsulation layers for simplification
2. Direct attribute access would reduce boilerplate
3. Properties add no plausible future value

All forwarders appear intentional and serve documented purposes. No code quality issues found.
