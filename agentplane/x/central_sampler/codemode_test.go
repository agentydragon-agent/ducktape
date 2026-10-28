package centralsampler

import (
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"testing"
	"time"
)

func TestCodeModeStopNotifiesPendingRequestsAndJoinsDelegates(t *testing.T) {
	log, err := os.CreateTemp(t.TempDir(), "host.log")
	if err != nil {
		t.Fatal(err)
	}
	stdinReader, stdinWriter := io.Pipe()
	stdoutReader, stdoutWriter := io.Pipe()
	t.Cleanup(func() {
		_ = stdinReader.Close()
		_ = stdoutWriter.Close()
	})
	hostDone := make(chan struct{})
	close(hostDone)
	host := &Host{cmd: &exec.Cmd{}, stdin: stdinWriter, stdout: stdoutReader, done: hostDone, log: log}

	response := make(chan codeReply, 1)
	runtime := &CodeMode{
		host: host, responses: map[int64]chan codeReply{1: response}, initials: map[int64]chan codeReply{},
		readerDone: make(chan struct{}), delegates: map[int64]struct{}{},
	}
	close(runtime.readerDone)
	runtime.fail(errors.New("host failed"))

	delegateGate := make(chan struct{})
	runtime.delegateWG.Add(1)
	go func() {
		defer runtime.delegateWG.Done()
		<-delegateGate
	}()

	stopDone := make(chan error, 1)
	go func() { stopDone <- runtime.Stop(context.Background()) }()
	select {
	case frame := <-response:
		if got := frame.Err.Error(); got != "host failed" {
			t.Fatalf("pending request error=%v", got)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Stop did not notify a pending request on a failed host")
	}
	select {
	case err := <-stopDone:
		t.Fatalf("Stop returned before delegate completion: %v", err)
	case <-time.After(100 * time.Millisecond):
	}
	close(delegateGate)
	select {
	case err := <-stopDone:
		if err != nil {
			t.Fatalf("Stop failed: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Stop did not finish after delegate completion")
	}

	// A late delegate failure after Stop must remain safe; response channels are never closed.
	runtime.fail(errors.New("late delegate failure"))
	if _, err := runtime.request(context.Background(), codeSessionOperation{Method: "session/open"}, false); err == nil {
		t.Fatal("request after Stop unexpectedly succeeded")
	}
}

func TestCodeModeReceiveCancellationJoinsBlockedFrameRead(t *testing.T) {
	stdoutReader, stdoutWriter := io.Pipe()
	defer stdoutWriter.Close()
	host := &Host{stdout: stdoutReader}
	runtime := &CodeMode{host: host}
	ctx, cancel := context.WithCancel(context.Background())
	result := make(chan error, 1)
	go func() {
		_, err := runtime.receive(ctx)
		result <- err
	}()
	cancel()
	select {
	case err := <-result:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("receive error=%v, want context cancellation", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("receive did not join its blocked read after cancellation")
	}
}

func TestCodeModeSendCancellationUnblocksBlockedFrameWrite(t *testing.T) {
	stdinReader, stdinWriter := io.Pipe()
	defer stdinReader.Close()
	host := &Host{cmd: &exec.Cmd{}, stdin: stdinWriter}
	ctx, cancel := context.WithCancel(context.Background())
	result := make(chan error, 1)
	go func() { result <- writeFrameWithContext(ctx, host, []byte{0, 0, 0, 1}, []byte("x")) }()
	cancel()
	select {
	case err := <-result:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("send error=%v, want context cancellation", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("send did not unblock its pipe write after cancellation")
	}
}
