import requests
from absl import app
from absl import flags

_TOKEN = flags.DEFINE_string('token', None, 'ETAPI token')


def upload_pdf_to_note(*, token: str, note_id: str):
    # Token 2022-12-25
    ROOT = 'http://localhost:37840'
    response = requests.patch(
        f'{ROOT}/etapi/notes/{NOTE_ID}',
        json={
            'type': 'file',
            'mime': 'application/pdf',
            # 'type': 'image',
            # 'mime': 'image/png',
        },
        headers={
            'Authorization': token,
        },
    )
    print(response.status_code)
    print(response.text)

    image_data = open('/home/agentydragon/downloads/G3AXBY.pdf', 'rb').read()
    # content-type here will affect the result
    # not working, encoding issue? automated force encoding to utf-8 and lost data
    response = requests.put(
        f'{ROOT}/etapi/notes/{NOTE_ID}/content',
        data=image_data,
        headers={
            'content-type': 'application/octet-stream',
            'Content-Transfer-Encoding': 'binary',
            'Authorization': token,
        },
    )
    assert response.status_code == 204


def main(_):
    upload_pdf_to_note(token=_TOKEN.value, note_id='dMJJok9mKY7I')


if __name__ == '__main__':
    flags.mark_flag_as_required(_TOKEN.name)
    app.run(main)
