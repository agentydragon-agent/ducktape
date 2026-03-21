//! Core game loop for Twenty Questions using Rig.
//!
//! The guesser agent produces text questions/guesses. The simulator agent
//! responds exclusively via tool calls (`answer` or `correct_answer`).
//!
//! For the guesser, Rig's agent loop auto-executes the exec tool. For the
//! simulator, we use the lower-level `Completion` trait to issue a single
//! completion request and extract the tool call from the response, avoiding
//! the MaxTurnError that occurs with `Chat` + `tool_choice=Required`.
//!
//! The guesser also has access to a scratch container exec tool, backed by
//! a Docker container created before the game starts and cleaned up after.

use crate::docker_exec::ScratchContainer;
use chrono::Utc;
use rig::client::{CompletionClient, ProviderClient};
use rig::completion::{Chat, Completion, CompletionModel, CompletionResponse, ToolDefinition};
use rig::message::{AssistantContent, Message, ToolChoice};
use rig::tool::Tool;
use runfiles::{Runfiles, rlocation};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::fmt;
use std::fs;
use std::io::Write;
use std::path::Path;
use std::sync::{Arc, Mutex};

// ---------------------------------------------------------------------------
// Prompt loading from shared text files via Bazel runfiles
// ---------------------------------------------------------------------------

const PROMPTS_DIR: &str = "_main/skills/info_gathering/evals/twenty_questions";

fn load_runfile(r: &Runfiles, rlocation_path: &str) -> String {
    let path = rlocation!(r, rlocation_path)
        .unwrap_or_else(|| panic!("Could not resolve runfile: {rlocation_path}"));
    fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("Could not read {}: {e}", path.display()))
        .trim()
        .to_string()
}

fn load_sim_prompt(r: &Runfiles, turn_limit: u32, secret: &str) -> String {
    let template = load_runfile(r, &format!("{PROMPTS_DIR}/sim.txt"));
    template
        .replace("{turn_limit}", &turn_limit.to_string())
        .replace("{secret}", secret)
}

fn load_first_user_message(r: &Runfiles, domain_description: &str, turn_limit: u32) -> String {
    let template = load_runfile(r, &format!("{PROMPTS_DIR}/first_user_message.txt"));
    template
        .replace("{domain_description}", domain_description)
        .replace("{turn_limit}", &turn_limit.to_string())
}

fn load_scratch_system_note(r: &Runfiles) -> String {
    load_runfile(r, &format!("{PROMPTS_DIR}/scratch_system_note.txt"))
}

// ---------------------------------------------------------------------------
// Game variant configuration
// ---------------------------------------------------------------------------

pub struct Variant {
    pub name: &'static str,
    pub domain_description: &'static str,
    pub secret: &'static str,
    pub turn_limit: u32,
}

pub fn get_variant(name: &str) -> anyhow::Result<Variant> {
    match name {
        "states" => Ok(Variant {
            name: "states",
            domain_description: "a US state",
            secret: "New Mexico",
            turn_limit: 20,
        }),
        "wide" => Ok(Variant {
            name: "wide",
            domain_description: "a thing — could be anything: object, place, concept, activity, anything",
            secret: "a sourdough starter",
            turn_limit: 25,
        }),
        _ => anyhow::bail!("Unknown variant: {name}. Choose 'states' or 'wide'."),
    }
}

// ---------------------------------------------------------------------------
// Logging / summary types
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Serialize, Deserialize)]
pub enum Player {
    #[serde(rename = "guesser")]
    Guesser,
    #[serde(rename = "simulator")]
    Simulator,
}

#[derive(Serialize, Deserialize)]
pub struct LogEntry {
    pub timestamp: chrono::DateTime<chrono::Utc>,
    pub player: Player,
    pub content: String,
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum GameResult {
    #[serde(rename = "correct")]
    Correct { turns: u32 },
    #[serde(rename = "timeout")]
    Timeout { limit: u32 },
}

#[derive(Serialize, Deserialize)]
pub struct RunSummary {
    pub eval_name: String,
    pub framework: String,
    pub model: String,
    pub api: String,
    pub turns: u32,
    pub result: GameResult,
}

// ---------------------------------------------------------------------------
// Simulator tool types
// ---------------------------------------------------------------------------

/// Shared state for capturing which tool the simulator invoked.
#[derive(Clone, Debug)]
enum SimAction {
    Answer(String),
    CorrectAnswer,
}

type SharedAction = Arc<Mutex<Option<SimAction>>>;

#[derive(Debug)]
struct ToolCallError(String);

impl fmt::Display for ToolCallError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "tool call error: {}", self.0)
    }
}

impl std::error::Error for ToolCallError {}

// -- answer tool --

#[derive(Deserialize)]
struct AnswerArgs {
    response: String,
}

struct AnswerTool {
    action: SharedAction,
}

impl Tool for AnswerTool {
    const NAME: &'static str = "answer";
    type Error = ToolCallError;
    type Args = AnswerArgs;
    type Output = String;

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "answer".to_string(),
            description: "Answer the player's yes/no question with yes, no, or sort_of."
                .to_string(),
            parameters: json!({
                "type": "object",
                "properties": {
                    "response": {
                        "type": "string",
                        "enum": ["yes", "no", "sort_of"],
                        "description": "Your answer to the question"
                    }
                },
                "required": ["response"]
            }),
        }
    }

    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        let resp = args.response.clone();
        let mut guard = self
            .action
            .lock()
            .map_err(|e| ToolCallError(e.to_string()))?;
        *guard = Some(SimAction::Answer(args.response));
        Ok(resp)
    }
}

// -- correct_answer tool --

#[derive(Deserialize)]
struct CorrectAnswerArgs {}

struct CorrectAnswerTool {
    action: SharedAction,
}

impl Tool for CorrectAnswerTool {
    const NAME: &'static str = "correct_answer";
    type Error = ToolCallError;
    type Args = CorrectAnswerArgs;
    type Output = String;

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "correct_answer".to_string(),
            description: "The player correctly guessed the secret.".to_string(),
            parameters: json!({
                "type": "object",
                "properties": {}
            }),
        }
    }

    async fn call(&self, _args: Self::Args) -> Result<Self::Output, Self::Error> {
        let mut guard = self
            .action
            .lock()
            .map_err(|e| ToolCallError(e.to_string()))?;
        *guard = Some(SimAction::CorrectAnswer);
        Ok("correct".to_string())
    }
}

// ---------------------------------------------------------------------------
// Guesser exec tool (scratch container)
// ---------------------------------------------------------------------------

const SCRATCH_IMAGE: &str = "ubuntu:24.04";

#[derive(Deserialize)]
struct ExecArgs {
    cmd: Vec<String>,
    #[serde(default)]
    cwd: Option<String>,
    #[serde(default = "default_timeout_ms")]
    timeout_ms: u64,
}

fn default_timeout_ms() -> u64 {
    30_000
}

struct ExecTool {
    scratch: Arc<ScratchContainer>,
}

impl Tool for ExecTool {
    const NAME: &'static str = "exec";
    type Error = ToolCallError;
    type Args = ExecArgs;
    type Output = String;

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "exec".to_string(),
            description: "Execute a command in a scratch container. Use this to run code, \
                test hypotheses, or compute things during the game."
                .to_string(),
            parameters: json!({
                "type": "object",
                "properties": {
                    "cmd": {
                        "type": "array",
                        "items": { "type": "string" },
                        "description": "Command and arguments to execute"
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory (optional)"
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Timeout in milliseconds (default 30000)"
                    }
                },
                "required": ["cmd"]
            }),
        }
    }

    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        let cmd_str = args
            .cmd
            .iter()
            .map(|a| shell_escape(a))
            .collect::<Vec<_>>()
            .join(" ");

        let full_cmd = match args.cwd {
            Some(ref dir) => format!("cd {} && {}", shell_escape(dir), cmd_str),
            None => cmd_str,
        };

        let timeout_secs = (args.timeout_ms as f64 / 1000.0).ceil() as u64;
        let timed_cmd = format!("timeout {timeout_secs} sh -c {}", shell_escape(&full_cmd));

        log::debug!("ExecTool: {timed_cmd}");

        let result = self
            .scratch
            .exec(&timed_cmd)
            .await
            .map_err(|e| ToolCallError(format!("exec failed: {e}")))?;

        Ok(format!(
            "exit_code: {}\n{}",
            result.exit_code, result.output
        ))
    }
}

/// Minimal shell escaping: wraps in single quotes, escaping existing single quotes.
fn shell_escape(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}

// ---------------------------------------------------------------------------
// Game config
// ---------------------------------------------------------------------------

struct GameConfig<'a> {
    eval_name: &'a str,
    model_name: &'a str,
    api: &'a str,
    first_message: &'a str,
    turn_limit: u32,
    calls_path: &'a Path,
    summary_path: &'a Path,
}

// ---------------------------------------------------------------------------
// Simulator: single-completion approach
// ---------------------------------------------------------------------------

/// Issue a single completion request to the simulator agent and extract the
/// tool call from the response. This avoids the MaxTurnError that occurs when
/// using `Chat` with `tool_choice=Required`, because we never enter the
/// agent's internal tool-execution loop.
async fn sim_single_turn<M: CompletionModel>(
    sim: &impl Completion<M>,
    prompt: &str,
    history: Vec<Message>,
    sim_action: &SharedAction,
) -> anyhow::Result<()> {
    // Clear previous action.
    {
        let mut guard = sim_action.lock().unwrap();
        *guard = None;
    }

    // Use the Completion trait to build and send a single request.
    let response: CompletionResponse<M::Response> = sim
        .completion(prompt, history)
        .await
        .map_err(|e| anyhow::anyhow!("Simulator completion build error: {e}"))?
        .send()
        .await
        .map_err(|e| anyhow::anyhow!("Simulator completion send error: {e}"))?;

    // Extract tool calls from the response and execute them manually.
    for content in response.choice.iter() {
        match content {
            AssistantContent::ToolCall(tc) => {
                let name = &tc.function.name;
                let args = &tc.function.arguments;
                match name.as_str() {
                    "answer" => {
                        let parsed: AnswerArgs = serde_json::from_value(args.clone())
                            .map_err(|e| anyhow::anyhow!("Failed to parse answer args: {e}"))?;
                        let mut guard = sim_action.lock().unwrap();
                        *guard = Some(SimAction::Answer(parsed.response));
                    }
                    "correct_answer" => {
                        let mut guard = sim_action.lock().unwrap();
                        *guard = Some(SimAction::CorrectAnswer);
                    }
                    other => {
                        log::warn!("Simulator called unknown tool: {other}");
                    }
                }
                // Only process the first tool call.
                break;
            }
            _ => continue,
        }
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Game loop
// ---------------------------------------------------------------------------

/// Run the 20 Questions game.
///
/// Creates a scratch container for the guesser's exec tool, builds both
/// agents, runs the game loop, and cleans up the container afterwards.
pub async fn run_game(
    model_name: &str,
    api: &str,
    variant: &Variant,
    output_dir: &Path,
) -> anyhow::Result<RunSummary> {
    let eval_name = format!("20q_rig_{}", variant.name);

    fs::create_dir_all(output_dir)?;
    let ts = Utc::now().format("%Y%m%d_%H%M%S");
    let calls_path = output_dir.join(format!("{eval_name}_{ts}_calls.jsonl"));
    let summary_path = output_dir.join(format!("{eval_name}_{ts}_summary.json"));

    let r = Runfiles::create().map_err(|e| anyhow::anyhow!("Failed to create runfiles: {e:?}"))?;

    let scratch_note = load_scratch_system_note(&r);
    let guesser_system = format!(
        "You are playing 20 Questions as the guesser. Ask strategic yes/no \
         questions to narrow down the answer. When confident, state: \
         'My answer is: [X]'.\n\n{scratch_note}"
    );

    let sim_system = load_sim_prompt(&r, variant.turn_limit, variant.secret);

    let first_message = load_first_user_message(&r, variant.domain_description, variant.turn_limit);

    // Shared state for capturing simulator tool calls.
    let sim_action: SharedAction = Arc::new(Mutex::new(None));

    // Create the scratch container for the guesser's exec tool.
    log::info!("Creating scratch container ({SCRATCH_IMAGE})...");
    let scratch = Arc::new(ScratchContainer::create(SCRATCH_IMAGE).await?);
    log::info!("Scratch container ready: {}", scratch.container_id());

    let config = GameConfig {
        eval_name: &eval_name,
        model_name,
        api,
        first_message: &first_message,
        turn_limit: variant.turn_limit,
        calls_path: &calls_path,
        summary_path: &summary_path,
    };

    // Build agents based on provider selection and run the game loop.
    let result = match api {
        "openai" => {
            let client = rig::providers::openai::Client::from_env();
            run_with_client(
                &client,
                model_name,
                &guesser_system,
                &sim_system,
                &sim_action,
                &scratch,
                &config,
            )
            .await
        }
        "anthropic" => {
            let client = rig::providers::anthropic::Client::from_env();
            run_with_client(
                &client,
                model_name,
                &guesser_system,
                &sim_system,
                &sim_action,
                &scratch,
                &config,
            )
            .await
        }
        _ => anyhow::bail!("Unknown API provider: {api}. Use 'openai' or 'anthropic'."),
    };

    // Clean up the scratch container regardless of game outcome.
    log::info!("Cleaning up scratch container...");
    if let Err(e) = scratch.force_cleanup().await {
        log::warn!("Failed to clean up scratch container: {e}");
    }

    result
}

/// Build guesser and simulator agents from any provider client, then run the game loop.
async fn run_with_client<C: CompletionClient>(
    client: &C,
    model_name: &str,
    guesser_system: &str,
    sim_system: &str,
    sim_action: &SharedAction,
    scratch: &Arc<ScratchContainer>,
    config: &GameConfig<'_>,
) -> anyhow::Result<RunSummary> {
    let guesser = client
        .agent(model_name)
        .preamble(guesser_system)
        .default_max_turns(20)
        .tool(ExecTool {
            scratch: scratch.clone(),
        })
        .build();

    // The simulator agent uses tool_choice=Required and is called via the
    // Completion trait (single request, no agent loop), so default_max_turns
    // is irrelevant here.
    let sim = client
        .agent(model_name)
        .preamble(sim_system)
        .tool(AnswerTool {
            action: sim_action.clone(),
        })
        .tool(CorrectAnswerTool {
            action: sim_action.clone(),
        })
        .tool_choice(ToolChoice::Required)
        .build();

    run_game_loop(&guesser, &sim, sim_action, config).await
}

/// Provider-agnostic game loop.
///
/// The guesser uses `Chat` (Rig's agent loop handles exec tool calls).
/// The simulator uses `Completion` (single request, manual tool dispatch).
async fn run_game_loop<M: CompletionModel>(
    guesser: &(impl Chat + Sync),
    sim: &impl Completion<M>,
    sim_action: &SharedAction,
    config: &GameConfig<'_>,
) -> anyhow::Result<RunSummary> {
    let mut calls_file = fs::File::create(config.calls_path)?;
    let mut result = GameResult::Timeout {
        limit: config.turn_limit,
    };
    let mut turns: u32 = 0;

    let mut guesser_history: Vec<Message> = Vec::new();
    let mut sim_history: Vec<Message> = Vec::new();

    let mut guesser_input = config.first_message.to_string();

    for turn in 1..=config.turn_limit {
        turns = turn;
        log::info!("Turn {turn}/{}", config.turn_limit);

        // --- Guesser turn ---
        let guesser_response = guesser
            .chat(&guesser_input, guesser_history.clone())
            .await
            .map_err(|e| anyhow::anyhow!("Guesser LLM error on turn {turn}: {e}"))?;

        guesser_history.push(Message::user(&guesser_input));
        guesser_history.push(Message::assistant(&guesser_response));

        log::info!("Guesser: {guesser_response}");

        let guesser_entry = LogEntry {
            timestamp: Utc::now(),
            player: Player::Guesser,
            content: guesser_response.clone(),
        };
        writeln!(calls_file, "{}", serde_json::to_string(&guesser_entry)?)?;

        // --- Simulator turn ---
        sim_single_turn::<M>(sim, &guesser_response, sim_history.clone(), sim_action).await?;

        sim_history.push(Message::user(&guesser_response));

        // Read the action captured by manual tool dispatch.
        let action = {
            let guard = sim_action.lock().unwrap();
            guard.clone()
        };

        match action {
            Some(SimAction::CorrectAnswer) => {
                log::info!("Simulator: correct_answer on turn {turn}");
                sim_history.push(Message::assistant("correct_answer"));
                let sim_entry = LogEntry {
                    timestamp: Utc::now(),
                    player: Player::Simulator,
                    content: "correct_answer".into(),
                };
                writeln!(calls_file, "{}", serde_json::to_string(&sim_entry)?)?;
                result = GameResult::Correct { turns: turn };
                break;
            }
            Some(SimAction::Answer(ref response)) => {
                log::info!("Simulator: {response}");
                sim_history.push(Message::assistant(response));
                let sim_entry = LogEntry {
                    timestamp: Utc::now(),
                    player: Player::Simulator,
                    content: response.clone(),
                };
                writeln!(calls_file, "{}", serde_json::to_string(&sim_entry)?)?;
                guesser_input = response.clone();
            }
            None => {
                log::warn!("Simulator produced no tool action on turn {turn}, treating as timeout");
                sim_history.push(Message::assistant("(no tool action)"));
                let sim_entry = LogEntry {
                    timestamp: Utc::now(),
                    player: Player::Simulator,
                    content: "(no tool action)".into(),
                };
                writeln!(calls_file, "{}", serde_json::to_string(&sim_entry)?)?;
                break;
            }
        }
    }

    let summary = RunSummary {
        eval_name: config.eval_name.to_string(),
        framework: "rig".into(),
        model: config.model_name.into(),
        api: config.api.into(),
        turns,
        result,
    };

    fs::write(config.summary_path, serde_json::to_string_pretty(&summary)?)?;
    log::info!(
        "Saved results to {}",
        config
            .summary_path
            .parent()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| ".".to_string())
    );

    Ok(summary)
}
