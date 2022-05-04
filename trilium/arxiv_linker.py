from trilium_py.client import ETAPI

from absl import app
from absl import flags

_ETAPI_TOKEN = flags.DEFINE_string("etapi_token", None, "Trilium ETAPI token")
_SERVER_URL = flags.DEFINE_string("server_url", "http://127.0.0.1:37840",
                                  "Trilium ETAPI endpoint")


def main(_):
    # Token for my scripts:
    ea = ETAPI(_SERVER_URL.value, _ETAPI_TOKEN.value)
    res = ea.search_note(search="python", )

    print(res)
    for x in res['results']:
        print(x['noteId'], x['title'])


"""
~template=Paper template
#arxivLink="https://arxiv.org/abs/1701.06538"
#readingPriority=0
#readingPriorityDate=2022-05-03
~topic=Architecture
~citedBy=Language Models are Few-Shot Learners
#arxivId=1701.06538

res = ea.create_note(
    parentNoteId="root",
    title="Simple note 1",
    type="text",
    content="Simple note example",
    noteId="note1"
)
-> noteId = res['note']['noteId']

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
