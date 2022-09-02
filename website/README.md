My homepage. Everything is CC BY-NC-SA 3.0.

To build:

```bash
sass css/default.scss > css/default.css
stack build
stack exec site build
```

To push:

```bash
# from repo root
git subtree push \
  --prefix website/_site \
  git@github.com:agentydragon/agentydragon.github.io master
```

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
