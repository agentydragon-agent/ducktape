// Hotlist sidebar widget.

const TPL = `
<div style="contain: none; padding: 10px; border-top: 1px solid var(--main-border-color);">
  Open issues in this hotlist:
  <ul class="hotlist-issue-list">
  </ul>
</div>`;

class HotlistSidebarWidget extends api.TabAwareWidget {
  get position() {
    // higher value means position towards the bottom/right
    // 10 in right pane seems to put it just below "Note info"
    return 10;
  }

  get parentWidget() {
    return 'right-pane';
  }

  doRender() {
    this.$widget = $(TPL);
    this.$issueList = this.$widget.find('.hotlist-issue-list');
    return this.$widget;
  }

  async refreshWithNote(note) {
    if (note.type !== 'text' || !note.hasLabel('hotlist')) {
      this.toggleInt(false);  // hide
      return;
    }
    this.toggleInt(true);
    let searchString = '#issue';
    // open issues only
    searchString += ' ~state.title=Open';
    searchString += ' ~hotlist.noteId=' + note.noteId;

    console.log('search string:', searchString);
    let issueNotes = await api.searchForNotes(searchString);
    this.$issueList.empty();
    for (const issueNote of issueNotes) {
      const bullet = $('<li>');
      bullet.append(
          await api.createNoteLink(issueNote.noteId, {showTooltip: true}));
      this.$issueList.append(bullet);
    }
    // const {content} = await note.getNoteComplement();
  }

  async entitiesReloadedEvent({loadResults}) {
    // TODO: how about changes elsewhere...? is that included?
    if (loadResults.isNoteContentReloaded(this.noteId)) {
      this.refresh();
    }
  }
}

module.exports = new HotlistSidebarWidget();
