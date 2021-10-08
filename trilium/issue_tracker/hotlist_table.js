function getAllHotlists() {
  return api.runOnBackend(() => {
    const notes = api.searchForNotes('#hotlist');
    return notes.map(note => {
      return {'noteId': note.noteId, 'title': note.title};
    });
  });
}

function searchIssues(hotlistId) {
  let searchString = '#issue';
  // Open only
  searchString += ' ~state.title=Open';
  if (hotlistId) {
    searchString += ' ~hotlist.noteId=' + hotlistId;
  }

  return api.runOnBackend((searchString) => {
    const notes = api.searchForNotes(searchString);
    return notes.map(note => {
      return {'noteId': note.noteId, 'title': note.title};
    });
  }, [searchString]);
}

function getAllIssues() {
  return searchIssues(null);
}

function getIssuesInHotlist(hotlistId) {
  return searchIssues(hotlistId);
}

function makeIssueLink(note) {
  return $('<a href="#">')
      .text(note.title)
      .click(() => api.activateNote(note.noteId));
}

async function populateHotlistTable() {
  // List all hotlists.
  const list2 = $('<ul>');
  for (const note of await getAllHotlists()) {
    const item = $('<li>');
    item.attr('data-hotlist-id', note.noteId);
    const link = $('<a href="#">')
                     .text(note.title)
                     .click(() => activateHotlist(note.noteId));
    item.append(link);
    list2.append(item);
  }
  $('#hotlist-table').append(list2);
}

async function populateAllIssues() {
  // List all issues all hotlists.
  const root = $('#issue-table');
  root.empty();
  const list = $('<ul>');
  for (const note of await getAllIssues()) {
    const item = $('<li>');
    item.append(makeIssueLink(note));
    list.append(item);
  }
  root.append(list);
}

async function activateHotlist(hotlistId) {
  $('[data-hotlist-id]').removeClass('active');
  $('[data-hotlist-id=' + hotlistId + ']').addClass('active');
  console.log('activateHotlist(', hotlistId, ')');
  const root = $('#issue-table');
  root.empty();
  const list = $('<ul>');
  for (const note of await getIssuesInHotlist(hotlistId)) {
    const item = $('<li>');
    item.append(makeIssueLink(note));
    list.append(item);
  }
  root.append(list);
}

await populateHotlistTable();
await populateAllIssues();

/*
const datasets = [
    {
        label: "Weight (kg)",
        backgroundColor: 'red',
        borderColor: 'red',
        data: days.map(day => day.weight),
        fill: false,
        spanGaps: true,
        datalabels: {
            display: false
        }
    }
];

return {
    datasets: datasets,
    labels: days.map(day => day.date)
};

const ctx = $("#canvas")[0].getContext("2d");

new chartjs.Chart(ctx, {
    type: 'line',
    data: await getChartData()
});
*/
