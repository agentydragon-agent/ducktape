package api_test

import (
	"context"
	"net"
	"testing"

	v1alpha1 "github.com/cosi-project/runtime/api/v1alpha1"
	"github.com/cosi-project/runtime/pkg/state/impl/inmem"
	"github.com/cosi-project/runtime/pkg/state/impl/namespaced"
	stateclient "github.com/cosi-project/runtime/pkg/state/protobuf/client"
	"github.com/siderolabs/talos/pkg/machinery/api/machine"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	grpcstatus "google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/types/known/emptypb"

	"github.com/cosi-project/runtime/pkg/resource"
	"github.com/cosi-project/runtime/pkg/state"

	"github.com/agentydragon/ducktape/cluster/kubespand/api"
)

const bufSize = 1024 * 1024

type testServer struct {
	st          state.CoreState
	stateClient *stateclient.Adapter
	conn        *grpc.ClientConn
}

func setupServer(t *testing.T) *testServer {
	t.Helper()

	st := namespaced.NewState(inmem.Build)

	lis := bufconn.Listen(bufSize)
	srv := grpc.NewServer()
	v1alpha1.RegisterStateServer(srv, api.NewReadOnlyState(st))
	api.RegisterMachineService(srv)

	go func() {
		if err := srv.Serve(lis); err != nil {
			t.Logf("server exited: %v", err)
		}
	}()
	t.Cleanup(srv.GracefulStop)

	conn, err := grpc.NewClient("passthrough:///bufconn",
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) {
			return lis.Dial()
		}),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		t.Fatalf("dialing bufconn: %v", err)
	}
	t.Cleanup(func() { conn.Close() })

	return &testServer{
		st:          st,
		stateClient: stateclient.NewAdapter(v1alpha1.NewStateClient(conn)),
		conn:        conn,
	}
}

func TestVersion(t *testing.T) {
	ts := setupServer(t)

	mc := machine.NewMachineServiceClient(ts.conn)
	resp, err := mc.Version(context.Background(), &emptypb.Empty{})
	if err != nil {
		t.Fatalf("Version: %v", err)
	}
	if len(resp.Messages) != 1 {
		t.Fatalf("expected 1 version message, got %d", len(resp.Messages))
	}
	if resp.Messages[0].Version == nil {
		t.Fatal("VersionInfo is nil")
	}
	t.Logf("version tag: %s", resp.Messages[0].Version.Tag)
}

func TestListEmpty(t *testing.T) {
	ts := setupServer(t)

	items, err := ts.stateClient.List(context.Background(), resource.NewMetadata("nonexistent", "FakeType", "", resource.VersionUndefined))
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(items.Items) != 0 {
		t.Errorf("expected empty list, got %d items", len(items.Items))
	}
}

func TestCreateDenied(t *testing.T) {
	ts := setupServer(t)

	md := resource.NewMetadata("test-ns", "TestType", "test-id", resource.VersionUndefined)
	err := ts.stateClient.Destroy(context.Background(), md)
	if err == nil {
		t.Fatal("expected error from Destroy, got nil")
	}

	st, ok := grpcstatus.FromError(err)
	if !ok {
		if err.Error() == "" {
			t.Fatal("expected non-empty error")
		}
		return
	}
	if st.Code() != codes.PermissionDenied {
		t.Errorf("expected PermissionDenied, got %v", st.Code())
	}
}

func TestDestroyDenied(t *testing.T) {
	ts := setupServer(t)

	md := resource.NewMetadata("test-ns", "TestType", "test-id", resource.VersionUndefined)
	err := ts.stateClient.Destroy(context.Background(), md)
	if err == nil {
		t.Fatal("expected error from Destroy, got nil")
	}
}
