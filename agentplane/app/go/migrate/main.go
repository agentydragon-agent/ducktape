// app-migrate is an init container, not part of the Agentplane app's startup.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/agentydragon/ducktape/agentplane/app/go/migrations"
	dbmigrate "github.com/agentydragon/ducktape/agentplane/postgres/go/migrate"
)

const databaseURLEnv = "AGENTPLANE_DATABASE_URL"

func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stderr, nil)))
	if err := runCLI(os.Args[1:]); err != nil {
		slog.Error("Agentplane app migration failed", "error", err)
		os.Exit(1)
	}
}

func runCLI(args []string) error {
	if len(args) != 0 {
		return errors.New("usage: app-migrate")
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	return run(ctx)
}

func run(ctx context.Context) error {
	databaseURL, err := databaseURLFromEnvironment()
	if err != nil {
		return err
	}
	if err := dbmigrate.Run(ctx, databaseURL, migrations.Up); err != nil {
		return fmt.Errorf("migrate app database: %w", err)
	}
	slog.InfoContext(ctx, "Agentplane app database migrations complete")
	return nil
}

func databaseURLFromEnvironment() (string, error) {
	databaseURL, ok := os.LookupEnv(databaseURLEnv)
	if !ok || strings.TrimSpace(databaseURL) == "" {
		return "", fmt.Errorf("%s is required", databaseURLEnv)
	}
	// The app setting also accepts SQLAlchemy's asyncpg scheme; lib/pq uses PostgreSQL's URI scheme.
	return strings.Replace(databaseURL, "postgresql+asyncpg://", "postgres://", 1), nil
}
