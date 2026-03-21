//! Lightweight Docker exec for scratch containers using bollard.

use bollard::Docker;
use bollard::exec::StartExecResults;
use bollard::models::{ContainerCreateBody, ExecConfig};
use bollard::query_parameters::{CreateContainerOptions, RemoveContainerOptionsBuilder};
use futures::StreamExt;

pub struct ExecResult {
    pub exit_code: i64,
    pub output: String,
}

pub struct ScratchContainer {
    docker: Docker,
    container_id: String,
}

impl ScratchContainer {
    pub async fn create(image: &str) -> anyhow::Result<Self> {
        let docker = Docker::connect_with_local_defaults()?;

        let config = ContainerCreateBody {
            image: Some(image.to_string()),
            cmd: Some(vec!["sleep".into(), "infinity".into()]),
            network_disabled: Some(true),
            ..Default::default()
        };

        let container = docker
            .create_container(None::<CreateContainerOptions>, config)
            .await?;

        docker.start_container(&container.id, None).await?;

        Ok(Self {
            docker,
            container_id: container.id,
        })
    }

    pub async fn exec(&self, cmd: &str) -> anyhow::Result<ExecResult> {
        let exec = self
            .docker
            .create_exec(
                &self.container_id,
                ExecConfig {
                    cmd: Some(
                        vec!["sh", "-c", cmd]
                            .into_iter()
                            .map(ToString::to_string)
                            .collect(),
                    ),
                    attach_stdout: Some(true),
                    attach_stderr: Some(true),
                    ..Default::default()
                },
            )
            .await?;

        let mut output_text = String::new();
        if let StartExecResults::Attached {
            output: mut stream, ..
        } = self.docker.start_exec(&exec.id, None).await?
        {
            while let Some(Ok(msg)) = stream.next().await {
                output_text.push_str(&msg.to_string());
            }
        }

        let inspect = self.docker.inspect_exec(&exec.id).await?;
        let exit_code = inspect.exit_code.unwrap_or(-1);

        Ok(ExecResult {
            exit_code,
            output: output_text,
        })
    }

    /// Returns the container ID.
    pub fn container_id(&self) -> &str {
        &self.container_id
    }

    /// Force-remove the container.
    pub async fn force_cleanup(&self) -> anyhow::Result<()> {
        self.docker
            .remove_container(
                &self.container_id,
                Some(RemoveContainerOptionsBuilder::default().force(true).build()),
            )
            .await?;
        Ok(())
    }
}
