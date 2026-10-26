# Codex executor isolation

Runner supports local Codex tools and an isolated WebSocket `codex exec-server`. All Codex Sessions
on a Runner share one app-server and, in isolated mode, one executor. Runner sets
`CODEX_EXEC_SERVER_URL` before starting the app-server; an executor failure never enables local
execution. Claude continues to execute in its own harness process.

The executor is a resource boundary within the same Sandbox principal. It shares workspace, home,
temporary files and native state paths with the app-server. It is not an authorization boundary
between Sessions or a safe place for another principal's credentials.

## Pods

The template puts the companion and `exec-server` in a separate container on the same tools image.
Kubernetes `resources` supplies its memory and CPU limits; kubelet restarts the container. Its PID
namespace must be private (`shareProcessNamespace: false`), and the companion must be PID 1.
Both containers mount the same state, workspace, home, temporary directory, runner binary disk,
proxy trust bundle and kubeconfig. Projected workload tokens remain confined to the egress sidecar.

Runner holds a Unix connection to the companion through an `emptyDir`. Claiming it starts
`exec-server`; EOF, a fence request, termination, or executor exit ends that whole container
generation. Exiting PID 1 lets the runtime kill detached descendants as well as the process group.
An idle successor's fresh generation ID proves cleanup completed. A socket close alone does not.
The companion also reaps orphaned children while running. Its Kubernetes liveness probe checks the
control socket, including while waiting for Runner to claim it. Pod OOM evidence remains in
`status.containerStatuses[].lastState.terminated` and `restartCount`; an ownership disconnect alone
does not establish that the container was OOM-killed.

The common Runner configuration selects this mode with `executor.kind: "container"`, `url`,
and `socket`. The endpoint
is loopback-only; no Service, inbound network rule, Kubernetes credentials or cgroup privileges are
needed by Runner. The template owns the endpoint and socket paths used on both sides.

## VMs

The template's optional `vm_resources.executor` budget supplies `executor.kind: "cgroup"` in the
common Runner configuration. Runner prepares
`workloads` and `executors` as sibling delegated cgroup subtrees, before opening Session stores.
The harness aggregate and executor aggregate have independent limits; their configured memory caps
must fit together below the service's memory high watermark. The service's maximum leaves the
configured OS reserve below guest RAM. Each native leaf disables swap and enables group OOM killing;
the harness aggregate permits individual leaf failures.

Runner supervises `exec-server` using the same inherited state-owner descriptor and parent-liveness
pipe as a harness. The supervisor stays outside the executor cgroup. Parent death or server exit
kills the entire leaf, including descendants that changed process groups, before releasing state
ownership. Runner restarts the executor independently of the app-server. The guest remains responsible
for root paths, agent UID/GID and block devices; templates supply resource policy.

## Startup, loss and suspend

1. Runner acquires state ownership and fences previous native work. In Pods it waits for an idle
   companion generation before opening Session stores. In VMs it clears old delegated groups.
2. The first Codex startup starts the executor restart loop and waits for a bounded RPC probe.
   The probe initializes a WebSocket session and reads `environment/status`. The app-server then
   starts with the configured executor URL.
3. Runner probes RPC progress every five seconds with a three-second deadline. Exit or failed
   probes fence that generation and retry startup with exponential backoff capped at ten seconds.
   Pod cleanup also waits for kubelet to restart the companion. Commands are never replayed by Runner.
4. Quiesce halts Sessions, stops harnesses, fences the executor and only then seals journals.
   Ordinary Runner shutdown follows the same cleanup before releasing state ownership. Failure to
   prove executor cleanup prevents sealing and starting a successor executor.

No Sandbox Controller lifecycle API changes are required: its existing quiesce/seal fence covers
executor cleanup. A replacement Runner performs the startup fence even after an ungraceful exit.
The bounded cleanup wait can fail during container restart backoff; that is a failed fence, not
permission to proceed. A later Runner startup can retry once kubelet has produced an idle companion.

## Scope in Codex 0.162.1

The remote environment covers the shell/filesystem operations Codex routes to its exec-server.
Codex can reconnect after a transient WebSocket loss while the server retains its session registry.
A restarted server loses that registry and running commands; an interrupted tool can return an
error with uncertain side effects. Later tool calls can use the new server. Runner neither retries
the command nor treats an executor exit as an app-server exit.

Code-mode workers and MCP helpers remain children of the app-server in this release and consume
the harness budget. Work requested from a separate daemon, such as a system Nix daemon, consumes
that daemon's cgroup rather than the caller's. An RPC probe detects an unresponsive dispatcher;
it cannot establish progress of every individual command. Host OOM, node eviction and a breached
outer service/container limit can still stop Runner itself.

Central hosting of the Codex app-server with Sandbox executors remains future work. Local tools
and Sandbox-hosted app-server with isolated tools remain explicit transitional operating modes.
