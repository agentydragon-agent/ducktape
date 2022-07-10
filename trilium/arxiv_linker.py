# TODO: add acknowledgement:
# Thank you to arXiv for use of its open access interoperability.

# Ideally I'd like for the data to actually live in Solid / Linked Data,
# so I don't have to store my own local copy of the citation graph. Oh well...
#
# Let's just improve my current workflow... Ugh.

import re
from urllib.parse import urlencode
from trilium_py.client import ETAPI
import requests
import feedparser

from absl import app
from absl import flags
from absl import logging

_ETAPI_TOKEN = flags.DEFINE_string("etapi_token", None, "Trilium ETAPI token")
_SERVER_URL = flags.DEFINE_string("server_url", "http://127.0.0.1:37840",
                                  "Trilium ETAPI endpoint")
_ADD = flags.DEFINE_list("add", [], "Papers to add (URLs or IDs)")

_ARXIV_ENDPOINT = 'https://export.arxiv.org/api/query'
_PAPER_TEMPLATE_NOTE_ID = 'WgCQiTGFyKV7'

# workflows:
#   - given paper URL:
#     - is it in my database?
#       - look up by name
#       - (TODO: maybe by arxiv id first?)
#     - if not, add it


def sanitize_title(title):
    #'Outrageously Large Neural Networks: The Sparsely-Gated\n  Mixture-of-Experts Layer'
    title = re.sub(r'\s+', ' ', title.replace('\n', ' '))
    title = title.strip()
    return title


def get_paper_arxiv(paper_id):
    paper_ids = [paper_id]
    url = _ARXIV_ENDPOINT + '?' + urlencode({'id_list': ','.join(paper_ids)})
    feed = feedparser.parse(url)
    assert len(feed['entries']) > 0
    assert len(feed['entries']) == 1
    return feed['entries'][0]


def upload_paper_pdf(ea, paper_id):
    existing_paper = find_note_by_paper_id(ea, paper_id)
    assert len(existing_paper['childNoteIds']
               ) == 0, "existing paper has some children already"
    assert existing_paper is not None
    pdf_url = get_paper_meta(paper_id)['pdf']
    # TODO: check that the page has no children
    logging.info("downloading pdf: %s", pdf_url)
    pdf_bytes = requests.get(pdf_url).content
    logging.info("pdf downloaded for %s", paper_id)
    etapi_upload_pdf(
        ea,
        parentNoteId=existing_paper['noteId'],
        title=f"{paper_id}.pdf",
        data=pdf_bytes,
    )
    logging.info("pdf uploaded for %s", paper_id)


def etapi_upload_pdf(
    ea,
    parentNoteId: str,
    title: str,
    data: bytes,
    mime: str = 'application/pdf',
):
    # from https://github.com/Nriver/trilium-py/blob/2a5e45103269756e3d7c9badaa74ca9c22a77e1d/src/trilium_py/client.py#L121=
    url = f'{ea.server_url}/etapi/create-note'
    params = {
        "parentNoteId": parentNoteId,
        "title": title,
        "type": "file",
        "mime": mime,
        "content": data,
    }
    #"qabtenDuUntp"
    res = requests.post(url,
                        json=params,
                        headers={
                            'content-type': 'application/json',
                            'Authorization': ea.token,
                        })
    print(res.json())


#    new_noteId = res.json()['note']['noteId']
#
#    # set file name
#    #image_file_name = os.path.basename(image_file)
#    #ea.create_attribute(attributeId=None,
#    #                      noteId=new_noteId,
#    #                      type='label',
#    #                      name='originalFileName',
#    #                      value=image_file_name,
#    #                      isInheritable=False)
#
#    # upload image, set note content
#    url = f'{ea.server_url}/etapi/notes/{new_noteId}/content'
#    #image_data = open(image_file, 'rb').read()
#    # content-type here will effect the result
#    # not working, encoding issue? automated force encoding to utf-8 and lost data
#    res = requests.put(
#        url,
#        data=data,
#        # headers={'content-type': 'text/plain', 'Authorization': ea.token, })
#        headers={
#            #'content-type': 'application/stream',
#            'content-type': mime,
#            'Content-Transfer-Encoding': 'binary',
#            'Authorization': ea.token,
#        })
#    if res.status_code == 204:
#        return True
#    return False


def get_paper_meta(paper_id):
    """
    Args:
       paper_id: Paper ID on Arxiv, like "1701.06538"
    """

    entry = get_paper_arxiv(paper_id)
    logging.info("got arxiv entry for %s", paper_id)
    # >>> f['entries'][0].keys()
    # dict_keys(['id', 'guidislink', 'link', 'updated', 'updated_parsed', 'published', 'published_parsed', 'title', 'title_detail', 'summary', 'summary_detail', 'authors', 'author_detail', 'author', 'links', 'arxiv_primary_category', 'tags'])
    # >>> f['entries'][0]['published']
    # '2017-01-23T18:10:00Z'
    # >>> f['entries'][0]['authors']
    # [{'name': 'Noam Shazeer'}, {'name': 'Azalia Mirhoseini'}, ...]
    # >>> f['entries'][0]['summary']
    title = sanitize_title(entry['title'])
    logging.info('sanitized title: %s', repr(title))

    #>>> d['links']
    #[{'href': 'http://arxiv.org/abs/2206.07694v1', 'rel': 'alternate', 'type': 'text/html'}, {'title': 'pdf', 'href': 'http://arxiv.org/pdf/2206.07694v1', 'rel': 'related', 'type': 'application/pdf'}]
    pdfs = {
        link['href']
        for link in entry['links']
        if link['rel'] == 'related' and link['type'] == 'application/pdf'
    }
    assert len(pdfs) == 1, str(pdfs)
    #print(f['entries'][0]['summary'])

    return {'title': title, 'pdf': next(iter(pdfs))}

    # if paper does not exist: download its title, create new page under #papersRoot

    # Semantic Scholar API: https://www.semanticscholar.org/product/api
    #url = f'https://api.semanticscholar.org/graph/v1/paper/arXiv:{paper_id}'
    #semantic_scholar_paper_id = requests.get(url)['paperId']  # also ['title']
    # citation graph:
    # https://api.semanticscholar.org/graph/v1/paper/649def34f8be52c8b66281af98ae884c09aef38b?fields=title,citations.paperId,citations.title,citations.authors,references.title,references.paperId,references.title,references.authors,externalIds
    # https://api.semanticscholar.org/graph/v1/author/145612610?fields=papers.authors


def find_note_by_paper_id(ea, paper_id):
    # TODO: check format - against escapes
    res = ea.search_note(search=f"#arxivId = '{paper_id}'")

    if len(res['results']) == 0:
        return None

    assert len(res['results']) == 1
    return res['results'][0]


def find_note_id_by_paper_id(ea, paper_id):
    note = find_note_by_paper_id(ea, paper_id)
    if note:
        return note['noteId']
    else:
        return None


def create_paper_if_not_exists(ea, paper_id):
    # try to find paper by arxiv id
    existing_paper = find_note_id_by_paper_id(ea, paper_id)
    if existing_paper is not None:
        logging.info("paper %s already in Trilium as %s", paper_id,
                     existing_paper)
        return

    # try to find paper by title
    meta = get_paper_meta(paper_id)
    title = meta['title']
    existing_paper = find_note_id_by_title(ea, title)
    if existing_paper is not None:
        logging.info("paper %s already in Trilium as %s", paper_id,
                     existing_paper)
        return

    # create new paper
    papers_root = get_papers_root_note_id(ea)
    res = ea.create_note(
        parentNoteId=papers_root,
        title=title,
        type="text",
        content=f"auto-created for paper ID {paper_id}",
    )
    # error: {'status': 500, 'code': 'GENERIC', 'message': 'Note content must be set'}

    print(res)
    new_note_id = res['note']['noteId']
    logging.info(f"{new_note_id = }")
    res = ea.create_attribute(
        attributeId='',
        type='relation',
        noteId=new_note_id,
        name='template',
        value=_PAPER_TEMPLATE_NOTE_ID,
        isInheritable=False,
    )
    logging.info("created attribute: %s", res)
    res = ea.create_attribute(
        attributeId='',
        type='label',
        noteId=new_note_id,
        name='arxivId',
        value=paper_id,
        isInheritable=False,
    )
    logging.info("created attribute: %s", res)
    # populates ~template, #arxivId.
    # TODO: add citations, authors, arxivLink. download and add PDF.

    existing_paper = find_note_id_by_title(ea, title)
    assert existing_paper is not None, "can't find just created paper"


# TODO: populate citation graph?


def get_papers_root_note_id(ea):
    res = ea.search_note(search='#papersRoot')
    assert len(res['results']) == 1
    note_id = res['results'][0]['noteId']
    logging.info("papers root = %s", note_id)
    return note_id


def find_note_id_by_title(ea, title):
    res = ea.search_note(search=title)

    if len(res['results']) == 0:
        return None

    # if multiple search results, should have exactly 1 matching
    matching = {r['noteId'] for r in res['results'] if r['title'] == title}
    if len(matching) == 0:
        return None

    assert len(matching) == 1, f'multiple matches for {repr(title)}'
    return next(iter(matching))
    # TODO check title


def main(_):
    # Token for my scripts:
    ea = ETAPI(_SERVER_URL.value, _ETAPI_TOKEN.value)
    if _ADD.value:
        logging.info("Adding papers from --add flag")
        for paper in set(_ADD.value):
            if re.fullmatch('\d{4}\.\d{5}', paper):
                paper_id = paper
            else:
                m = re.fullmatch('https://arxiv.org/abs/(.*)(v\d+)?', paper)
                if m:
                    paper_id = m.group(1)
                else:
                    raise Exception(f"unhandled: {paper}")

            create_paper_if_not_exists(ea, paper_id)

    # TODO: does not work - unclear how to properly do this in ETAPI
    # upload_paper_pdf(ea, '2206.02231')


#    res = ea.search_note(search="python", )
#
#    print(res)
#    for x in res['results']:
#        print(x['noteId'], x['title'])
"""
~template=Paper template
#arxivLink="https://arxiv.org/abs/1701.06538"
#readingPriority=0
#readingPriorityDate=2022-05-03
~topic=Architecture
~citedBy=Language Models are Few-Shot Learners
#arxivId=1701.06538

ea.get_note_content("note1") -> ...
ea.get_note(note_id) -> ...
ea.update_note_content("note1", "updated by python") -> ...
ea.patch_note(
    noteId="note1",
    title="Python client moded",
)
es.get_day_note("2022-02-25")  # get today's note

def get_attribute(self, attributeId: str) -> dict:
def create_attribute(self, attributeId: str, noteId: str, type: str, name: str, value: str,
                     isInheritable: bool) -> dict:
def patch_attribute(self, attributeId: str, value: str) -> dict:
def delete_attribute(self, attributeId: str) -> bool:
"""

if __name__ == '__main__':
    flags.mark_flag_as_required(_ETAPI_TOKEN.name)
    app.run(main)
