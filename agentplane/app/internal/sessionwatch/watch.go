// Package sessionwatch shares one Dispatcher inventory stream across an App replica's browsers.
// The cache is disposable; the Dispatcher remains the authority on Session membership.
package sessionwatch

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"sort"
	"sync"
	"time"

	apppb "github.com/agentydragon/ducktape/agentplane/app/appservicepb"
	dispatcherpb "github.com/agentydragon/ducktape/agentplane/session_dispatcher/dispatcher/api/session/session_dispatcherpb"
	"github.com/google/uuid"
	gateway "github.com/grpc-ecosystem/grpc-gateway/v2/runtime"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
)

type (
	ThreadOpener interface {
		OpenThread(context.Context, uuid.UUID) error
	}
	Client interface {
		WatchSessions(context.Context, *dispatcherpb.WatchSessionsRequest, ...grpc.CallOption) (grpc.ServerStreamingClient[dispatcherpb.WatchSessionsResponse], error)
	}
)

type (
	entry struct {
		session  *dispatcherpb.Session
		revision uint64
	}
	Watch struct {
		client                 Client
		threads                ThreadOpener
		mu                     sync.Mutex
		sessions               map[string]entry
		revision               uint64
		initialized, connected bool
		changed                chan struct{}
	}
)

func New(client Client, threads ThreadOpener) *Watch {
	return &Watch{client: client, threads: threads, sessions: map[string]entry{}, changed: make(chan struct{})}
}
func (w *Watch) notifyLocked() { close(w.changed); w.changed = make(chan struct{}) }
func (w *Watch) disconnected() {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.connected = false
	w.notifyLocked()
}

// Run resumes only after an upsert and its App metadata have both been accepted locally.
// A fresh replica starts with an empty token; no ListSessions read or persistent mirror is used.
func (w *Watch) Run(ctx context.Context) error {
	token := ""
	for ctx.Err() == nil {
		err := w.follow(ctx, &token)
		w.disconnected()
		if ctx.Err() != nil {
			break
		}
		if err == nil {
			continue
		} // Planned Dispatcher watch lease renewal.
		if status.Code(err) == codes.InvalidArgument {
			token = ""
		}
		slog.WarnContext(ctx, "Dispatcher Session inventory disconnected; reconnecting", "error", err)
		timer := time.NewTimer(time.Second)
		select {
		case <-ctx.Done():
			timer.Stop()
		case <-timer.C:
		}
	}
	return ctx.Err()
}

func (w *Watch) follow(ctx context.Context, token *string) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	stream, err := w.client.WatchSessions(ctx, &dispatcherpb.WatchSessionsRequest{ResumeToken: *token})
	if err != nil {
		return err
	}
	for {
		frame, err := stream.Recv()
		if err != nil {
			return err
		}
		switch item := frame.GetFrame().(type) {
		case *dispatcherpb.WatchSessionsResponse_Session:
			id, err := uuid.Parse(item.Session.GetSessionId())
			if err != nil || id.String() != item.Session.GetSessionId() {
				return errors.New("Dispatcher returned a noncanonical Session UUID")
			}
			if err := w.threads.OpenThread(ctx, id); err != nil {
				return err
			}
			w.mu.Lock()
			w.revision++
			w.sessions[id.String()] = entry{session: item.Session, revision: w.revision}
			w.notifyLocked()
			w.mu.Unlock()
		case *dispatcherpb.WatchSessionsResponse_CaughtUp:
			w.mu.Lock()
			w.initialized = true
			w.connected = true
			w.notifyLocked()
			w.mu.Unlock()
		case *dispatcherpb.WatchSessionsResponse_ReconnectRequired:
			return nil
		default:
			return errors.New("Dispatcher returned an empty Session inventory frame")
		}
		*token = frame.GetResumeToken()
	}
}

// read captures the notification channel under the same lock as the bounded read. Slow readers
// coalesce updates to current records, without blocking the upstream or accumulating a queue.
func (w *Watch) read(after uint64) (*apppb.WatchSessionInventoryResponse, uint64, <-chan struct{}) {
	w.mu.Lock()
	defer w.mu.Unlock()
	entries := make([]entry, 0)
	for _, item := range w.sessions {
		if item.revision > after {
			entries = append(entries, item)
		}
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].revision < entries[j].revision })
	response := &apppb.WatchSessionInventoryResponse{CaughtUp: w.initialized && len(entries) <= 100, UpdatesConnected: w.connected}
	if len(entries) > 100 {
		entries = entries[:100]
	}
	for _, item := range entries {
		response.Sessions = append(response.Sessions, item.session)
		after = item.revision
	}
	return response, after, w.changed
}

// Handler uses grpc-gateway's standard stream encoder for the AppService RPC. The caller mounts
// it behind operator authentication and passes a context cancelled on logout, expiry and drain.
func (w *Watch) Handler() http.Handler {
	mux := gateway.NewServeMux()
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set("Cache-Control", "no-store")
		writer.Header().Set("X-Accel-Buffering", "no")
		ctx := gateway.NewServerMetadataContext(request.Context(), gateway.ServerMetadata{})
		_, marshaler := gateway.MarshalerForRequest(mux, request)
		var after uint64
		var changed <-chan struct{}
		wait := false
		gateway.ForwardResponseStream(ctx, mux, marshaler, writer, request, func() (proto.Message, error) {
			if wait {
				select {
				case <-ctx.Done():
					return nil, io.EOF
				case <-changed:
				}
			}
			if ctx.Err() != nil {
				return nil, io.EOF
			}
			frame, next, signal := w.read(after)
			after, changed = next, signal
			wait = len(frame.Sessions) < 100 || frame.CaughtUp
			return frame, nil
		})
	})
}
