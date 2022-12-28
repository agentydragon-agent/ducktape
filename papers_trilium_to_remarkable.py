"""
On first run:
    docker run -v $HOME/.config/rmapi/:/home/app/.config/rmapi/ -it rmapi

This will pair the device to Remarkable API so that we can upload later.

- create directory of synced papers (or maybe download based on Trilium db)
"""

import requests
from absl import app
from absl import flags
from tqdm.auto import tqdm
import subprocess
import os

from typing import Optional

from xdg import xdg_cache_home

# put book.pdf /books

_ETAPI_URL = flags.DEFINE_string('etapi_url', 'http://localhost:37840',
                                 "ETAPI root URL")
_TOKEN = flags.DEFINE_string('token', None, 'ETAPI token')
SYNCED_DIR_PATH = (xdg_cache_home() / 'papers_trilium_to_remarkable' /
                   'synced_dir')
REMARKABLE_SIDE_PATH = '/papers_trilium_to_remarkable'


def find_attribute_value_in_result(result, attribute_name):
    for attribute in result['attributes']:
        if attribute['name'] == attribute_name:
            return attribute['value']
    raise KeyError()


def populate_synced_dir():
    token = _TOKEN.value
    root = _ETAPI_URL.value
    headers = {'Authorization': token}

    SYNCED_DIR_PATH.mkdir(exist_ok=True, parents=True)

    # Search for all papers in Trilium, and their attached PDFs.
    response = requests.get(
        f'{root}/etapi/notes',
        params={'search': '~type.title = Paper'},
        headers=headers,
    )
    results = response.json()

    # Sort results by ascending priority.
    def get_result_priority(result):
        try:
            priority = find_attribute_value_in_result(
                result, attribute_name='readingPriority')
        except KeyError:
            return 200  # unprioritized go last

        try:
            return int(priority)
        except ValueError:
            return 200  # badly prioritized, go last

    results = list(sorted(results['results'], key=get_result_priority))

    for result in tqdm(results):
        priority = get_result_priority(result)
        note_id = result['noteId']
        title = result['title']

        if title == 'Paper template':
            # TODO: skip somehow?
            continue

        children = result['childNoteIds']
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
                break
        else:
            print('no PDF found, skip')
            continue

        print(f'found: ')
        response = requests.get(
            f'{root}/etapi/notes/{child_id}',
            headers=headers,
        )
        # TODO: split apart stuff I finished reading / did not finish reading
        filename = ''
        try:
            arxiv_id = find_attribute_value_in_result(result,
                                                      attribute_name='arxivId')
            filename += f'{arxiv_id} '
        except KeyError:
            pass
        filename += title
        filename = (filename.replace('/', '-').replace('?', '-').replace(
            ' ', '_').replace('(', '_').replace(')', '_'))
        filename += '.pdf'
        path = SYNCED_DIR_PATH / filename
        response = requests.get(
            f'{root}/etapi/notes/{child_id}/content',
            headers=headers,
        )
        assert response.status_code == 200
        with open(path, 'wb') as f:
            f.write(response.content)
        print(f'{title} {child_id} written to {path}')


def make_args(*args):
    return [
        'docker', 'run', '-v',
        '/home/agentydragon/.config/rmapi/:/home/app/.config/rmapi/', 'rmapi',
        *args
    ]


def upload_synced_dir():
    subprocess.check_call(make_args('mkdir', REMARKABLE_SIDE_PATH))
    # TODO: if 'entry already exists' in stdout -> ok, skip it
    print('mkdir ok')

    existing = subprocess.check_output(make_args(
        'ls', REMARKABLE_SIDE_PATH)).decode('utf-8')
    existing_filenames = set()
    for line in existing.splitlines():
        assert line.startswith('[f]\t')
        _marker, filename = line.split('\t')
        existing_filenames.add(filename)

    # TODO: list the directory on remarkable side, skip entries that are already
    # uploaded
    for p in os.listdir(SYNCED_DIR_PATH):
        if p.split('.')[0] in existing_filenames:
            print(f'{p} already uploaded apparently')
            continue
        # TODO: skip those that already exist in Remarkable; warn if there are
        # items we don't know about.
        #print(p)
        # uploading: [/home/app/synced_dir/2110.01548_Uncertainty-Based_Offline_Reinforcement_Learning_with_Diversified_Q-Ensemble.pdf]...OK
        args = make_args(
            'put',
            f'/home/app/synced_dir/{p}',
            REMARKABLE_SIDE_PATH,
        )
        #args = [
        #    'bash',
        #    '-c',
        #    (
        #        # TODO: compose command with shlex
        #        'docker run '
        #        '-v /home/agentydragon/.config/rmapi/:/home/app/.config/rmapi/ '  # TODO hardcoded xdg path
        #        f'-v {SYNCED_DIR_PATH}:/home/app/synced_dir/ '
        #        f'rmapi put /home/app/synced_dir/{p} {REMARKABLE_SIDE_PATH}'),
        #]
        # this seems to work:
        # docker run -v /home/agentydragon/.config/rmapi/:/home/app/.config/rmapi/ -v /home/agentydragon/.cache/papers_trilium_to_remarkable/synced_dir:/home/app/synced_dir/ rmapi put /home/app/synced_dir/2205.12910_NaturalProver:_Grounded_Mathematical_Proof_Generation_with_Language_Models.pdf /papers_trilium_to_remarkable
        print(args)
        sp = subprocess.run(args, capture_output=True)

        if sp.returncode == 0:
            print('ok')
            continue
        if sp.returncode == 1 and b'entry already exists' in sp.stderr:
            print('already exists')
            continue
        # Print the standard output of the command
        print(f'{sp.stdout = }')
        # Print the standard error of the command
        print(f'{sp.stderr = }')
        raise "unhandled"


def purge_remarkable_synced_dir():
    existing = subprocess.check_output(make_args(
        'ls', REMARKABLE_SIDE_PATH)).decode('utf-8')
    for line in existing.splitlines():
        assert line.startswith('[f]\t')
        print(line)
        _, p = line.split('\t')
        args = make_args(
            'rm',
            f'{REMARKABLE_SIDE_PATH}/{p}',  #.pdf',
        )
        print(args)
        subprocess.check_call(args)


def main(_):
    purge_remarkable_synced_dir()
    # populate_synced_dir()
    # upload_synced_dir()


if __name__ == '__main__':
    flags.mark_flag_as_required(_TOKEN.name)
    app.run(main)
