package ibdock

import (
	"bytes"
	"errors"
	"fmt"
	"github.com/fsouza/go-dockerclient"
	"io/ioutil"
	"log"
	"time"
)

type Dock struct {
	client    *docker.Client
	container *docker.Container
	port      int
	logger    *log.Logger
}

const image = "agentydragon/ibcontroller"
const deadline = 5 * 60 * time.Second

var readSnapshotCmdline = []string{"python3", "/root/read_snapshot.py", "--port=7496"}

func buildEnv(username, password string) []string {
	return []string{"IB_LOGIN_ID=" + username, "IB_PASSWORD=" + password}
}

func makeContainerName() string {
	return fmt.Sprintf("ibcontroller_%d", time.Now().Unix()%1000)
}

func StartNew(username, password string, logger *log.Logger) (*Dock, error) {
	dock := new(Dock)
	dock.logger = logger
	var err error
	dock.client, err = docker.NewClientFromEnv()
	if err != nil {
		return nil, err
	}
	options := docker.CreateContainerOptions{
		Name: makeContainerName(),
		Config: &docker.Config{
			Env:   buildEnv(username, password),
			Image: image,
		},
		HostConfig: &docker.HostConfig{
			PublishAllPorts: true,
		},
	}
	dock.container, err = dock.client.CreateContainer(options)
	if err != nil {
		return nil, err
	}
	err = dock.client.StartContainer(dock.container.ID, nil)
	if err != nil {
		return nil, err
	}
	// TODO: from this point on, the container should be killed if anything
	// fails
	return dock, nil
}

func (dock *Dock) RunExec() ([]byte, error) {
	dock.logger.Println("Calling CreateExec")
	exec, err := dock.client.CreateExec(docker.CreateExecOptions{
		AttachStdout: true,
		AttachStderr: true,
		Cmd:          readSnapshotCmdline,
		Container:    dock.container.ID,
	})
	if err != nil {
		return nil, err
	}
	var stdout, stderr bytes.Buffer
	dock.logger.Println("Calling StartExec")
	// NOTE: This will not work with 'detach'.
	if _, err := dock.client.StartExecNonBlocking(exec.ID, docker.StartExecOptions{
		OutputStream: &stdout,
		ErrorStream:  &stderr,
	}); err != nil {
		return nil, err
	}
	dock.logger.Println("Execution started")
	pollInterval := 5 * time.Second
	timeout := time.After(deadline)
loop:
	for {
		select {
		case <-time.After(pollInterval):
			info, err := dock.client.InspectExec(exec.ID)
			if err != nil {
				return nil, err
			}
			if !info.Running {
				if info.ExitCode != 0 {
					return nil, fmt.Errorf("exit code %d", info.ExitCode)
				}
				dock.logger.Println("finished OK")
				break loop
			}
			dock.logger.Println("not finished yet")
		case <-timeout:
			return nil, errors.New("Timed out waiting to get stocks")
		}
	}
	stdoutBytes, err := ioutil.ReadAll(&stdout)
	if err != nil {
		return nil, err
	}
	dock.logger.Println("stdout:", string(stdoutBytes))
	stderrBytes, err := ioutil.ReadAll(&stderr)
	if err != nil {
		return nil, err
	}
	dock.logger.Println("stderr:", string(stderrBytes))
	return stdoutBytes, nil
}

func (dock *Dock) Kill() {
	dock.client.RemoveContainer(docker.RemoveContainerOptions{
		ID:    dock.container.ID,
		Force: true,
	})
}
