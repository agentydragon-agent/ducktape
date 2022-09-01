/**
 * To install, add as frontend script and add #widget.
 */

const TPL = `<div>
  <input type="text" id="arxiv-input" placeholder="arXiv ID or URL" style="width: 80%;">
  <button id="arxiv-submit">Add</button>
  <output id="arxiv-message" style="color: var(--main-text-color);"></output>
</div>`;

const ARXIV_ENDPOINT = 'https://export.arxiv.org/api/query';
const PAPER_TEMPLATE_NOTE_ID = 'WgCQiTGFyKV7';
const PAPERS_ROOT_LABEL = 'papersRoot';

class ArxivWidget extends api.CollapsibleWidget {
  get position() {
    return 20;
  }
  get parentWidget() {
    return 'right-pane';
  }
  get widgetTitle() {
    return 'Add arXiv paper';
  }

  async doRenderBody() {
    this.$body.empty().append($(TPL));
    this.$input = this.$body.find('#arxiv-input');
    this.$submit = this.$body.find('#arxiv-submit');
    this.$message = this.$body.find('#arxiv-message');

    // Make message disappear when URL is updated.
    this.$input.on('input', () => this.$message.text(''));

    this.$submit.on('click', async () => {
      const paper = this.$input.val().trim();
      if (!paper) {
        this.$message.text('Please enter a valid arXiv ID or URL.');
        return;
      }
      try {
        this.$message.text('Adding paper...');
        await this.addPaper(paper);
      } catch (e) {
        this.$message.text('Error: ' + e.message + ' ' + e.stack);
      }
    });
    return this.$body;
  }

  async addPaper(paper) {
    // parse the paper ID from the input
    let paperId = this.parsePaperId(paper);

    // check if the paper already exists in Trilium
    const existingPaper = await this.findNoteByPaperId(paperId);
    if (existingPaper) {
      await this.showExistingPaperMessage(existingPaper);
      return;
    }

    // fetch the paper metadata from arXiv
    const meta = await this.getPaperMeta(paperId);

    // search for notes with similar titles
    const title = meta.title;
    // TODO: maybe show links to all similar pages, not just one
    // TODO: maybe search fuzzily, skipping individual words
    const results = await api.searchForNotes(title);
    if (results.length > 0) {
      // show a message with a link to the note and a confirmation button
      await this.showSimilarNotesMessage(title, results, paperId);
      return;
    }

    // create a new note for the paper on the backend
    let newNote = await this.addNoteToBackend(title, paperId);
    await this.showNewPaperMessage(newNote);
  }

  parsePaperId(paper) {
    if (/^\d{4}\.\d{4,5}$/.test(paper)) {
      return paper;
    } else {
      const match = paper.match(
          /arxiv\.org\/(?:abs|pdf)\/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/);
      if (match) {
        return match[1];
      } else {
        throw new Error('Invalid arXiv ID or URL.');
      }
    }
  }

  async showExistingPaperMessage(existingPaper) {
    this.$message.text('Paper already exists as: ');
    const noteLink = await api.createNoteLink(
        existingPaper.noteId, {showTooltip: true, showNoteIcon: true});
    this.$message.append(noteLink);
  }

  async showSimilarNotesMessage(title, results, paperId) {
    this.$message.text(
        results.length + ' notes with similar title found, first one is: ');
    this.$message.append(await api.createNoteLink(
        results[0].noteId, {showTooltip: true, showNoteIcon: true}));
    this.$message.append(
        '<button id="arxiv-add-to-existing">Link existing page to ArXiv</button>');
    this.$body.find('#arxiv-add-to-existing').on('click', async () => {
      // add the paper ID attribute to the existing note
      await api.runOnBackend(function(noteId, paperId) {
        const note = api.getNote(noteId);
        note.addLabel('arxivId', paperId);
      }, [results[0].noteId, paperId]);
      this.$message.html(await api.createNoteLink(
          results[0].noteId, {showTooltip: true, showNoteIcon: true}));
      this.$message.prepend('Paper ID added to: ');
      this.$input.val('');
    });
    this.$message.append(
        '<br>Confirm to create a new note anyway: ' +
        '<button id="arxiv-confirm">Confirm</button>');
    this.$body.find('#arxiv-confirm').on('click', async () => {
      // create the note as usual
      let newNote = await this.addNoteToBackend(title, paperId);
      this.showNewPaperMessage(newNote);
    });
  }

  async showNewPaperMessage(newNote) {
    this.$message.text('Paper added as: ');
    this.$message.append(await api.createNoteLink(
        newNote.noteId, {showTooltip: true, showNoteIcon: true}));
  }

  async addNoteToBackend(title, paperId) {
    const papersRoot = await this.getPapersRootNoteId();
    // Will run on backend
    const backendFn =
        (papersRootNoteId, title, paperId, paperTemplateNoteId) => {
          const newNote = api.createTextNote(
                                 papersRootNoteId, title,
                                 'auto-created for paper ID ' + paperId)
                              .note;
          newNote.addRelation('template', paperTemplateNoteId);
          newNote.addLabel('arxivId', paperId);
          return newNote;
        };
    const newNote = await api.runOnBackend(
        backendFn, [papersRoot.noteId, title, paperId, PAPER_TEMPLATE_NOTE_ID]);
    return newNote;
  }

  async findNoteByPaperId(paperId) {
    // search for notes with the arxivId label
    const results = await api.searchForNotes('#arxivId = "' + paperId + '"');
    if (results.length > 0) {
      return results[0];
    } else {
      return null;
    }
  }

  async getPaperMeta(paperId) {
    // query the arXiv API for the paper details
    const url = ARXIV_ENDPOINT + '?' + $.param({id_list: paperId});
    const response = await $.get(url);
    const xml = response;
    const entry = $(xml).find('entry');
    if (entry.length > 0) {
      const title = this.sanitizeTitle(entry.find('title').text());
      return {title};
    } else {
      throw new Error('Paper not found on arXiv.');
    }
  }

  sanitizeTitle(title) {
    // remove extra whitespace and line breaks from the title
    return title.replace(/\s+/g, ' ').trim();
  }

  async getPapersRootNoteId() {
    // search for the note with the papersRoot label
    const results = await api.searchForNotes('#' + PAPERS_ROOT_LABEL);
    if (results.length > 0) {
      return results[0];
    } else {
      throw new Error('Papers root note not found.');
    }
  }
}

module.exports = new ArxivWidget();
