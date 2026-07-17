# vault-graph

Render any Obsidian vault as a **single self-contained HTML file**: an
interactive, force-directed knowledge graph that works in any browser,
including on a phone. No dependencies, no network, no build step: one Python
script, one template.

It is more than a picture of the vault. Each node carries the note's text,
the real source file the note documents (matched by name, embedded in full),
and its history: created/updated dates and the last commit that touched the
note and the script. Tap a node and you can read the note, open the script,
download it, and see when and why it last changed, all offline, from one
file you can AirDrop to a phone. Wired to a pre-commit hook (below), the
graph regenerates itself on every commit, so it stays a live, browsable map
of the project rather than a snapshot.

## Requirements

- **Python ≥ 3.8, standard library only**: `argparse`, `json`, `os`, `re`,
  `subprocess`, `sys`, `time`. There is no `requirements.txt` because there
  is nothing to install; the stock macOS `python3` (3.9.6) is enough.
- **git is optional.** When it's on PATH and a file has committed history,
  nodes get real commit stamps; otherwise the tool falls back to filesystem
  dates and everything else works unchanged.
- The output HTML is equally dependency-free: no D3, no CDN, no network.
  The force simulation and renderer are inlined vanilla JS on a canvas.
- **Obsidian is not required to run the tool.** It reads the vault's `.md`
  files directly (Obsidian only matters for *writing* the vault). Developed
  and tested against a vault created with **Obsidian 1.12.7**; the parsed
  surface is stable, long-standing syntax (`[[wikilinks]]` with `|` aliases
  and `#headings`, YAML frontmatter `tags:`/`aliases:`) plus `.obsidian/`
  folder detection, so older/newer vaults should work unchanged.

```bash
python3 vault_graph.py                # auto-detect the vault in the cwd
python3 vault_graph.py /path/to/vault # or point it anywhere
```

With no argument the vault is found relative to the current directory, in
order: `./Vault` → the cwd itself if it contains `.obsidian` → the single
subfolder that contains `.obsidian` (several candidates = explicit error).
Nothing else is ever assumed about paths: sources are scanned relative to the
vault (`--src`), fallback links for non-embedded files are emitted relative
to the output file, and the HTML template is loaded from next to the script
itself.

## What it does

- Parses every `.md` note; the vault's **top-level folders become color groups**
  (validated colorblind-safe dark palette, assigned by group size).
- Resolves `[[wikilinks]]` in all their forms: `[[Note]]`, `[[Note|display]]`,
  `[[Note#heading]]`, frontmatter **aliases**, path-style links, and the
  table-escaped `[[Note\|display]]` form. Links to notes that don't exist yet
  show up as dashed "unresolved" ghost nodes, like Obsidian's graph view.
- Extracts each note's tags + first paragraph as a preview for the info panel.
- **Source linking**: a note named like a real file (`toggle.sh`,
  `dns-proxy.py`, `rule-compiler`, any language or none) gets a ⚙️ link to
  that file. Matching is by exact filename first, then by stem
  (`routing-fix` → `routing-fix.sh`), shallowest path wins, scanning `--src`
  (default: the vault's parent folder). This is a *heuristic*: it can't know
  that a note called "Sweep Protocol" documents `sweep.sh`; only name-shaped
  notes are linked automatically.
- **Dates & commit stamps**: every node shows when it was created and last
  updated: from `git log --follow` (rename-aware) when the file is committed,
  from filesystem dates (macOS birthtime) when it isn't, and the **earlier of
  the two wins**, so notes first committed long after they were written keep
  their true origin dates. Plus the last commit hash + subject for the note
  and for its linked source file. `--no-dates` turns this off.
- **Embeds file contents into the HTML itself**: notes and matched source
  files (text, up to `--max-embed` KB each) are inlined, so the 📝/⚙️ links
  open in an in-page viewer (with a download button) even when the HTML
  travels alone. Whatever can't be embedded (binary, oversized, a directory)
  falls back to a link relative to the output HTML, which works when the file
  sits in (or is served from) the repo the vault documents.

## Viewer features

Force layout pre-settles before first paint. Search (names, aliases, tags),
per-group legend filter chips, fit / zoom / label-mode / re-layout buttons,
tap-to-highlight neighborhoods, and an info panel with the note preview,
file links, and clickable outgoing/incoming links. On phones the panel is a
bottom sheet that opens **compact** (~30% of the screen); drag or tap its
handle to expand, swipe down to collapse or dismiss. File links open a
full-screen viewer showing the embedded content.

## Options

| flag | meaning |
| ---- | ------- |
| `VAULT` | vault folder (optional, auto-detected in cwd as described above) |
| `-o FILE` | output path (default `<vault>-graph.html` in cwd) |
| `--src DIR` | root scanned for source-file matches (default: vault's parent) |
| `--no-src` | disable source linking |
| `--title NAME` | header/brand title (default: vault folder name) |
| `--emoji CHAR` | brand + favicon emoji (default 🗺️) |
| `--color GROUP=HEX` | pin a group's color (repeatable) |
| `--max-embed KB` | per-file cap for embedded file contents (default 512; 0 disables) |
| `--no-dates` | skip created/updated dates and git commit stamps |

## Example: the nullexit vault

```bash
cd ~/Developer/nullexit
python3 ~/Developer/vault-graph/vault_graph.py nullexit-knowledge-graph \
    --src . -o knowledge-graph.html --title nullexit --emoji 🕳️ \
    --color Concepts=#3987e5 --color Components=#199e70 \
    --color 00-Maps=#c98500 --color Containers=#008300 \
    --color Future=#9085e9 --color Bugs=#e66767 \
    --color Observations=#d55181 --color Threat-Model=#d95926
```

The `--color` pins keep the semantic mapping (bugs red, components teal)
instead of the default size-ordered assignment.

## Auto-regeneration: a pre-commit hook

Git runs `.git/hooks/pre-commit` before every commit; putting the generator
there means the graph can never drift from the vault or the scripts it
documents. Regeneration is deterministic and takes about a second, so it is
cheap enough to run unconditionally. The hook used in the nullexit repo:

```sh
#!/bin/sh
# Regenerates on every commit. The HTML is only staged into the commit once
# it is itself tracked; until then it is refreshed locally and left alone.
# Never blocks a commit.

python3 "$HOME/Developer/vault-graph/vault_graph.py" nullexit-knowledge-graph \
    --src . -o knowledge-graph.html --title nullexit --emoji 🕳️ \
    --color Concepts=#3987e5 --color Components=#199e70 \
    >/dev/null 2>&1 || { echo "vault-graph: regeneration failed" >&2; exit 0; }

if git ls-files --error-unmatch knowledge-graph.html >/dev/null 2>&1; then
    git add knowledge-graph.html
fi
exit 0
```

Notes on the shape of it: the file must be executable (`chmod +x`); it always
`exit 0`s so a broken regeneration can never block a commit; and the
`git ls-files` guard makes it adaptive: the day you `git add` the HTML
yourself, the hook starts folding the fresh copy into each commit
automatically. Until then it only refreshes the local file. Be deliberate
about that step: the HTML embeds the full text of every note, so tracking it
publishes the vault's contents wherever the repo goes. Hooks live in `.git/`
and are not cloned with the repo; re-create the file (or set
`git config core.hooksPath`) on a fresh clone.

## Phone notes

Open the HTML any way you like: AirDrop the file, or serve the repo with
`python3 -m http.server` and browse to it. Note and source contents are
embedded in the file, so the ⚙️/📝 links work even on a lone copied HTML;
only non-embeddable targets (binary, oversized, directories) still need the
surrounding tree.
