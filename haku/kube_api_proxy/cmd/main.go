// Copyright 2026 agentydragon
// SPDX-License-Identifier: Apache-2.0

package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	kubeapiproxy "github.com/agentydragon/ducktape/haku/kube_api_proxy"
)

func main() {
	if err := run(); err != nil {
		slog.Error("Haku Kubernetes API proxy stopped", "error", err)
		os.Exit(1)
	}
}

func run() error {
	authorizationURL, err := requiredURL("HAKU_KUBE_AUTHORIZATION_URL")
	if err != nil {
		return err
	}
	upstreamURL, transport, err := kubeapiproxy.InClusterUpstream()
	if err != nil {
		return err
	}

	handler, err := kubeapiproxy.NewHandler(kubeapiproxy.Config{
		Upstream:                   upstreamURL,
		UpstreamTransport:          transport,
		AuthorizationURL:           authorizationURL,
		AllowInsecureAuthorization: boolFromEnv("HAKU_KUBE_ALLOW_INSECURE_AUTHORITY", false),
		AuthorizationTimeout:       durationFromEnv("HAKU_KUBE_AUTHORIZATION_TIMEOUT", 3*time.Second),
		RequestTimeout:             durationFromEnv("HAKU_KUBE_REQUEST_TIMEOUT", 30*time.Second),
		MaxRequestBytes:            int64FromEnv("HAKU_KUBE_MAX_REQUEST_BYTES", 10<<20),
	})
	if err != nil {
		return err
	}

	server := &http.Server{
		Addr:              envOr("HAKU_KUBE_LISTEN_ADDRESS", ":8080"),
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       60 * time.Second,
		// Request contexts carry the stricter per-request/lease deadline. Do not
		// add WriteTimeout here: it would make future streaming support subtly
		// depend on a second, unrelated deadline.
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownCtx)
	}()

	slog.Info("Haku Kubernetes API proxy listening", "address", server.Addr, "upstream", upstreamURL.Redacted())
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

func requiredURL(name string) (*url.URL, error) {
	value := os.Getenv(name)
	if value == "" {
		return nil, fmt.Errorf("%s is required", name)
	}
	parsed, err := url.Parse(value)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return nil, fmt.Errorf("%s must be an absolute URL", name)
	}
	return parsed, nil
}

func envOr(name string, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func durationFromEnv(name string, fallback time.Duration) time.Duration {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	parsed, err := time.ParseDuration(value)
	if err != nil || parsed <= 0 {
		slog.Warn("ignoring invalid duration", "environment", name, "value", value)
		return fallback
	}
	return parsed
}

func boolFromEnv(name string, fallback bool) bool {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		slog.Warn("ignoring invalid boolean", "environment", name, "value", value)
		return fallback
	}
	return parsed
}

func int64FromEnv(name string, fallback int64) int64 {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseInt(value, 10, 64)
	if err != nil || parsed <= 0 {
		slog.Warn("ignoring invalid positive integer", "environment", name, "value", value)
		return fallback
	}
	return parsed
}
