const TPL = `
  <h2>Papers</h2>
  TODO: toggle show finished/unfinished<br>
  TODO: toggle show prioritized only/unprioritized only/all<br>
  sort by ascending priority<br>
  TODO: show associated topics, allow filtering<
  <table>
  <thead>
    <tr>
      <th>Paper</th>
      <th>Priority</th>
    </tr>
  </thead>
  <tbody class="paper-list">
  </tbody>
  </table>`;

class PaperTable {
  constructor() {
    this.$root = null;
    this.$paperList = null;
  }

  async fillPaperList() {
    this.$paperList.empty();
    const rows = await api.runOnBackend(() => {
      const rows = api.sql.getRows(`
        SELECT
          Papers.noteId,
          Papers.title,
          Priority.priority,
          CASE Finished.finishedReading
            WHEN 'true' THEN 1
            ELSE 0 END AS finishedReading
        FROM (
          SELECT
            notes.noteId,
            notes.title
          FROM
            notes
            LEFT JOIN attributes USING (noteId)
          WHERE
            NOT notes.isDeleted
            AND attributes.name = 'template'
            AND attributes.value = 'WgCQiTGFyKV7'
        ) AS Papers LEFT JOIN (
          SELECT
            attributes.noteId,
            CAST(attributes.value AS INTEGER) AS priority
          FROM
            attributes
          WHERE
            NOT attributes.isDeleted
            AND attributes.name = 'readingPriority'
        ) AS Priority USING (noteId)
        LEFT JOIN (
          SELECT
            attributes.noteId,
            attributes.value AS finishedReading
          FROM
            attributes
          WHERE
            NOT attributes.isDeleted
            AND attributes.name = 'finishedReading'
        ) AS Finished USING (noteId)
        ORDER BY priority ASC
      `);
      return rows;
    }, []);
    const promises = [];
    for (const row of rows) {
      const paperCell = $('<td>');
      const priorityCell = $('<td>');
      const priorityInput = $('<input type=number>').val(row.priority);
      priorityInput.change(() => {
        const newPriority = priorityInput.val();
        console.log(newPriority, typeof (newPriority));

        if (newPriority === '') {
          // TODO: deprioritize
        } else if (typeof (newPriority === 'string')) {
          console.log(`setting priority of ${row.noteId} to ${newPriority}`);
        }
      });

      promises.push(api.createNoteLink(
                           row.noteId, {showTooltip: true, showNoteIcon: true})
                        .then(paperLink => {
                          paperCell.append(paperLink);
                        }));
      priorityCell.append(priorityInput);
      // priorityCell.append(row.priority);
      const rowElement = $('<tr>').append(paperCell).append(priorityCell);
      this.$paperList.append(rowElement);
    }
    return Promise.all(promises);
  }

  async render(root) {
    this.$root = root;
    this.$root.empty().append($(TPL));
    this.$paperList = this.$root.find('.paper-list');

    await this.fillPaperList();
  }
}

const paperTable = new PaperTable();
await paperTable.render($('#paper-table-root'));
