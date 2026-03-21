// Game logic for the Genkit Twenty Questions implementation.
//
// Defines Genkit tools (answer, correct_answer, exec) and runs the alternating
// turn loop: guesser produces text questions (optionally using the exec tool),
// simulator responds via tool calls only.
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/firebase/genkit/go/ai"
	"github.com/firebase/genkit/go/genkit"
)

// simAction is the discriminated union of simulator tool call results.
type simAction struct {
	Kind     string `json:"kind"`               // "answer" or "correct_answer"
	Response string `json:"response,omitempty"` // "yes", "no", or "sort_of" (only for kind=answer)
}

// answerInput is the schema for the "answer" tool.
type answerInput struct {
	Response string `json:"response" jsonschema_description:"yes, no, or sort_of"`
}

// emptyInput is the schema for the "correct_answer" tool (no arguments).
type emptyInput struct{}

// execInput is the schema for the "exec" tool (scratch container execution).
type execInput struct {
	Cmd       []string `json:"cmd" jsonschema_description:"Command array passed to exec (no shell wrapping). For shell features use ['sh', '-c', '...']."`
	Cwd       *string  `json:"cwd,omitempty" jsonschema_description:"Working directory inside container (default: /work)"`
	TimeoutMs int      `json:"timeout_ms" jsonschema_description:"Timeout in milliseconds (default: 10000)"`
}

// runGameLoop runs the full twenty questions game loop using Genkit.
//
// The guesser agent asks yes/no questions as text (and may use the exec tool
// for scratch computation if scratch is non-nil). The simulator agent responds
// exclusively via tool calls (answer or correct_answer).
// The game ends when the simulator calls correct_answer or the turn limit is reached.
func runGameLoop(
	ctx context.Context,
	g *genkit.Genkit,
	modelName string,
	v Variant,
	simSystem string,
	agentSystem string,
	callsFile *os.File,
	scratch *ScratchContainer,
) (GameResult, int, error) {
	// The tool closures capture lastAction and lastToolCalls so the game loop
	// can inspect what the simulator did after each Generate round-trip.
	var lastAction *simAction
	var lastToolCalls []toolCallEntry

	// Define the "answer" tool — simulator answers yes/no/sort_of.
	answerTool := genkit.DefineTool(
		g, "answer",
		"Answer the player's yes/no question with yes, no, or sort_of.",
		func(ctx *ai.ToolContext, input answerInput) (string, error) {
			if input.Response != "yes" && input.Response != "no" && input.Response != "sort_of" {
				return "", fmt.Errorf("invalid response %q: must be yes, no, or sort_of", input.Response)
			}
			lastAction = &simAction{Kind: "answer", Response: input.Response}
			lastToolCalls = append(lastToolCalls, toolCallEntry{Name: "answer", Input: string(mustJSON(input))})
			return fmt.Sprintf("Answered: %s", input.Response), nil
		},
	)

	// Define the "correct_answer" tool — simulator signals correct guess.
	correctAnswerTool := genkit.DefineTool(
		g, "correct_answer",
		"The player correctly guessed the secret.",
		func(ctx *ai.ToolContext, input emptyInput) (string, error) {
			lastAction = &simAction{Kind: "correct_answer"}
			lastToolCalls = append(lastToolCalls, toolCallEntry{Name: "correct_answer", Input: "{}"})
			return "Correct answer acknowledged.", nil
		},
	)

	// Define the "exec" tool — guesser runs commands in a scratch container.
	// Only registered if a scratch container is available.
	var guesserOpts []ai.GenerateOption
	if scratch != nil {
		execTool := genkit.DefineTool(
			g, "exec",
			"Run a command in a private scratch container for computation, note-taking, or code execution. "+
				"Does NOT count as a question turn.",
			func(toolCtx *ai.ToolContext, input execInput) (string, error) {
				cwd := ""
				if input.Cwd != nil {
					cwd = *input.Cwd
				}
				timeoutMs := input.TimeoutMs
				if timeoutMs <= 0 {
					timeoutMs = 10000
				}
				result, err := scratch.Exec(ctx, input.Cmd, cwd, timeoutMs)
				if err != nil {
					return "", fmt.Errorf("exec failed: %w", err)
				}
				return fmt.Sprintf("exit_code=%d\n%s", result.ExitCode, result.Output), nil
			},
		)
		guesserOpts = []ai.GenerateOption{ai.WithTools(execTool)}
	}

	// Build the first user message for the guesser from the shared template.
	firstMessage := loadFirstUserMessage(v)

	// Guesser conversation history — starts with system + first user message.
	guesserHistory := []*ai.Message{
		ai.NewSystemTextMessage(agentSystem),
		ai.NewUserTextMessage(firstMessage),
	}

	// Simulator conversation history — starts with system prompt.
	simHistory := []*ai.Message{
		ai.NewSystemTextMessage(simSystem),
	}

	writeLog := func(player, content string, toolCalls []toolCallEntry) {
		entry := LogEntry{
			Timestamp: time.Now().UTC().Format(time.RFC3339),
			Player:    player,
			Content:   content,
			ToolCalls: toolCalls,
		}
		fmt.Fprintln(callsFile, string(mustJSON(entry)))
	}

	var turns int
	for turn := 1; turn <= v.TurnLimit; turn++ {
		turns = turn
		log.Printf("Turn %d/%d", turn, v.TurnLimit)

		// --- Guesser turn: generate a question or guess ---
		// Base options: model + history. Append exec tool if scratch is enabled.
		opts := append([]ai.GenerateOption{
			ai.WithModelName(modelName),
			ai.WithMessages(guesserHistory...),
		}, guesserOpts...)

		guesserResp, err := genkit.Generate(ctx, g, opts...)
		if err != nil {
			return GameResult{}, turn, fmt.Errorf("guesser generate error on turn %d: %w", turn, err)
		}

		guesserText := guesserResp.Text()
		if guesserText == "" {
			return GameResult{}, turn, fmt.Errorf("guesser produced no text on turn %d", turn)
		}

		writeLog("agent", guesserText, nil)
		log.Printf("  Guesser: %s", truncate(guesserText, 120))

		// Append guesser's response and prepare for next turn.
		guesserHistory = guesserResp.History()

		// --- Simulator turn: respond via tool call ---
		// Feed the guesser's text to the simulator as a user message.
		simHistory = append(simHistory, ai.NewUserTextMessage(guesserText))
		lastAction = nil
		lastToolCalls = nil

		simResp, err := genkit.Generate(ctx, g,
			ai.WithModelName(modelName),
			ai.WithMessages(simHistory...),
			ai.WithTools(answerTool, correctAnswerTool),
			ai.WithToolChoice(ai.ToolChoiceRequired),
		)
		if err != nil {
			return GameResult{}, turn, fmt.Errorf("simulator generate error on turn %d: %w", turn, err)
		}

		// Record simulator response. Tool calls were captured by the closures.
		simHistory = simResp.History()
		writeLog("simulator", simResp.Text(), lastToolCalls)

		if lastAction == nil {
			return GameResult{}, turn, fmt.Errorf("simulator produced no tool call on turn %d", turn)
		}

		if lastAction.Kind == "correct_answer" {
			log.Printf("  Simulator: CORRECT!")
			return GameResult{Kind: "correct", Turns: turn}, turns, nil
		}

		log.Printf("  Simulator: %s", lastAction.Response)

		// Feed the simulator's answer back to the guesser.
		guesserHistory = append(guesserHistory, ai.NewUserTextMessage(lastAction.Response))
	}

	return GameResult{Kind: "timeout", Limit: v.TurnLimit}, turns, nil
}

// truncate shortens s to at most n runes, appending "..." if truncated.
func truncate(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	if n <= 3 {
		return string(r[:n])
	}
	return string(r[:n-3]) + "..."
}
