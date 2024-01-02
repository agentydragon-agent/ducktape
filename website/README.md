My homepage. Everything is CC BY-NC-SA 3.0.

It's hosted on my VPS. (Used to be on GitHub pages until ~2022-09-01.)

TODO: There is still a CI job building the site for GitLab pages. Maybe
sometime I'll figure out how to set up GitLab to deploy the website to
my webserver...

# Important linked URLs

URL                                     | purpose
----------------------------------------|--------
http(s)://agentydragon.com/found.html   | lost-and-found stickers
http(s)://agentydragon.com/nfc.html     | NFC armband

# Develop

To build:

```bash
sass css/default.scss > css/default.css
bazel build //website:site
cd website
../bazel-bin/website/site build
```

To push:

```bash
rsync -av --progress _site/ vps.agentydragon.com:/var/www/agentydragon.com
```

To convert a Jupyter notebook into Markdown:

```bash
sudo apt install jupyter-nbconvert
jupyter-nbconvert --to markdown --template basic <...>.ipynb
```

# Syntax highlighting

See: https://pandoc.org/MANUAL.html#syntax-highlighting

It uses [skylighting](https://github.com/jgm/skylighting) library under the hood.

```bash
pandoc --list-highlighted-languages
```

```bash
stack install --flag skylighting-core:executable skylighting-core
```

```bash
skylighting --help
```

# Upgrades

Might need:

```bash
stack upgrade
```

Maybe try to upgrade resolver in `stack.yaml`.
