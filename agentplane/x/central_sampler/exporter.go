package centralsampler

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"time"

	"github.com/agentydragon/ducktape/agentplane/grpc/bearer"
	ingresspb "github.com/agentydragon/ducktape/agentplane/history_service/runner_ingresspb"
	"github.com/agentydragon/ducktape/agentplane/postgres/go/wakeups"
	eventlogpb "github.com/agentydragon/ducktape/agentplane/proto/event_log"
	"golang.org/x/sync/errgroup"
	"google.golang.org/grpc"
)

const (
	exportPageSize     = 16
	exportPagesPerTurn = 16
	exportConcurrency  = 8
	exportRetry        = time.Second
)

func ExportSession(ctx context.Context, store *Store, sessionID, target, tokenFile string) error {
	channel, err := bearer.Dial(target, tokenFile, 30*time.Second)
	if err != nil {
		return err
	}
	defer channel.Close()
	return exportSession(ctx, store, sessionID, target, channel)
}

func exportSession(ctx context.Context, store *Store, sessionID, target string, channel grpc.ClientConnInterface) error {
	pages := 0
	for refresh := 0; refresh < exportPagesPerTurn; refresh++ {
		session, err := store.GetSession(ctx, sessionID, "")
		if err != nil {
			return err
		}
		snapshot, err := Describe(session)
		if err != nil {
			return err
		}
		callCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
		err = func() error {
			call, err := ingresspb.NewRunnerIngressClient(channel).Push(callCtx)
			if err != nil {
				return err
			}
			if err := call.Send(&ingresspb.PushFrame{Frame: &ingresspb.PushFrame_SamplerAnnounce{SamplerAnnounce: &ingresspb.SamplerAnnouncement{Session: snapshot.GetAttached(), Executor: snapshot.GetExecutor()}}}); err != nil {
				return err
			}
			first, err := call.Recv()
			if err != nil {
				return fmt.Errorf("History initial acknowledgement: %w", err)
			}
			current, err := store.GetSession(callCtx, sessionID, "")
			if err != nil {
				return err
			}
			if first.GetSealed() || first.GetCursor() > current.Cursor {
				return errors.New("History acknowledgement conflicts with sampler journal")
			}
			after := first.GetCursor()
			for after < session.Cursor && pages < exportPagesPerTurn {
				entries, err := store.Events(callCtx, sessionID, after, min(exportPageSize, int(session.Cursor-after)))
				if err != nil {
					return err
				}
				if len(entries) == 0 {
					return errors.New("sampler journal missing committed evidence")
				}
				through := entries[len(entries)-1].GetCursor()
				tasks, pageCtx := errgroup.WithContext(callCtx)
				// A reader failure must also interrupt a sender blocked in gRPC flow control.
				tasks.Go(func() error {
					err := sendExportPage(call, entries)
					if err != nil {
						cancel()
					}
					return err
				})
				next := after
				tasks.Go(func() error {
					var err error
					next, err = acknowledgeExportPage(pageCtx, store, sessionID, target, call, after, through)
					if err != nil {
						cancel()
					}
					return err
				})
				if err := tasks.Wait(); err != nil {
					return err
				}
				after = next
				pages++
			}
			if err := call.CloseSend(); err != nil {
				return err
			}
			// Half-close and read through EOF to let History commit the announced metadata snapshot.
			for {
				ack, err := call.Recv()
				if errors.Is(err, io.EOF) {
					break
				}
				if err != nil {
					return err
				}
				if ack.GetSealed() || ack.GetCursor() < first.GetCursor() || ack.GetCursor() > after {
					return errors.New("History acknowledgement outside sent prefix")
				}
			}
			return store.CommitCheckpoint(callCtx, sessionID, target, after)
		}()
		cancel()
		if err != nil {
			return err
		}
		current, err := store.GetSession(ctx, sessionID, "")
		if err != nil {
			return err
		}
		checkpoint, err := store.Checkpoint(ctx, sessionID, target)
		if err != nil {
			return err
		}
		if pages == exportPagesPerTurn || (checkpoint != nil && *checkpoint == current.Cursor && session.Cursor == current.Cursor) {
			return nil
		}
	}
	return nil
}

func sendExportPage(call grpc.BidiStreamingClient[ingresspb.PushFrame, ingresspb.Acknowledgement], entries []*eventlogpb.EventEntry) error {
	for _, entry := range entries {
		if err := call.Send(&ingresspb.PushFrame{Frame: &ingresspb.PushFrame_Entry{Entry: entry}}); err != nil {
			return err
		}
	}
	return call.Send(&ingresspb.PushFrame{Frame: &ingresspb.PushFrame_Heartbeat{Heartbeat: &ingresspb.Heartbeat{}}})
}

func acknowledgeExportPage(ctx context.Context, store *Store, sessionID, target string, call grpc.BidiStreamingClient[ingresspb.PushFrame, ingresspb.Acknowledgement], after, through uint64) (uint64, error) {
	for after < through {
		ack, err := call.Recv()
		if err != nil {
			return 0, fmt.Errorf("History batch acknowledgement: %w", err)
		}
		if ack.GetSealed() || ack.GetCursor() < after || ack.GetCursor() > through {
			return 0, errors.New("History acknowledgement outside sent prefix")
		}
		after = ack.GetCursor()
		if err := store.CommitCheckpoint(ctx, sessionID, target, after); err != nil {
			return 0, err
		}
	}
	return after, nil
}

type exportResult struct {
	sessionID string
	err       error
}

func RunExporter(ctx context.Context, store *Store, target, tokenFile string, hub *wakeups.Hub) error {
	changed, unsubscribe, err := hub.Subscribe(OutboxChannel)
	if err != nil {
		return err
	}
	defer unsubscribe()
	channel, err := bearer.Dial(target, tokenFile, 30*time.Second)
	if err != nil {
		return err
	}
	defer channel.Close()
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	tasks, taskCtx := errgroup.WithContext(ctx)
	completed := make(chan exportResult, exportConcurrency)
	running := map[string]struct{}{}
	retries := map[string]time.Time{}
	after := ""
	defer func() { cancel(); _ = tasks.Wait() }()
	for {
		now := time.Now()
		excluded := make([]string, 0, len(running)+len(retries))
		var retryAt time.Time
		for id := range running {
			excluded = append(excluded, id)
		}
		for id, until := range retries {
			if !until.After(now) {
				delete(retries, id)
				continue
			}
			excluded = append(excluded, id)
			if retryAt.IsZero() || until.Before(retryAt) {
				retryAt = until
			}
		}
		if len(running) < exportConcurrency {
			sessions, err := store.PendingSessions(taskCtx, target, excluded, after, exportConcurrency-len(running))
			if err != nil {
				if taskCtx.Err() != nil {
					return taskCtx.Err()
				}
				cancel()
				return err
			}
			for _, session := range sessions {
				id := session.ID
				after = id
				running[id] = struct{}{}
				tasks.Go(func() error {
					err := exportSession(taskCtx, store, id, target, channel)
					select {
					case completed <- exportResult{id, err}:
					case <-taskCtx.Done():
					}
					return nil
				})
			}
		}
		var retry <-chan time.Time
		var timer *time.Timer
		if !retryAt.IsZero() {
			timer = time.NewTimer(time.Until(retryAt))
			retry = timer.C
		}
		select {
		case <-ctx.Done():
			if timer != nil {
				timer.Stop()
			}
			cancel()
			return ctx.Err()
		case <-changed:
		case result := <-completed:
			delete(running, result.sessionID)
			if result.err != nil {
				slog.Warn("History export failed; retaining outbox for replay", "session_id", result.sessionID, "error_type", fmt.Sprintf("%T", result.err))
				retries[result.sessionID] = time.Now().Add(exportRetry)
			}
		case <-retry:
		}
		if timer != nil {
			timer.Stop()
		}
	}
}
