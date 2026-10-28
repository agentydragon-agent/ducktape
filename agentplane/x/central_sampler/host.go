package centralsampler

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"github.com/containerd/cgroups/v3/cgroup2"
	"github.com/google/uuid"
	"github.com/sethvargo/go-retry"
)

type Host struct {
	cmd       *exec.Cmd
	stdin     io.WriteCloser
	stdout    io.ReadCloser
	cgroup    *cgroup2.Manager
	log       *os.File
	done      chan struct{}
	waitErr   error
	mu        sync.Mutex
	closeOnce sync.Once
	closeErr  error
}

func StartHost(ctx context.Context, binary, logPath string, settings Settings) (*Host, error) {
	if binary == "" || logPath == "" {
		return nil, errors.New("code-mode binary and log path are required")
	}
	if err := os.MkdirAll(filepath.Dir(logPath), 0o750); err != nil {
		return nil, err
	}
	log, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o640)
	if err != nil {
		return nil, err
	}
	host := &Host{log: log, done: make(chan struct{})}
	var command *exec.Cmd
	var gateRead *os.File
	var gateWrite *os.File
	if settings.HostCgroupRoot != "" {
		command, host.cgroup, gateRead, gateWrite, err = cgroupCommand(ctx, binary, settings)
	} else {
		command = exec.CommandContext(ctx, binary, "--listen", "stdio")
	}
	if err != nil {
		_ = log.Close()
		return nil, err
	}
	stdin, err := command.StdinPipe()
	if err != nil {
		closeGate(gateRead)
		closeGate(gateWrite)
		cleanupErr := deleteHostCgroup(host.cgroup)
		_ = log.Close()
		return nil, errors.Join(err, cleanupErr)
	}
	stdout, err := command.StdoutPipe()
	if err != nil {
		_ = stdin.Close()
		closeGate(gateRead)
		closeGate(gateWrite)
		cleanupErr := deleteHostCgroup(host.cgroup)
		_ = log.Close()
		return nil, errors.Join(err, cleanupErr)
	}
	command.Stderr = log
	if err := command.Start(); err != nil {
		closeGate(gateRead)
		_ = stdin.Close()
		_ = stdout.Close()
		closeGate(gateWrite)
		cleanupErr := deleteHostCgroup(host.cgroup)
		_ = log.Close()
		return nil, errors.Join(err, cleanupErr)
	}
	closeGate(gateRead)
	if gateWrite != nil {
		if err := host.cgroup.AddProc(uint64(command.Process.Pid)); err != nil {
			_ = command.Process.Kill()
			_ = command.Wait()
			closeGate(gateWrite)
			cleanupErr := deleteHostCgroup(host.cgroup)
			_ = log.Close()
			return nil, errors.Join(fmt.Errorf("place code-mode host in cgroup: %w", err), cleanupErr)
		}
		written, err := gateWrite.Write([]byte("go\n"))
		if err != nil || written != len("go\n") {
			_ = command.Process.Kill()
			_ = command.Wait()
			closeGate(gateWrite)
			cleanupErr := deleteHostCgroup(host.cgroup)
			_ = log.Close()
			if err == nil {
				err = io.ErrShortWrite
			}
			return nil, errors.Join(err, cleanupErr)
		}
		closeGate(gateWrite)
	}
	host.cmd, host.stdin, host.stdout = command, stdin, stdout
	go func() {
		host.waitErr = command.Wait()
		close(host.done)
	}()
	return host, nil
}

func cgroupCommand(ctx context.Context, binary string, settings Settings) (*exec.Cmd, *cgroup2.Manager, *os.File, *os.File, error) {
	root, err := filepath.Abs(settings.HostCgroupRoot)
	if err != nil {
		return nil, nil, nil, nil, err
	}
	parent, err := cgroup2.Load("/"+filepath.Base(root), cgroup2.WithMountpoint(filepath.Dir(root)))
	if err != nil {
		return nil, nil, nil, nil, fmt.Errorf("load code-mode host cgroup root: %w", err)
	}
	name := "sampler-" + uuid.NewString()
	manager, err := parent.NewChild(name, hostCgroupResources(settings))
	if err != nil {
		return nil, nil, nil, nil, fmt.Errorf("create code-mode host cgroup: %w", err)
	}
	gateRead, gateWrite, err := os.Pipe()
	if err != nil {
		return nil, nil, nil, nil, errors.Join(err, deleteHostCgroup(manager))
	}
	command := exec.CommandContext(ctx, "/bin/sh", "-c", "IFS= read -r gate <&3 || exit 1; [ \"$gate\" = go ] || exit 1; exec \"$@\"", "sampler-host-gate", binary, "--listen", "stdio")
	command.ExtraFiles = []*os.File{gateRead}
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	return command, manager, gateRead, gateWrite, nil
}

func hostCgroupResources(settings Settings) *cgroup2.Resources {
	cpuQuota := int64(settings.HostCPUQuotaUS)
	period := uint64(100000)
	memoryMax := settings.HostRSSBytes
	memorySwapMax := int64(0)
	groupOOM := true
	pidsMax := int64(settings.HostPids)
	return &cgroup2.Resources{
		CPU:    &cgroup2.CPU{Max: cgroup2.NewCPUMax(&cpuQuota, &period)},
		Memory: &cgroup2.Memory{Max: &memoryMax, Swap: &memorySwapMax, OOMGroup: &groupOOM},
		Pids:   &cgroup2.Pids{Max: pidsMax},
	}
}

func deleteHostCgroup(manager *cgroup2.Manager) error {
	if manager == nil {
		return nil
	}
	_ = manager.Kill()
	backoff := retry.WithMaxDuration(5*time.Second, retry.NewConstant(50*time.Millisecond))
	err := retry.Do(context.Background(), backoff, func(context.Context) error {
		err := manager.Delete()
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return retry.RetryableError(err)
	})
	if err != nil {
		return fmt.Errorf("remove code-mode host cgroup: %w", err)
	}
	return nil
}

func closeGate(file *os.File) {
	if file != nil {
		_ = file.Close()
	}
}

func (h *Host) Stdin() io.WriteCloser { return h.stdin }
func (h *Host) Stdout() io.ReadCloser { return h.stdout }
func (h *Host) PID() int              { return h.cmd.Process.Pid }
func (h *Host) Done() <-chan struct{} { return h.done }

func (h *Host) Wait() error {
	<-h.done
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.waitErr
}

func (h *Host) Kill() error {
	if h.cgroup != nil {
		if err := h.cgroup.Kill(); err == nil {
			return nil
		} else if h.cmd.Process == nil {
			return err
		} else if killErr := h.cmd.Process.Kill(); killErr != nil && !errors.Is(killErr, os.ErrProcessDone) {
			return errors.Join(err, killErr)
		} else {
			return err
		}
	}
	if h.cmd.Process == nil {
		return nil
	}
	return h.cmd.Process.Kill()
}

func (h *Host) Close() error {
	h.closeOnce.Do(func() {
		killErr := h.Kill()
		select {
		case <-h.done:
			var errs []error
			if killErr != nil && !errors.Is(killErr, os.ErrProcessDone) {
				errs = append(errs, killErr)
			}
			if h.cgroup != nil {
				if err := deleteHostCgroup(h.cgroup); err != nil {
					errs = append(errs, err)
				}
			}
			if err := h.stdin.Close(); err != nil && !errors.Is(err, os.ErrClosed) {
				errs = append(errs, err)
			}
			if err := h.stdout.Close(); err != nil && !errors.Is(err, os.ErrClosed) {
				errs = append(errs, err)
			}
			if err := h.log.Close(); err != nil && !errors.Is(err, os.ErrClosed) {
				errs = append(errs, err)
			}
			h.closeErr = errors.Join(errs...)
		case <-time.After(5 * time.Second):
			_ = h.stdin.Close()
			_ = h.stdout.Close()
			_ = h.log.Close()
			h.closeErr = errors.Join(killErr, errors.New("code-mode host did not stop after kill"))
		}
	})
	return h.closeErr
}
