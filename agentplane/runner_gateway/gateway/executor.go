package gateway

import (
	"context"
	"fmt"
	"sync"
	"time"

	executorpb "github.com/agentydragon/ducktape/agentplane/runner_gateway/executor_gatewaypb"
	runnercontrolpb "github.com/agentydragon/ducktape/agentplane/runner_gateway/runner_controlpb"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

const (
	maxExecutorChannelsPerRunner = 8
	executorQueueDepth           = 4
	maxExecutorMessageBytes      = 1 << 20
)

type executorChannel struct {
	id        string
	sessionID string
	ready     chan bool
	frames    chan *executorpb.ExecutorFrame
	outbound  chan *executorOutbound
	done      chan struct{}
	endOnce   sync.Once
	mu        sync.Mutex
	err       error
	close     *executorpb.ExecutorClose
	readySeen bool
}

type executorOutbound struct {
	frame *executorpb.ExecutorFrame
	done  chan error
}

func newExecutorChannel(id, sessionID string) *executorChannel {
	return &executorChannel{
		id: id, sessionID: sessionID, ready: make(chan bool, 1),
		frames:   make(chan *executorpb.ExecutorFrame, executorQueueDepth),
		outbound: make(chan *executorOutbound, executorQueueDepth), done: make(chan struct{}),
	}
}

func (c *executorChannel) finish(err error, closeFrame *executorpb.ExecutorClose) {
	c.endOnce.Do(func() {
		c.mu.Lock()
		c.err = err
		c.close = closeFrame
		c.mu.Unlock()
		close(c.done)
	})
}

func (c *executorChannel) end() (error, *executorpb.ExecutorClose) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.err, c.close
}

func (c *executorChannel) terminalError() error {
	if err, _ := c.end(); err != nil {
		return err
	}
	return status.Error(codes.FailedPrecondition, "executor channel is closed")
}

func (c *executorChannel) deliver(frame *executorpb.ExecutorFrame) error {
	switch body := frame.GetFrame().(type) {
	case *executorpb.ExecutorFrame_Ready:
		c.mu.Lock()
		if c.readySeen {
			c.mu.Unlock()
			return status.Error(codes.InvalidArgument, "runner repeated executor readiness")
		}
		c.readySeen = true
		c.mu.Unlock()
		select {
		case c.ready <- body.Ready.GetAccepted():
		default:
			return status.Error(codes.InvalidArgument, "runner repeated executor readiness")
		}
		if !body.Ready.GetAccepted() {
			c.finish(status.Error(codes.Unavailable, "Sandbox executor is unavailable"), nil)
		}
		return nil
	case *executorpb.ExecutorFrame_Message:
		c.mu.Lock()
		ready := c.readySeen
		c.mu.Unlock()
		if !ready {
			return status.Error(codes.InvalidArgument, "runner sent executor data before readiness")
		}
		if len(body.Message.GetPayload()) > maxExecutorMessageBytes {
			c.finish(status.Error(codes.ResourceExhausted, "executor message exceeds the size limit"), nil)
			return nil
		}
		select {
		case c.frames <- frame:
			return nil
		default:
			c.finish(status.Error(codes.ResourceExhausted, "executor channel queue is full"), nil)
			return nil
		}
	case *executorpb.ExecutorFrame_Close:
		c.finish(nil, body.Close)
		return nil
	default:
		return status.Error(codes.InvalidArgument, "runner sent an invalid executor frame")
	}
}

type executorTunnel struct {
	epoch    uint64
	send     sendServiceFrame
	sendData sendServiceFrame
	mu       sync.Mutex
	nextID   uint64
	active   map[string]*executorChannel
	ended    chan struct{}
	endOnce  sync.Once
	endErr   error
}

func newExecutorTunnel(epoch uint64, send, sendData sendServiceFrame) *executorTunnel {
	return &executorTunnel{
		epoch: epoch, send: send, sendData: sendData,
		active: make(map[string]*executorChannel), ended: make(chan struct{}),
	}
}

func (t *executorTunnel) open(open *executorpb.ExecutorOpen) (*executorChannel, error) {
	t.mu.Lock()
	select {
	case <-t.ended:
		err := t.endErr
		t.mu.Unlock()
		if err != nil {
			return nil, err
		}
		return nil, status.Error(codes.Unavailable, "runner control stream ended")
	default:
	}
	if len(t.active) >= maxExecutorChannelsPerRunner {
		t.mu.Unlock()
		return nil, status.Error(codes.ResourceExhausted, "Sandbox has too many executor channels")
	}
	t.nextID++
	id := fmt.Sprintf("%d-%d", t.epoch, t.nextID)
	channel := newExecutorChannel(id, open.GetSessionId())
	t.active[id] = channel
	t.mu.Unlock()

	frame := &executorpb.ExecutorFrame{
		ChannelId: id,
		Frame:     &executorpb.ExecutorFrame_Open{Open: open},
	}
	if err := t.send(&runnercontrolpb.ServiceFrame{Frame: &runnercontrolpb.ServiceFrame_Executor{Executor: frame}}); err != nil {
		t.remove(id, err)
		return nil, err
	}
	go t.forwardData(channel)
	return channel, nil
}

func (t *executorTunnel) sendMessage(ctx context.Context, channelID string, message *executorpb.ExecutorMessage) error {
	if len(message.GetPayload()) > maxExecutorMessageBytes {
		return status.Error(codes.ResourceExhausted, "executor message exceeds the size limit")
	}
	t.mu.Lock()
	channel := t.active[channelID]
	ended := t.ended
	t.mu.Unlock()
	if channel == nil {
		return status.Error(codes.FailedPrecondition, "executor channel is closed")
	}
	request := &executorOutbound{
		frame: &executorpb.ExecutorFrame{
			ChannelId: channel.id,
			Frame:     &executorpb.ExecutorFrame_Message{Message: message},
		},
		done: make(chan error, 1),
	}
	select {
	case channel.outbound <- request:
	case <-channel.done:
		return channel.terminalError()
	case <-ended:
		if err, _ := channel.end(); err != nil {
			return err
		}
		return status.Error(codes.Unavailable, "runner control stream ended")
	case <-ctx.Done():
		return status.FromContextError(ctx.Err()).Err()
	}
	// Wait until this frame has reached the Runner control stream before accepting the next
	// caller frame. In particular, a following Close must not overtake already accepted data.
	select {
	case err := <-request.done:
		return err
	case <-channel.done:
		return channel.terminalError()
	case <-ended:
		if err, _ := channel.end(); err != nil {
			return err
		}
		return status.Error(codes.Unavailable, "runner control stream ended")
	case <-ctx.Done():
		return status.FromContextError(ctx.Err()).Err()
	}
}

func (t *executorTunnel) forwardData(channel *executorChannel) {
	for {
		select {
		case <-t.ended:
			return
		case <-channel.done:
			return
		case request := <-channel.outbound:
			err := t.sendData(&runnercontrolpb.ServiceFrame{Frame: &runnercontrolpb.ServiceFrame_Executor{Executor: request.frame}})
			request.done <- err
			if err != nil {
				t.remove(channel.id, err)
				return
			}
		}
	}
}

func (t *executorTunnel) sendClose(channelID string, closeFrame *executorpb.ExecutorClose) error {
	t.mu.Lock()
	channel := t.active[channelID]
	t.mu.Unlock()
	if channel == nil {
		return nil
	}
	frame := &executorpb.ExecutorFrame{
		ChannelId: channelID,
		Frame:     &executorpb.ExecutorFrame_Close{Close: closeFrame},
	}
	err := t.send(&runnercontrolpb.ServiceFrame{Frame: &runnercontrolpb.ServiceFrame_Executor{Executor: frame}})
	t.remove(channelID, nil)
	return err
}

func (t *executorTunnel) receive(frame *executorpb.ExecutorFrame) error {
	if frame.GetChannelId() == "" {
		return status.Error(codes.InvalidArgument, "runner executor frame has no channel ID")
	}
	t.mu.Lock()
	channel := t.active[frame.GetChannelId()]
	t.mu.Unlock()
	// Frames already in flight when the caller closes a channel are stale. They cannot open or
	// address another channel, and are dropped without interrupting RunnerControl.
	if channel == nil {
		return nil
	}
	if err := channel.deliver(frame); err != nil {
		channel.finish(err, nil)
		_ = t.sendClose(channel.id, &executorpb.ExecutorClose{Code: 1011})
		t.remove(channel.id, err)
		return nil
	}
	if _, closeFrame := channel.end(); closeFrame != nil {
		t.remove(channel.id, nil)
	}
	return nil
}

func (t *executorTunnel) remove(id string, err error) {
	t.mu.Lock()
	channel := t.active[id]
	delete(t.active, id)
	t.mu.Unlock()
	if channel != nil {
		channel.finish(err, nil)
	}
}

func (t *executorTunnel) close(err error) {
	t.endOnce.Do(func() {
		t.mu.Lock()
		t.endErr = err
		close(t.ended)
		channels := make([]*executorChannel, 0, len(t.active))
		for id, channel := range t.active {
			delete(t.active, id)
			channels = append(channels, channel)
		}
		t.mu.Unlock()
		for _, channel := range channels {
			channel.finish(err, nil)
		}
	})
}

func (c *executorChannel) waitReady(ctx context.Context, timeout <-chan time.Time) error {
	select {
	case accepted := <-c.ready:
		if !accepted {
			return status.Error(codes.Unavailable, "Sandbox executor is unavailable")
		}
		return nil
	case <-c.done:
		err, _ := c.end()
		if err != nil {
			return err
		}
		return status.Error(codes.Unavailable, "Sandbox executor channel closed during setup")
	case <-timeout:
		return status.Error(codes.DeadlineExceeded, "Sandbox executor did not open in time")
	case <-ctx.Done():
		return status.FromContextError(ctx.Err()).Err()
	}
}

func (c *executorChannel) receive(ctx context.Context) (*executorpb.ExecutorFrame, error) {
	select {
	case frame := <-c.frames:
		return frame, nil
	default:
	}
	select {
	case frame := <-c.frames:
		return frame, nil
	case <-c.done:
		err, closeFrame := c.end()
		if err != nil {
			return nil, err
		}
		if closeFrame != nil {
			return &executorpb.ExecutorFrame{Frame: &executorpb.ExecutorFrame_Close{Close: closeFrame}}, nil
		}
		return nil, nil
	case <-ctx.Done():
		return nil, status.FromContextError(ctx.Err()).Err()
	}
}
