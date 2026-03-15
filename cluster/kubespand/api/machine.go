// Package api: MachineService Version RPC for talosctl compatibility.
//
// Implements the minimum MachineService surface needed for talosctl to connect
// and query kubespand. All other RPCs return Unimplemented.
package api

import (
	"context"

	"github.com/siderolabs/talos/pkg/machinery/api/machine"
	"github.com/siderolabs/talos/pkg/machinery/version"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/emptypb"
)

// MachineServer implements the Talos MachineService Version RPC.
// All other RPCs inherit UnimplementedMachineServiceServer (returns Unimplemented).
type MachineServer struct {
	machine.UnimplementedMachineServiceServer
}

func (s *MachineServer) Version(_ context.Context, _ *emptypb.Empty) (*machine.VersionResponse, error) {
	return &machine.VersionResponse{
		Messages: []*machine.Version{
			{
				Version: version.NewVersion(),
			},
		},
	}, nil
}

// RegisterMachineService registers the MachineService on a gRPC server.
func RegisterMachineService(srv *grpc.Server) {
	machine.RegisterMachineServiceServer(srv, &MachineServer{})
}
