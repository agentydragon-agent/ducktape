package api

import (
	"context"
	"fmt"
	"net"
	"os"
	"path/filepath"

	v1alpha1 "github.com/cosi-project/runtime/api/v1alpha1"
	"github.com/cosi-project/runtime/pkg/state"
	"go.uber.org/zap"
	"google.golang.org/grpc"
)

// Server exposes kubespand's COSI state via gRPC on a Unix socket,
// and optionally on a TCP address for remote access (e.g., test harnesses).
type Server struct {
	grpcServer *grpc.Server
	socketPath string
	tcpAddr    string
	logger     *zap.Logger
}

// NewServer creates a gRPC server that exposes COSI state as read-only
// and implements the Talos MachineService Version RPC.
// If tcpAddr is non-empty, the server also listens on that TCP address.
func NewServer(st state.CoreState, socketPath, tcpAddr string, logger *zap.Logger) *Server {
	srv := grpc.NewServer()
	v1alpha1.RegisterStateServer(srv, NewReadOnlyState(st))
	RegisterMachineService(srv)

	return &Server{
		grpcServer: srv,
		socketPath: socketPath,
		tcpAddr:    tcpAddr,
		logger:     logger,
	}
}

// Run starts the gRPC server on the configured Unix socket (and optionally TCP).
// Blocks until ctx is cancelled, then performs graceful shutdown.
func (s *Server) Run(ctx context.Context) error {
	dir := filepath.Dir(s.socketPath)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("creating socket directory %s: %w", dir, err)
	}

	// Remove stale socket from unclean shutdown.
	if err := os.Remove(s.socketPath); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("removing stale socket %s: %w", s.socketPath, err)
	}

	unixLis, err := net.Listen("unix", s.socketPath)
	if err != nil {
		return fmt.Errorf("listening on %s: %w", s.socketPath, err)
	}

	if err := os.Chmod(s.socketPath, 0o600); err != nil {
		unixLis.Close()
		return fmt.Errorf("setting socket permissions on %s: %w", s.socketPath, err)
	}

	s.logger.Info("API server listening", zap.String("socket", s.socketPath))

	// Optional TCP listener for remote access (test harnesses, diagnostics).
	if s.tcpAddr != "" {
		tcpLis, err := net.Listen("tcp", s.tcpAddr)
		if err != nil {
			unixLis.Close()
			return fmt.Errorf("listening on TCP %s: %w", s.tcpAddr, err)
		}
		s.logger.Info("API server listening on TCP", zap.String("addr", s.tcpAddr))
		go s.grpcServer.Serve(tcpLis) //nolint:errcheck
	}

	go func() {
		<-ctx.Done()
		s.logger.Info("API server shutting down")
		s.grpcServer.GracefulStop()
	}()

	if err := s.grpcServer.Serve(unixLis); err != nil {
		return fmt.Errorf("serving gRPC: %w", err)
	}

	// Clean up socket file after shutdown.
	os.Remove(s.socketPath)

	return nil
}
