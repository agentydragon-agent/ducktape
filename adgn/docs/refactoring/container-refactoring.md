# AgentContainer Refactoring Plan

## Current Problems

### 1. God Object Antipattern
`AgentContainer` manages too many responsibilities:
- MCP infrastructure (Compositor, Client, NotificationsBuffer)
- Policy management (Engine, Hub, Reader/Approver stubs)
- Agent runtime (AgentSession, MiniCodex, ConnectionManager)
- UI integration (ServerBus, UiFacet)
- Persistence (RunPersistenceHandler)
- Actor lifecycle (Mailbox, task management)
- AsyncExitStack lifecycle management

**Stats**:
- 19 fields in dataclass
- ~10 private internal fields
- 632 lines total
- `_handle_actor_msg._StartMsg` case: 150+ lines of initialization code

### 2. Async Construction Antipattern

```python
async def build_container(...) -> AgentContainer:
    c = AgentContainer(...)  # Sync construction
    await c.start(...)       # Async initialization - BAD!
    return c
```

Problems:
- Function named "build" does async work
- Mixes construction with initialization
- Can't use the object until `start()` is called
- Easy to forget to call `start()`

### 3. Massive Initialization Method

The `_StartMsg` case in `_handle_actor_msg` is 150+ lines doing:
1. Load presets
2. Create approval engine
3. Create AgentSession & ConnectionManager
4. Create LLM client
5. Setup AsyncExitStack
6. Create & configure Compositor
7. Mount servers
8. Setup notifications
9. Setup policy gateway
10. Create & start agent
11. Attach everything

This should be broken into focused initialization functions.

## Proposed Refactoring

### Phase 1: Extract Infrastructure Components

Create focused components for each major concern:

```python
@dataclass
class MCPInfrastructure:
    """MCP compositor and client infrastructure."""
    compositor: Compositor
    client: Client  # Front-door client with policy middleware
    notification_buffer: NotificationsBuffer

@dataclass
class PolicyInfrastructure:
    """Policy evaluation and management."""
    engine: ApprovalPolicyEngine
    hub: ApprovalHub
    reader_stub: PolicyReaderStub
    approver_stub: PolicyApproverStub

@dataclass
class AgentRuntime:
    """Core agent execution runtime."""
    session: AgentSession
    agent: MiniCodex
    connection_manager: ConnectionManager
    persist_handler: RunPersistenceHandler
    model: str
    base_system: str
```

### Phase 2: Extract Initialization Functions

Break apart the 150-line initialization:

```python
async def _initialize_mcp_infrastructure(
    mcp_config: MCPConfig,
    stack: AsyncExitStack,
) -> MCPInfrastructure:
    """Create compositor, client, and notification buffer."""
    comp = Compositor("compositor", eager_open=True)
    for name, server_cfg in mcp_config.mcpServers.items():
        await comp.mount_server(name, server_cfg)

    loop_server = make_loop_server("loop")
    await comp.mount_inproc("loop", loop_server)

    notif_buffer = NotificationsBuffer(compositor=comp)
    mcp_client = Client(comp, message_handler=notif_buffer.handler)
    await stack.enter_async_context(mcp_client)

    return MCPInfrastructure(
        compositor=comp,
        client=mcp_client,
        notification_buffer=notif_buffer,
    )

async def _initialize_policy_infrastructure(
    agent_id: str,
    persistence: SQLitePersistence,
    docker_client: DockerClient,
    policy_source: str,
    mcp_client: Client,
    stack: AsyncExitStack,
) -> PolicyInfrastructure:
    """Create policy engine, hub, and server stubs."""
    engine = make_policy_engine(
        agent_id=agent_id,
        persistence=persistence,
        docker_client=docker_client,
        policy_source=policy_source,
    )
    hub = ApprovalHub()

    # Create policy servers and stubs
    reader_server = ApprovalPolicyServer(engine=engine, name=...)
    reader_client = Client(reader_server)
    await stack.enter_async_context(reader_client)
    reader_stub = PolicyReaderStub(TypedClient(reader_client))

    # Similar for approver...

    return PolicyInfrastructure(
        engine=engine,
        hub=hub,
        reader_stub=reader_stub,
        approver_stub=approver_stub,
    )

async def _initialize_agent_runtime(
    cm: ConnectionManager,
    mcp_client: Client,
    policy: PolicyInfrastructure,
    model: str,
    system: str,
    ...,
) -> AgentRuntime:
    """Create agent session, handlers, and agent."""
    sess = AgentSession(
        cm,
        approval_hub=policy.hub,
        persistence=...,
        agent_id=...,
        ui_bus=...,
        approval_engine=policy.engine,
    )

    handlers, persist_handler = build_handlers(...)
    sess.set_persist_handler(persist_handler)

    agent = await MiniCodex.create(
        model=model,
        mcp_client=mcp_client,
        system=system,
        ...,
    )

    sess.attach_agent(agent, model=model, system=system)

    return AgentRuntime(
        session=sess,
        agent=agent,
        connection_manager=cm,
        persist_handler=persist_handler,
        model=model,
        base_system=system,
    )
```

### Phase 3: Refactor AgentContainer

```python
@dataclass
class AgentContainer:
    """Lifecycle container for agent infrastructure.

    Manages startup/shutdown of MCP, policy, and agent components.
    Uses actor pattern for concurrent operations.
    """

    # Configuration (immutable after construction)
    agent_id: str
    persistence: SQLitePersistence
    model: str
    client_factory: Callable[[str], OpenAIModelProto]
    docker_client: DockerClient
    with_ui: bool = True
    system_override: str | None = None
    initial_policy: str | None = None
    runtime_ephemeral: bool = False

    # Infrastructure components (initialized on start)
    mcp: MCPInfrastructure | None = None
    policy: PolicyInfrastructure | None = None
    runtime: AgentRuntime | None = None
    ui: UiFacet | None = None

    # Actor internals
    _mailbox: asyncio.Queue = field(default_factory=asyncio.Queue, init=False)
    _actor_task: asyncio.Task | None = field(default=None, init=False)
    _ready: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _stack: AsyncExitStack = field(default_factory=AsyncExitStack, init=False)

    # REMOVE: All the individual _policy_reader, _compositor, _cm, etc fields
    # They're now organized into the infrastructure components above
```

### Phase 4: Fix Build Pattern

```python
# BEFORE:
async def build_container(...) -> AgentContainer:
    c = AgentContainer(...)
    await c.start(...)  # async in "build"!
    return c

# AFTER:
def create_container(...) -> AgentContainer:
    """Create an uninitialized container (sync)."""
    return AgentContainer(...)

async def initialize_container(container: AgentContainer, mcp_config: MCPConfig) -> None:
    """Initialize the container (async)."""
    await container.start(mcp_config=mcp_config)

# Or combined:
async def create_and_start_container(...) -> AgentContainer:
    """Create and fully initialize a container (async)."""
    c = create_container(...)
    await initialize_container(c, mcp_config)
    return c
```

### Phase 5: Consider Actor Pattern Necessity

**Question**: Is the actor pattern really needed here?

**Current usage**:
- Serializes operations like start, reconfigure, close
- Provides message-based async coordination

**Alternative**: Direct async methods with locks:
```python
class AgentContainer:
    _init_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def start(self, mcp_config: MCPConfig) -> None:
        async with self._init_lock:
            if self.mcp is not None:
                raise RuntimeError("Already started")
            # Initialization...

    async def reconfigure(self, ...) -> None:
        async with self._init_lock:
            # Reconfiguration...
```

**Recommendation**: If actor pattern stays, keep it focused on lifecycle coordination only. Move business logic out of `_handle_actor_msg`.

## Implementation Steps

1. **Extract infrastructure dataclasses** (MCPInfrastructure, PolicyInfrastructure, AgentRuntime)
2. **Extract initialization functions** (_initialize_mcp_infrastructure, etc.)
3. **Refactor AgentContainer** to use infrastructure components
4. **Update _handle_actor_msg** to call initialization functions
5. **Fix build pattern** - rename or split build_container
6. **Add property accessors** for backward compatibility:
   ```python
   @property
   def compositor_client(self) -> Client:
       if self.mcp is None:
           raise RuntimeError("Not initialized")
       return self.mcp.client
   ```
7. **Update tests** to use new API

## Benefits

- **Separation of concerns**: Each component has one responsibility
- **Testability**: Can test MCPInfrastructure independently of PolicyInfrastructure
- **Readability**: Clear structure, no 500-line methods
- **Maintainability**: Easy to find and modify specific functionality
- **Type safety**: Infrastructure components are well-typed
- **Reusability**: Components can be used outside AgentContainer if needed
