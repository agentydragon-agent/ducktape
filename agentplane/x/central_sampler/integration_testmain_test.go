package centralsampler

import (
	"database/sql"
	"os"
	"testing"

	"github.com/agentydragon/ducktape/agentplane/testing/postgres"
	_ "github.com/lib/pq"
)

var integrationDatabase *postgres.Database

func TestMain(m *testing.M) {
	os.Exit(postgres.RunIntegrationTests(Migrate, func(database *postgres.Database) int {
		integrationDatabase = database
		return m.Run()
	}))
}

func newTestStoreWithDSN(t testing.TB) (*Store, string) {
	t.Helper()
	dsn := integrationDatabase.Clone(t)
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return New(db), dsn
}

func newTestStore(t testing.TB) *Store {
	t.Helper()
	store, _ := newTestStoreWithDSN(t)
	return store
}
