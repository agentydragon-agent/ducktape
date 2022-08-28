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
        const {note, created} = await this.addPaper(paper);
        this.$message.html(await api.createNoteLink(
            note.noteId, {showTooltip: true, showNoteIcon: true}));
        if (created) {
          this.$message.prepend('Paper added as: ');
        } else {
          this.$message.prepend('Paper already exists as: ');
        }
        this.$input.val('');
      } catch (e) {
        this.$message.text('Error: ' + e.message);
      }
    });
    return this.$body;
  }

  async addPaper(paper) {
    // parse the paper ID from the input
    let paperId;
    if (/^\d{4}\.\d{4,5}$/.test(paper)) {
      paperId = paper;
    } else {
      const match = paper.match(
          /arxiv\.org\/(?:abs|pdf)\/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/);
      if (match) {
        paperId = match[1];
      } else {
        throw new Error('Invalid arXiv ID or URL.');
      }
    }

    // check if the paper already exists in Trilium
    const existingPaper = await this.findNoteByPaperId(paperId);
    if (existingPaper) {
      return {note: existingPaper, created: false};
    }

    // fetch the paper metadata from arXiv
    const meta = await this.getPaperMeta(paperId);

    // create a new note for the paper on the backend
    const papersRoot = await this.getPapersRootNoteId();
    return await api.runOnBackend(
        function(papersRootNoteId, title, paperId, paperTemplateNoteId) {
          const newNote = api.createTextNote(
                                 papersRootNoteId, title,
                                 'auto-created for paper ID ' + paperId)
                              .note;
          newNote.addAttribute('relation', 'template', paperTemplateNoteId);
          newNote.addAttribute('label', 'arxivId', paperId);
          return {note: newNote, created: true};
        },
        [papersRoot.noteId, meta.title, paperId, PAPER_TEMPLATE_NOTE_ID]);
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
