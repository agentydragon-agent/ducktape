#!/bin/sh
# The image ships no git identity and the Pod inherits none, so the first `git commit` fails with
# "Please tell me who you are" -- and for Haku that is the last step of a run, after the work. Set
# it before the clones, globally: the setup script and the harness share HOME (the runner forwards
# HOME), so one write covers commits made from either. Matches the identity haku-state's history is
# already written under.
git config --global user.name haku
git config --global user.email haku@allegedly.works
git clone --depth 1 --branch main --single-branch http://haku:agentplane-credential-forgejo-haku@forgejo-http.forgejo.svc.cluster.local:3000/haku/haku-state.git .
git clone --depth 1 --branch devel --single-branch https://github.com/agentydragon/ducktape.git ../ducktape
