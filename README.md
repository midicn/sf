# midicn · sf

Frozen public site source, batch `midicn-1.2.0-20261102`, private core `1.2.0`.

HTML and UI are built locally from the private core. This repository contains
runtime files plus a small standard-library byte assembler. CI validates every
file against `file-manifest.json`, retrieves immutable release materials, and
publishes `_artifact/` to GitHub Pages. It does not render or modify business data.

Run `python3 tools/assemble_release.py --source . --output _artifact` to reproduce
the published artifact. Original media rights and attribution remain as stated
on the site; code is MIT and metadata is CC BY 4.0 where explicitly indicated.
Do not edit generated HTML or copy private source/credentials into this repo.
