package main

import (
	"testing"
)

func TestDatabaseURLFromEnvironment(t *testing.T) {
	t.Setenv(databaseURLEnv, "postgresql+asyncpg://app:secret@postgres/app")
	got, err := databaseURLFromEnvironment()
	if err != nil {
		t.Fatal(err)
	}
	if want := "postgres://app:secret@postgres/app"; got != want {
		t.Fatalf("databaseURLFromEnvironment() = %q, want %q", got, want)
	}
}

func TestDatabaseURLFromEnvironmentRequiresValue(t *testing.T) {
	t.Setenv(databaseURLEnv, " \t")
	if _, err := databaseURLFromEnvironment(); err == nil {
		t.Fatal("databaseURLFromEnvironment() succeeded with a blank database URL")
	}
}
