package centralsampler

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
)

const maxCodeModeFrame = 64 * 1024 * 1024

type CodeMode struct {
	host         *Host
	store        *Store
	owner        Owner
	executor     *Executor
	sessionID    string
	nextID       int64
	mu           sync.Mutex
	responses    map[int64]chan codeReply
	initials     map[int64]chan codeReply
	delegates    map[int64]struct{}
	cancelled    map[int64]struct{}
	delegateWG   sync.WaitGroup
	writeGate    chan struct{}
	error        error
	readerDone   chan struct{}
	readerCancel context.CancelFunc
	closeOnce    sync.Once
	stopErr      error
	stopped      bool
}

func NewCodeMode(ctx context.Context, host *Host, store *Store, owner Owner, executor *Executor) (*CodeMode, error) {
	return NewCodeModeWithHandshake(ctx, ctx, host, store, owner, executor)
}

func NewCodeModeWithHandshake(lifetimeCtx, handshakeCtx context.Context, host *Host, store *Store, owner Owner, executor *Executor) (*CodeMode, error) {
	runtime := &CodeMode{
		host: host, store: store, owner: owner, executor: executor, sessionID: uuid.NewString(),
		responses: map[int64]chan codeReply{}, initials: map[int64]chan codeReply{}, delegates: map[int64]struct{}{},
		cancelled: map[int64]struct{}{}, readerDone: make(chan struct{}), writeGate: make(chan struct{}, 1),
	}
	if err := runtime.send(handshakeCtx, codeHello{Type: "connection/hello", SupportedVersions: []int{1}, RequiredCapabilities: []string{}, OptionalCapabilities: []string{}}); err != nil {
		return nil, errors.Join(err, host.Close())
	}
	frame, err := runtime.receive(handshakeCtx)
	if err != nil {
		return nil, errors.Join(err, host.Close())
	}
	if frame.Type != codeReady || frame.SelectedVersion != 1 || frame.Capabilities == nil || len(frame.Capabilities) != 0 {
		return nil, errors.Join(fmt.Errorf("unexpected code-mode handshake: %s", canonicalJSON(frame)), host.Close())
	}
	pumpCtx, cancel := context.WithCancel(lifetimeCtx)
	runtime.readerCancel = cancel
	go runtime.pump(pumpCtx)
	_, err = runtime.request(handshakeCtx, codeSessionOperation{Method: "session/open", SessionID: runtime.sessionID}, false)
	if err != nil {
		cancel()
		<-runtime.readerDone
		return nil, errors.Join(err, host.Close())
	}
	return runtime, nil
}

func (r *CodeMode) send(ctx context.Context, value any) error {
	object, err := protocolObject(value)
	if err != nil {
		return err
	}
	operationID := r.sessionID + ":" + fmt.Sprint(object["id"])
	if object["id"] == nil {
		operationID = r.sessionID + ":connection"
	}
	if err := r.store.ProtocolEvent(ctx, r.owner, operationID, "javascript", "send", object); err != nil {
		return err
	}
	payload, err := json.Marshal(value)
	if err != nil {
		return err
	}
	if len(payload) > maxCodeModeFrame {
		return errors.New("upstream code-mode frame exceeds protocol limit")
	}
	select {
	case r.writeGate <- struct{}{}:
	case <-ctx.Done():
		return ctx.Err()
	}
	defer func() { <-r.writeGate }()
	var header [4]byte
	binary.LittleEndian.PutUint32(header[:], uint32(len(payload)))
	return writeFrameWithContext(ctx, r.host, header[:], payload)
}

func writeFrameWithContext(ctx context.Context, host *Host, header, payload []byte) error {
	stopWriteCancellation := make(chan struct{})
	writeCancellationDone := make(chan struct{})
	if ctx.Done() != nil {
		go func() {
			defer close(writeCancellationDone)
			select {
			case <-ctx.Done():
				_ = host.stdin.Close()
				_ = host.Kill()
			case <-stopWriteCancellation:
			}
		}()
	}
	writeErr := writeFrame(host.stdin, header, payload)
	close(stopWriteCancellation)
	if ctx.Done() != nil {
		<-writeCancellationDone
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	return writeErr
}

func writeFrame(writer io.Writer, header, payload []byte) error {
	for _, part := range [][]byte{header, payload} {
		for len(part) > 0 {
			written, err := writer.Write(part)
			if err != nil {
				return err
			}
			if written == 0 {
				return io.ErrShortWrite
			}
			part = part[written:]
		}
	}
	return nil
}

func (r *CodeMode) receive(ctx context.Context) (*codeFrame, error) {
	type frameResult struct {
		frame *codeFrame
		raw   json.RawMessage
		err   error
	}
	ch := make(chan frameResult, 1)
	readDone := make(chan struct{})
	go func() {
		defer close(readDone)
		var header [4]byte
		if _, err := io.ReadFull(r.host.stdout, header[:]); err != nil {
			ch <- frameResult{err: err}
			return
		}
		length := binary.LittleEndian.Uint32(header[:])
		if length > maxCodeModeFrame {
			ch <- frameResult{err: errors.New("upstream code-mode frame exceeds protocol limit")}
			return
		}
		payload := make([]byte, int(length))
		if _, err := io.ReadFull(r.host.stdout, payload); err != nil {
			ch <- frameResult{err: err}
			return
		}
		var frame codeFrame
		if err := decodeProtocolObject(payload, &frame); err != nil {
			ch <- frameResult{err: err}
			return
		}
		ch <- frameResult{frame: &frame, raw: payload}
	}()
	select {
	case <-ctx.Done():
		_ = r.host.stdout.Close()
		<-readDone
		return nil, ctx.Err()
	case result := <-ch:
		<-readDone
		if result.err != nil {
			return nil, result.err
		}
		operationID := r.sessionID + ":connection"
		if result.frame.ID != nil {
			operationID = fmt.Sprintf("%s:%d", r.sessionID, *result.frame.ID)
		}
		object, err := protocolObject(result.raw)
		if err != nil {
			return nil, err
		}
		if err := r.store.ProtocolEvent(ctx, r.owner, operationID, "javascript", "receive", object); err != nil {
			return nil, err
		}
		return result.frame, nil
	}
}

func (r *CodeMode) pump(ctx context.Context) {
	defer close(r.readerDone)
	for {
		frame, err := r.receive(ctx)
		if err != nil {
			if ctx.Err() == nil {
				r.fail(err)
			}
			return
		}
		switch frame.Type {
		case codeDelegateRequest:
			if frame.ID == nil {
				r.fail(errors.New("code-mode delegate request has an invalid ID"))
				return
			}
			delegateID := *frame.ID
			r.mu.Lock()
			r.delegates[delegateID] = struct{}{}
			r.mu.Unlock()
			r.delegateWG.Add(1)
			go func(frame *codeFrame, id int64) {
				defer r.delegateWG.Done()
				r.delegate(ctx, id, frame)
			}(frame, delegateID)
		case codeDelegateCancel:
			if frame.ID != nil {
				delegateID := *frame.ID
				r.mu.Lock()
				r.cancelled[delegateID] = struct{}{}
				r.mu.Unlock()
			}
		case codeResponse, codeInitialResponse:
			if frame.ID == nil {
				r.fail(errors.New("code-mode response has an invalid ID"))
				return
			}
			id := *frame.ID
			r.mu.Lock()
			channel := r.responses[id]
			if frame.Type == codeInitialResponse {
				channel = r.initials[id]
			}
			r.mu.Unlock()
			if channel == nil {
				r.fail(fmt.Errorf("code-mode response references unknown request %d", id))
				return
			}
			select {
			case channel <- codeReply{Result: frame.Result}:
			default:
				r.fail(fmt.Errorf("duplicate code-mode response for request %d", id))
				return
			}
		case codeCellClosed:
		default:
			r.fail(fmt.Errorf("unexpected code-mode frame: %s", canonicalJSON(frame)))
			return
		}
	}
}

func (r *CodeMode) delegate(ctx context.Context, id int64, frame *codeFrame) {
	defer func() {
		r.mu.Lock()
		delete(r.delegates, id)
		r.mu.Unlock()
	}()
	if frame.Request == nil || frame.Request.Type != "tool/invoke" {
		r.fail(errors.New("code-mode only supports tool/invoke delegates"))
		return
	}
	invocation := frame.Request.Invocation
	if invocation.ToolName.Name == "" || invocation.ToolName.Namespace != nil {
		r.fail(errors.New("code-mode tool invocation has no supported tool name"))
		return
	}
	input := invocation.Input
	requestJournal, err := protocolObject(invocation)
	if err != nil {
		r.fail(err)
		return
	}
	requestJournal["kind"] = "tool"
	if invocation.CellID != "" {
		requestJournal["cell_id"] = r.cellHandle(invocation.CellID)
	}
	intent, err := r.store.RecordNested(ctx, r.owner, requestJournal)
	if err != nil {
		r.fail(err)
		return
	}
	result, err := r.executor.Invoke(ctx, invocation.ToolName.Name, input)
	if err != nil {
		r.fail(err)
		return
	}
	resultEvidence, err := protocolObject(result)
	if err != nil {
		r.fail(err)
		return
	}
	if err := r.store.FinishNested(ctx, r.owner, intent, resultEvidence); err != nil {
		r.fail(err)
		return
	}
	r.mu.Lock()
	_, cancelled := r.cancelled[id]
	r.mu.Unlock()
	if cancelled {
		return
	}
	encoded, err := json.Marshal(result)
	if err != nil {
		r.fail(err)
		return
	}
	if err := r.send(ctx, codeDelegateResponse{Type: "delegate/response", ID: id, Result: codeDelegateResult{Status: "ok", Value: codeToolResult{Type: "tool/result", Result: encoded}}}); err != nil {
		r.fail(err)
	}
}

func (r *CodeMode) fail(err error) {
	r.mu.Lock()
	if r.error == nil {
		r.error = err
	}
	r.notifyPendingLocked(r.error)
	r.mu.Unlock()
}

func (r *CodeMode) notifyPendingLocked(err error) {
	reply := codeReply{Err: err}
	for _, channel := range r.responses {
		select {
		case channel <- reply:
		default:
		}
	}
	for _, channel := range r.initials {
		select {
		case channel <- reply:
		default:
		}
	}
}

func (r *CodeMode) Err() error {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.error
}

func (r *CodeMode) hasDelegates() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.delegates) > 0
}

func (r *CodeMode) request(ctx context.Context, request codeOperation, execute bool) (json.RawMessage, error) {
	r.mu.Lock()
	if r.stopped {
		r.mu.Unlock()
		return nil, errors.New("code-mode session is stopped")
	}
	if r.error != nil && request.method() != "session/terminate" {
		err := r.error
		r.mu.Unlock()
		return nil, err
	}
	r.nextID++
	id := r.nextID
	response := make(chan codeReply, 1)
	r.responses[id] = response
	var initial chan codeReply
	if execute {
		initial = make(chan codeReply, 1)
		r.initials[id] = initial
	}
	r.mu.Unlock()
	defer func() {
		r.mu.Lock()
		delete(r.responses, id)
		delete(r.initials, id)
		r.mu.Unlock()
	}()
	if err := r.send(ctx, codeOperationFrame{Type: "operation/request", ID: id, Request: request}); err != nil {
		return nil, err
	}
	resultFrame, err := waitFrame(ctx, response)
	if err != nil {
		return nil, err
	}
	value, err := validateCodeModeResult(resultFrame)
	if err != nil {
		return nil, err
	}
	if initial == nil {
		return value, nil
	}
	var started codeHostResponse
	if err := decodeProtocolObject(value, &started); err != nil {
		return nil, err
	}
	cellID := started.CellID
	if started.Type != "execution/started" || cellID == "" {
		return nil, errors.New("code-mode execute response has no cellId")
	}
	if err := r.store.CellResult(ctx, r.owner, r.cellHandle(cellID), "live"); err != nil {
		return nil, err
	}
	initialFrame, err := waitFrame(ctx, initial)
	if err != nil {
		return nil, err
	}
	return validateCodeModeResult(initialFrame)
}

func waitFrame(ctx context.Context, channel <-chan codeReply) (*codeWireResult, error) {
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case reply := <-channel:
		if reply.Err != nil {
			return nil, reply.Err
		}
		if reply.Result == nil {
			return nil, errors.New("code-mode frame has no result object")
		}
		return reply.Result, nil
	}
}

func validateCodeModeResult(frame *codeWireResult) (json.RawMessage, error) {
	if frame.Status != "ok" {
		return nil, fmt.Errorf("code-mode operation failed: %s", frame.Message)
	}
	var object struct{}
	if err := decodeProtocolObject(frame.Value, &object); err != nil {
		return nil, err
	}
	return frame.Value, nil
}

func (r *CodeMode) Execute(ctx context.Context, call ResponsesToolCall) ([]ResponsesContentPart, error) {
	request, execute, err := r.prepareCall(ctx, call)
	if err != nil {
		return nil, &KnownFailureError{Evidence: map[string]any{"reason": err.Error(), "call": call, "dispatched": false}}
	}
	value, err := r.request(ctx, request, execute)
	if err != nil {
		return nil, err
	}
	var observation codeObservation
	if !execute {
		observation, err = decodeWaitObservation(value)
	} else {
		err = decodeProtocolObject(value, &observation)
	}
	if err != nil {
		return nil, err
	}
	return r.observe(ctx, observation)
}

func (r *CodeMode) prepareCall(ctx context.Context, call ResponsesToolCall) (codeOperation, bool, error) {
	name := call.Name
	if name == "wait" {
		input := call.Input
		var arguments waitInput
		if err := decodeToolInput([]byte(input), &arguments); err != nil {
			return nil, false, err
		}
		cellID := arguments.CellID
		if cellID == "" {
			return nil, false, errors.New("wait requires a string cell_id")
		}
		terminate := arguments.Terminate
		state, err := r.store.ExecutionState(ctx, r.owner)
		if err != nil {
			return nil, false, err
		}
		known := false
		for _, cell := range state.Cells {
			if cell.ID == cellID && cell.Status == "live" {
				known = true
				break
			}
		}
		if !known {
			return nil, false, errors.New("wait requires a known live cell_id; process session_id is not accepted")
		}
		nativeID, err := r.nativeCell(cellID)
		if err != nil {
			return nil, false, err
		}
		if terminate {
			return codeTerminateOperation{codeSessionOperation: codeSessionOperation{Method: "session/terminate", SessionID: r.sessionID}, CellID: nativeID}, false, nil
		}
		yieldMS, err := toolYieldTime(arguments.YieldTimeMS, 1000)
		if err != nil {
			return nil, false, err
		}
		return codeWaitOperation{codeSessionOperation: codeSessionOperation{Method: "session/wait", SessionID: r.sessionID}, Request: codeWaitRequest{CellID: nativeID, YieldTimeMS: yieldMS}}, false, nil
	}
	if name != "exec" {
		return nil, false, fmt.Errorf("unsupported model tool %q", name)
	}
	source := call.Input
	yieldMS := 60000
	if strings.HasPrefix(source, "// @exec:") {
		pragma, rest, found := strings.Cut(source, "\n")
		if !found {
			rest = ""
		}
		var arguments execPragma
		if err := decodeToolInput([]byte(strings.TrimSpace(strings.TrimPrefix(pragma, "// @exec:"))), &arguments); err != nil {
			return nil, false, errors.New("exec pragma must contain a JSON object")
		}
		var err error
		yieldMS, err = toolYieldTime(arguments.YieldTimeMS, 60000)
		if err != nil {
			return nil, false, err
		}
		source = rest
	}
	definitions, err := json.Marshal(toolDefinitions())
	if err != nil {
		return nil, false, err
	}
	callID := call.CallID
	return codeExecuteOperation{codeSessionOperation: codeSessionOperation{Method: "session/execute", SessionID: r.sessionID}, Request: codeExecuteRequest{ToolCallID: callID, Source: source, EnabledTools: definitions, YieldTimeMS: yieldMS, MaxOutputTokens: 10000}}, true, nil
}

func (r *CodeMode) observe(ctx context.Context, observation codeObservation) ([]ResponsesContentPart, error) {
	value := observation.Cell
	status := "completed"
	switch observation.Kind {
	case codeYielded:
		status = "live"
	case codeTerminated:
		status = "terminated"
	case codeResult:
	default:
		return nil, fmt.Errorf("unsupported cell observation %q", observation.Kind)
	}
	if err := r.store.CellResult(ctx, r.owner, r.cellHandle(value.CellID), status); err != nil {
		return nil, err
	}
	items := make([]ResponsesContentPart, 0, len(value.ContentItems)+1)
	for _, raw := range value.ContentItems {
		var item ResponsesContentPart
		if err := json.Unmarshal(raw, &item); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	if observation.Kind == codeYielded {
		items = append(items, ResponsesContentPart{Type: "input_text", Text: "Script running with cell ID " + r.cellHandle(value.CellID) + ". Use wait to continue."})
	} else if observation.Kind == codeTerminated {
		items = append(items, ResponsesContentPart{Type: "input_text", Text: "Cell terminated. Partial effects may have occurred."})
	} else if value.ErrorText != nil && *value.ErrorText != "" {
		items = append(items, ResponsesContentPart{Type: "input_text", Text: *value.ErrorText})
	}
	return items, nil
}

func (r *CodeMode) Interrupt(ctx context.Context) (map[string]any, error) {
	state, err := r.store.ExecutionState(ctx, r.owner)
	if err != nil {
		return nil, err
	}
	outcomes := map[string]any{}
	for _, cell := range state.Cells {
		if !strings.HasPrefix(cell.ID, r.sessionID+":") || cell.Status != "live" {
			continue
		}
		nativeID, err := r.nativeCell(cell.ID)
		if err != nil {
			outcomes[cell.ID] = map[string]any{"error": err.Error()}
			continue
		}
		requestCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		value, requestErr := r.request(requestCtx, codeTerminateOperation{codeSessionOperation: codeSessionOperation{Method: "session/terminate", SessionID: r.sessionID}, CellID: nativeID}, false)
		cancel()
		if requestErr != nil {
			outcomes[cell.ID] = map[string]any{"error": requestErr.Error()}
			continue
		}
		observation, err := decodeWaitObservation(value)
		if err != nil {
			outcomes[cell.ID] = map[string]any{"error": err.Error()}
			continue
		}
		if _, err := r.observe(ctx, observation); err != nil {
			outcomes[cell.ID] = map[string]any{"error": err.Error()}
		} else {
			outcomes[cell.ID] = map[string]any{"stopped": observation.Kind != codeYielded}
		}
	}
	return outcomes, nil
}

func (r *CodeMode) Stop(ctx context.Context) error {
	r.closeOnce.Do(func() {
		r.mu.Lock()
		r.stopped = true
		stopErr := r.error
		if stopErr == nil {
			stopErr = errors.New("code-mode session stopped")
		}
		r.notifyPendingLocked(stopErr)
		r.mu.Unlock()
		if r.readerCancel != nil {
			r.readerCancel()
			<-r.readerDone
		}
		hostErr := r.host.Close()
		// The reader is the only producer of delegateWG.Add, so joining it first makes Wait
		// safe. Delegates use the reader context; cancellation above stops their executor
		// calls before the caller releases the lease.
		r.delegateWG.Wait()
		result := errors.Join(hostErr, ctx.Err())
		r.mu.Lock()
		r.stopErr = result
		r.mu.Unlock()
	})
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.stopErr
}

func (r *CodeMode) cellHandle(nativeID string) string { return r.sessionID + ":" + nativeID }

func (r *CodeMode) nativeCell(handle string) (string, error) {
	prefix := r.sessionID + ":"
	if !strings.HasPrefix(handle, prefix) {
		return "", errors.New("cell handle belongs to another JavaScript host")
	}
	return strings.TrimPrefix(handle, prefix), nil
}
