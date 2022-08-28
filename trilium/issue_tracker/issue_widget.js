/**
 * Issue widget. For issue notes, allows changing state and shows attached
 * hotlists.
 */

const TPL = `<div>
  <div id="issue-state-buttons"></div>
  <ul id="issue-hotlists"></ul>
</div>`;

class IssueWidget extends api.CollapsibleWidget {
  get position() {
    return 100;
  }
  get parentWidget() {
    return 'right-pane';
  }
  get widgetTitle() {
    return 'Issue';
  }

  isEnabled() {
    return super.isEnabled() && this.note.type === 'text' &&
        this.note.hasLabel('issue');
  }

  async doRenderBody() {
    this.$body.empty().append($(TPL));
    this.$stateButtons = this.$body.find('#issue-state-buttons');
    this.$hotlists = this.$body.find('#issue-hotlists');
    return this.$body;
  }

  async setState(stateId) {
    await api.runOnBackend(async (noteId, stateId) => {
      const note = await api.getNote(noteId);
      note.setRelation('state', stateId);
    }, [this.note.noteId, stateId]);
  }

  async getStatesRootNoteId() {
    const results = await api.searchForNotes('#issueStatesRoot');
    if (results.length > 0) {
      return results[0];
    } else {
      throw new Error('Issue states root note not found.');
    }
  }

  async refreshWithNote(note) {
    const statesRoot = await this.getStatesRootNoteId();
    const stateNoteIds = statesRoot.getChildNoteIds();
    this.$stateButtons.empty();
    const currentState = await note.getRelationTarget('state');
    const currentStateId = currentState ? currentState.noteId : null;
    for (const stateNoteId of stateNoteIds) {
      const stateNote = await api.getNote(stateNoteId);
      const button = $('<button></button>');
      button.text(stateNote.title);
      button.data('state-id', stateNoteId);
      button.on('click', async () => {
        await this.setState(button.data('state-id'));
      });
      if (stateNote.hasLabel('issueIcon')) {
        const icon = $('<i></i>');
        icon.addClass(stateNote.getLabel('issueIcon').value);
        button.prepend(icon);
      }
      if (currentStateId === stateNoteId) {
        button.prop('disabled', true);
      }
      this.$stateButtons.append(button);
    }

    this.$hotlists.empty();
    const hotlistRelations = note.getRelations('hotlist');
    for (const hotlistRelation of hotlistRelations) {
      const hotlistNote = await api.getNote(hotlistRelation.value);
      if (hotlistNote) {
        const listItem = $('<li></li>');
        listItem.append(await api.createNoteLink(
            hotlistNote.noteId, {showTooltip: true, showNoteIcon: true}));
        this.$hotlists.append(listItem);
      }
    }
  }

  async entitiesReloadedEvent({loadResults}) {
    if (loadResults.isNoteContentReloaded(this.noteId) ||
        loadResults.getAttributes().find(
            attr => attr.type === 'relation' &&
                (attr.name === 'state' || attr.name == 'hotlist'))) {
      this.refresh();
    }
  }
}

module.exports = new IssueWidget();
