package control

import (
	"context"
	"sync"
	"time"

	controlpb "github.com/agentydragon/ducktape/agentplane/runner_gateway/runner_controlpb"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// Bound the stream's outbound payload backlog independently of per-channel queues.
const executorSendQueue = 32

type frameWrite struct {
	frame *controlpb.RunnerFrame
	done  chan error
}

// sender keeps WebSocket payload traffic behind Runner replies and heartbeats. The
// Gateway does the same on its side of the stream, so a full data queue cannot starve control.
type sender struct {
	ctx      context.Context
	timeout  time.Duration
	send     func(*controlpb.RunnerFrame) error
	priority chan *frameWrite
	data     chan *frameWrite
	done     chan struct{}
	mu       sync.Mutex
	err      error
}

func newSender(ctx context.Context, send func(*controlpb.RunnerFrame) error) *sender {
	sender := &sender{
		ctx: ctx, timeout: streamLiveness, send: send, priority: make(chan *frameWrite, 32),
		data: make(chan *frameWrite, executorSendQueue), done: make(chan struct{}),
	}
	go sender.run()
	return sender
}

func (s *sender) Send(frame *controlpb.RunnerFrame) error {
	return s.enqueue(frame, s.priority)
}

func (s *sender) SendExecutor(frame *controlpb.RunnerFrame) error {
	return s.enqueue(frame, s.data)
}

func (s *sender) enqueue(frame *controlpb.RunnerFrame, queue chan *frameWrite) error {
	request := &frameWrite{frame: frame, done: make(chan error, 1)}
	select {
	case queue <- request:
	case <-s.done:
		return s.error()
	case <-s.ctx.Done():
		return status.FromContextError(s.ctx.Err()).Err()
	}
	select {
	case err := <-request.done:
		return err
	case <-s.done:
		return s.error()
	case <-s.ctx.Done():
		return status.FromContextError(s.ctx.Err()).Err()
	}
}

func (s *sender) run() {
	for {
		select {
		case <-s.ctx.Done():
			s.fail(status.FromContextError(s.ctx.Err()).Err())
			return
		case <-s.done:
			return
		default:
		}
		select {
		case request := <-s.priority:
			s.write(request)
			continue
		default:
		}
		select {
		case request := <-s.priority:
			s.write(request)
		case request := <-s.data:
			s.write(request)
		case <-s.ctx.Done():
			s.fail(status.FromContextError(s.ctx.Err()).Err())
			return
		}
	}
}

func (s *sender) write(request *frameWrite) {
	result := make(chan error, 1)
	go func() { result <- s.send(request.frame) }()
	timer := time.NewTimer(s.timeout)
	defer timer.Stop()
	select {
	case err := <-result:
		if err != nil {
			s.fail(err)
		}
		request.done <- err
	case <-s.ctx.Done():
		err := status.FromContextError(s.ctx.Err()).Err()
		s.fail(err)
		request.done <- err
	case <-timer.C:
		err := status.Error(codes.Unavailable, "runner control stream send timed out")
		s.fail(err)
		request.done <- err
	}
}

func (s *sender) fail(err error) {
	s.mu.Lock()
	if s.err == nil {
		s.err = err
		close(s.done)
	}
	s.mu.Unlock()
}

func (s *sender) error() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.err != nil {
		return s.err
	}
	return status.Error(codes.Unavailable, "runner control stream ended")
}
