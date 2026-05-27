package main

import (
	"testing"
	"time"
)

func TestMatchGlob(t *testing.T) {
	tests := []struct {
		pattern string
		s       string
		want    bool
	}{
		{"*.ambr", "test_handlers/test.outputs/snapshot.ambr", true},
		{"*.ambr", "test_handlers/test.outputs/log.txt", false},
		{"*", "anything", true},
		{"*.ambr", "snapshot.ambr", true},
		{"test_*/*.ambr", "test_foo/snapshot.ambr", true},
		{"test_*/*.ambr", "other/snapshot.ambr", false},
		{"no-star", "no-star", true},
		{"no-star", "no-stardust", false},
		{"*.log", "foo/bar/test.log", true},
		{"*test.outputs/*", "foo/test.outputs/snapshot.ambr", true},
		{"test.outputs/*", "test.outputs/snapshot.ambr", true},
		{"test.outputs/*", "foo/test.outputs/snapshot.ambr", false},
		{"*.ambr", "", false},
		{"", "", true},
		{"", "nonempty", false},
	}
	for _, tt := range tests {
		got := matchGlob(tt.pattern, tt.s)
		if got != tt.want {
			t.Errorf("matchGlob(%q, %q) = %v, want %v", tt.pattern, tt.s, got, tt.want)
		}
	}
}

func TestFilterArtifacts(t *testing.T) {
	arts := []artifact{
		{Label: "//foo:test", Name: "snapshot.ambr"},
		{Label: "//foo:test", Name: "test.log"},
		{Label: "//bar:test", Name: "other.ambr"},
	}
	tests := []struct {
		pattern string
		want    int
	}{
		{".ambr", 2},
		{"*.ambr", 2},
		{"snapshot.ambr", 1},
		{"test.log", 1},
		{"nonexistent", 0},
		{"*", 3},
	}
	for _, tt := range tests {
		matches := filterArtifacts(arts, tt.pattern)
		if len(matches) != tt.want {
			t.Errorf("filterArtifacts(%q) = %d matches, want %d", tt.pattern, len(matches), tt.want)
		}
	}
}

func TestNormalizeGitURL(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want string
	}{
		{
			name: "ssh url with .git",
			in:   "git@github.com:user/repo.git",
			want: "https://github.com/user/repo",
		},
		{
			name: "https url with .git",
			in:   "https://github.com/user/repo.git",
			want: "https://github.com/user/repo",
		},
		{
			name: "https url without .git",
			in:   "https://github.com/user/repo",
			want: "https://github.com/user/repo",
		},
		{
			name: "ssh url without .git",
			in:   "git@github.com:user/repo",
			want: "https://github.com/user/repo",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := normalizeGitURL(tt.in)
			if got != tt.want {
				t.Errorf("normalizeGitURL(%q) = %q, want %q", tt.in, got, tt.want)
			}
		})
	}
}

func TestParseSince(t *testing.T) {
	now := time.Date(2026, 4, 8, 12, 0, 0, 0, time.UTC)

	tests := []struct {
		name    string
		since   string
		want    time.Time
		wantErr bool
	}{
		{
			name:  "go duration 168h",
			since: "168h",
			want:  time.Date(2026, 4, 1, 12, 0, 0, 0, time.UTC),
		},
		{
			name:  "go duration 24h",
			since: "24h",
			want:  time.Date(2026, 4, 7, 12, 0, 0, 0, time.UTC),
		},
		{
			name:  "date format",
			since: "2026-04-01",
			want:  time.Date(2026, 4, 1, 0, 0, 0, 0, time.UTC),
		},
		{
			name: "empty string",
			want: time.Time{},
		},
		{
			name:    "invalid duration 7d",
			since:   "7d",
			wantErr: true,
		},
		{
			name:    "invalid string",
			since:   "invalid",
			wantErr: true,
		},
		{
			name:  "date does not match as Nd",
			since: "2026-04-08",
			want:  time.Date(2026, 4, 8, 0, 0, 0, 0, time.UTC),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := parseSince(tt.since, now)
			if tt.wantErr {
				if err == nil {
					t.Errorf("parseSince(%q) expected error, got %v", tt.since, got)
				}
				return
			}
			if err != nil {
				t.Errorf("parseSince(%q) unexpected error: %v", tt.since, err)
				return
			}
			if !got.Equal(tt.want) {
				t.Errorf("parseSince(%q) = %v, want %v", tt.since, got, tt.want)
			}
		})
	}
}
