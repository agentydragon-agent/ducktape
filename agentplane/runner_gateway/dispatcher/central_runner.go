package dispatcher

import (
	"context"
	"errors"
	"os"
	"strings"
	"time"

	"github.com/agentydragon/ducktape/agentplane/observability"
	commandpb "github.com/agentydragon/ducktape/agentplane/proto/command"
	eventlogpb "github.com/agentydragon/ducktape/agentplane/proto/event_log"
	runnerpb "github.com/agentydragon/ducktape/agentplane/proto/runner"
	sandboxpb "github.com/agentydragon/ducktape/agentplane/proto/sandboxes"
	runnerservicepb "github.com/agentydragon/ducktape/agentplane/runner/runner_servicepb"
	samplerpb "github.com/agentydragon/ducktape/agentplane/x/central_sampler/samplerpb"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
)

// CentralTarget is deployment-owned. The Dispatcher selects the service for new sessions.
type CentralTarget struct {
	Target    string `mapstructure:"target"`
	TokenFile string `mapstructure:"token_file"`
}

type openingReader interface {
	GetOpening(context.Context, string) (*Opening, error)
}

// RoutingRunner keeps native execution local and routes centrally persisted
// conversations directly to their sampler. The execution Sandbox is a binding,
// not the authority for the central conversation's lifetime.
type RoutingRunner struct {
	Native  DeliveryRunner
	Store   openingReader
	Targets map[string]CentralTarget
	Timeout time.Duration
}

func centralSpec(spec *runnerpb.SessionSpec) bool {
	return spec.GetHarness() == runnerpb.Harness_HARNESS_CENTRAL_SAMPLER
}

func sessionRequiresReadyExecutor(spec *runnerpb.SessionSpec) bool {
	return !centralSpec(spec)
}

func validateOpeningExecutor(opening *Opening, sandbox SandboxSnapshot) error {
	if opening.SandboxName != sandbox.Name || opening.SandboxUID != sandbox.UID {
		return status.Error(codes.FailedPrecondition, "session executor identity changed")
	}
	return nil
}

// bindSessionRuntime resolves routing before persistence. Retries retain the original
// binding even when the deployment changes the default for new sessions.
func (s *Service) bindSessionRuntime(ctx context.Context, id string, spec *runnerpb.SessionSpec) (*runnerpb.SessionSpec, error) {
	if spec.GetCentralSampler() != nil {
		return nil, status.Error(codes.InvalidArgument, "central sampler routing is configured by the Dispatcher")
	}
	if !centralSpec(spec) {
		return spec, nil
	}
	bound := proto.Clone(spec).(*runnerpb.SessionSpec)
	opening, err := s.Store.GetOpening(ctx, id)
	switch {
	case err == nil:
		bound.CentralSampler = opening.Spec.GetCentralSampler()
	case errors.Is(err, ErrNotFound):
		if s.CentralService == "" {
			return nil, status.Error(codes.FailedPrecondition, "central sampler service is not configured")
		}
		bound.CentralSampler = &runnerpb.CentralSamplerConfig{Service: s.CentralService}
	default:
		return nil, err
	}
	return bound, nil
}

func ValidateRuntime(spec *runnerpb.SessionSpec, setup *string, targets map[string]CentralTarget) error {
	if !centralSpec(spec) {
		if spec.GetCentralSampler() != nil {
			return status.Error(codes.InvalidArgument, "central_sampler requires HARNESS_CENTRAL_SAMPLER")
		}
		return nil
	}
	config := spec.GetCentralSampler()
	if config.GetService() == "" {
		return status.Error(codes.InvalidArgument, "central sampler service is required")
	}
	if _, enabled := targets[config.GetService()]; !enabled {
		return status.Error(codes.FailedPrecondition, "central sampler service is not enabled")
	}
	if setup != nil && len(*setup) > 65536 {
		return status.Error(codes.InvalidArgument, "setup_script exceeds 65536 UTF-8 bytes")
	}
	return nil
}

func (r *RoutingRunner) withClient(ctx context.Context, service string, call func(context.Context, samplerpb.SamplerClient) error) error {
	target, enabled := r.Targets[service]
	if !enabled {
		return status.Error(codes.FailedPrecondition, "central sampler service is not enabled")
	}
	if target.Target == "" || target.TokenFile == "" || r.Timeout <= 0 {
		return status.Error(codes.Internal, "invalid configured central sampler target")
	}
	data, err := os.ReadFile(target.TokenFile)
	if err != nil {
		return status.Error(codes.Unavailable, "cannot read central sampler token")
	}
	token := strings.TrimSpace(string(data))
	if token == "" {
		return status.Error(codes.Unavailable, "central sampler token is empty")
	}
	conn, err := grpc.NewClient(target.Target, observability.GRPCClientOption(), grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithDisableRetry())
	if err != nil {
		return err
	}
	defer conn.Close()
	ctx, cancel := context.WithTimeout(ctx, r.Timeout)
	defer cancel()
	ctx = metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer "+token))
	return call(ctx, samplerpb.NewSamplerClient(conn))
}

func (r *RoutingRunner) OpenSession(ctx context.Context, sandbox SandboxSnapshot, id string, spec *runnerpb.SessionSpec, setup *string) error {
	if err := ValidateRuntime(spec, setup, r.Targets); err != nil {
		return err
	}
	if !centralSpec(spec) {
		return r.Native.OpenSession(ctx, sandbox, id, spec, setup)
	}
	if sandbox.Incarnation == "" {
		return status.Error(codes.FailedPrecondition, "executor incarnation is not available")
	}
	return r.withClient(ctx, spec.GetCentralSampler().GetService(), func(ctx context.Context, client samplerpb.SamplerClient) error {
		_, err := client.OpenSession(ctx, &samplerpb.OpenSessionRequest{
			SessionId: id, Spec: spec, ExpectedIncarnationUid: sandbox.Incarnation, SetupScript: setup,
			Executor: &sandboxpb.SandboxDestination{Owner: &sandboxpb.ServiceAccount{Namespace: sandbox.Namespace, Name: sandbox.Name}, Sandbox: sandbox.Name, SandboxUid: sandbox.UID},
		})
		return err
	})
}

func (r *RoutingRunner) Deliver(ctx context.Context, sandbox SandboxSnapshot, id string, command *commandpb.Command) (*eventlogpb.EventEntry, error) {
	opening, err := r.Store.GetOpening(ctx, id)
	// Existing runner Sessions may predate Dispatcher OpenSession.
	if errors.Is(err, ErrNotFound) {
		return r.Native.Deliver(ctx, sandbox, id, command)
	}
	if err != nil {
		return nil, err
	}
	if !centralSpec(opening.Spec) {
		return r.Native.Deliver(ctx, sandbox, id, command)
	}
	if err := validateOpeningExecutor(opening, sandbox); err != nil {
		return nil, err
	}
	var admission *eventlogpb.EventEntry
	err = r.withClient(ctx, opening.Spec.GetCentralSampler().GetService(), func(ctx context.Context, client samplerpb.SamplerClient) error {
		switch payload := command.GetOperation().(type) {
		case *commandpb.Command_SubmitInput:
			reply, err := client.SubmitInput(ctx, &runnerservicepb.SubmitInputRequest{SessionId: id, CommandId: command.GetCommandId(), Text: payload.SubmitInput.GetText()})
			if err == nil {
				admission = reply.GetAdmission()
			}
			return err
		case *commandpb.Command_ChangeModel:
			reply, err := client.ChangeModel(ctx, &runnerservicepb.ChangeModelRequest{SessionId: id, CommandId: command.GetCommandId(), Model: payload.ChangeModel.GetModel()})
			if err == nil {
				admission = reply.GetAdmission()
			}
			return err
		case *commandpb.Command_ChangeReasoningEffort:
			reply, err := client.ChangeReasoningEffort(ctx, &runnerservicepb.ChangeReasoningEffortRequest{SessionId: id, CommandId: command.GetCommandId(), Effort: payload.ChangeReasoningEffort.GetEffort()})
			if err == nil {
				admission = reply.GetAdmission()
			}
			return err
		case *commandpb.Command_InterruptTurn:
			reply, err := client.InterruptTurn(ctx, &runnerservicepb.InterruptTurnRequest{SessionId: id, CommandId: command.GetCommandId(), TurnId: payload.InterruptTurn.GetTurnId()})
			if err == nil {
				admission = reply.GetAdmission()
			}
			return err
		default:
			return status.Error(codes.InvalidArgument, "unsupported central sampler command")
		}
	})
	return admission, err
}
