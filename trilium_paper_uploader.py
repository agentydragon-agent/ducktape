import requests
from absl import app
from absl import flags
from tqdm.auto import tqdm

_ROOT = flags.DEFINE_string('root', 'http://localhost:37840', "ETAPI root URL")
_TOKEN = flags.DEFINE_string('token', None, 'ETAPI token')

# response = requests.patch(
#     f'{root}/etapi/notes/{note_id}',
#     json={
#         'type': 'file',
#         'mime': 'application/pdf',
#         # 'type': 'image',
#         # 'mime': 'image/png',
#     },
# )


def main(_):
    token = _TOKEN.value
    root = _ROOT.value
    headers = {'Authorization': token}
    response = requests.get(
        f'{root}/etapi/notes',
        params={'search': '~type.title = Paper'},
        headers=headers,
    )
    results = response.json()

    for result in tqdm(results['results']):
        note_id = result['noteId']
        title = result['title']
        arxiv_id = None

        if title == 'Paper template':
            # TODO: skip somehow?
            continue

        for attribute in result['attributes']:
            # print(attribute)
            if attribute['name'] == 'arxivId':
                arxiv_id = attribute['value']
                continue
            # TODO: also accept arxivLink attribute
            # TODO: migrate arxivLink -> arxivId

        if arxiv_id is None:
            print(note_id, title, 'skipping, no arxiv id')
            continue

        # print(result['attributes'])
        # find: 'arxivLink', 'arxivId'
        children = result['childNoteIds']

        paper_found = False
        for child_id in children:
            response = requests.get(
                f'{root}/etapi/notes/{child_id}',
                headers={
                    'Authorization': token,
                },
            )
            child_note = response.json()
            if (child_note['type'] == 'file'
                    and child_note['mime'] == 'application/pdf'):
                paper_found = True
                pass

        if paper_found:
            print(note_id, arxiv_id, title, 'skipping, PDF already in Trilium')
            continue

        print(result['noteId'], result['title'], arxiv_id,
              '-> upload the PDF to Trilium')

        # const ARXIV_ENDPOINT = 'https://export.arxiv.org/api/query';
        filename = f'{arxiv_id}.pdf'
        url = f'https://arxiv.org/pdf/{filename}'
        print(url)
        response = requests.get(url)
        assert response.status_code == 200
        pdf_bytes = response.content

        url = f'{root}/etapi/create-note'
        response = requests.post(
            url,
            json={
                "parentNoteId": note_id,
                "title": filename,
                "type": 'file',
                "mime": 'application/pdf',
                "content": "image",
            },
            headers=headers | {
                'content-type': 'application/json',
            },
        )
        new_note_id = response.json()['note']['noteId']
        # TODO: 'summary' element contains the abstract

        response = requests.put(
            f'{root}/etapi/notes/{new_note_id}/content',
            data=pdf_bytes,
            headers=headers | {
                'content-type': 'application/octet-stream',
                'Content-Transfer-Encoding': 'binary',
            },
        )
        assert response.status_code == 204

        print(f'-> uploaded PDF to note {new_note_id}')

        # TODO: get note, get content
        # print(result)
        # {'utcDateCreated', 'childBranchIds', 'dateModified', 'title',
        #  'isProtected', 'type', 'dateCreated', 'parentNoteIds',
        #  'parentBranchIds', 'utcDateModified'}
        # print(set(result.keys()))


if __name__ == '__main__':
    flags.mark_flag_as_required(_TOKEN.name)
    app.run(main)
