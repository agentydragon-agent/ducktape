package migrations

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	eventlogpb "github.com/agentydragon/ducktape/agentplane/proto/event_log"
	"google.golang.org/protobuf/proto"
)

const eventKindBatchSize = 512

type eventKindRow struct {
	sessionID string
	cursor    int64
	payload   []byte
	kind      int32
}

type eventKindCursor struct {
	sessionID string
	cursor    int64
}

// backfillEventKinds uses one transaction per bounded batch so an interrupted migration can resume
// from the remaining NULL kinds without retaining a transaction over the whole history table.
func backfillEventKinds(ctx context.Context, db *sql.DB) error {
	var after *eventKindCursor
	for {
		next, err := backfillEventKindBatch(ctx, db, after)
		if err != nil {
			return err
		}
		if next == nil {
			break
		}
		after = next
	}
	_, err := db.ExecContext(ctx, "ALTER TABLE session_event ALTER COLUMN kind SET NOT NULL")
	return err
}

func backfillEventKindBatch(ctx context.Context, db *sql.DB, after *eventKindCursor) (*eventKindCursor, error) {
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var rows *sql.Rows
	if after == nil {
		rows, err = tx.QueryContext(ctx, `SELECT session_id::text, cursor, payload
			FROM session_event WHERE kind IS NULL ORDER BY session_id, cursor LIMIT $1 FOR UPDATE`, eventKindBatchSize)
	} else {
		rows, err = tx.QueryContext(ctx, `SELECT session_id::text, cursor, payload
			FROM session_event WHERE kind IS NULL AND (session_id, cursor) > ($1, $2)
			ORDER BY session_id, cursor LIMIT $3 FOR UPDATE`, after.sessionID, after.cursor, eventKindBatchSize)
	}
	if err != nil {
		return nil, err
	}
	var batch []eventKindRow
	for rows.Next() {
		var row eventKindRow
		if err := rows.Scan(&row.sessionID, &row.cursor, &row.payload); err != nil {
			_ = rows.Close()
			return nil, err
		}
		row.kind, err = eventObservationNumber(row.payload)
		if err != nil {
			_ = rows.Close()
			return nil, fmt.Errorf("decode session_event %s cursor %d: %w", row.sessionID, row.cursor, err)
		}
		batch = append(batch, row)
	}
	if err := errors.Join(rows.Err(), rows.Close()); err != nil {
		return nil, err
	}
	if len(batch) == 0 {
		if err := tx.Commit(); err != nil {
			return nil, err
		}
		return nil, nil
	}
	for _, row := range batch {
		result, err := tx.ExecContext(ctx, `UPDATE session_event SET kind = $3
			WHERE session_id = $1 AND cursor = $2 AND kind IS NULL`, row.sessionID, row.cursor, row.kind)
		if err != nil {
			return nil, err
		}
		updated, err := result.RowsAffected()
		if err != nil {
			return nil, err
		}
		if updated != 1 {
			return nil, fmt.Errorf("backfill session_event %s cursor %d updated %d rows", row.sessionID, row.cursor, updated)
		}
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	last := batch[len(batch)-1]
	return &eventKindCursor{sessionID: last.sessionID, cursor: last.cursor}, nil
}

func eventObservationNumber(payload []byte) (int32, error) {
	var entry eventlogpb.EventEntry
	if err := proto.Unmarshal(payload, &entry); err != nil {
		return 0, err
	}
	if entry.GetEvent() == nil {
		return 0, nil
	}
	event := entry.GetEvent().ProtoReflect()
	field := event.WhichOneof(event.Descriptor().Oneofs().ByName("observation"))
	if field == nil {
		return 0, nil
	}
	return int32(field.Number()), nil
}

func rollbackEventKindBackfill(ctx context.Context, db *sql.DB) error {
	_, err := db.ExecContext(ctx, "ALTER TABLE session_event ALTER COLUMN kind DROP NOT NULL")
	return err
}
