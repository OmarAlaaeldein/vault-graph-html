# vault-graph

Render any Obsidian vault as a **single self-contained HTML file** — an
interactive, force-directed knowledge graph that works in any browser,
including on a phone (pan, pinch-zoom, tap a node for its info panel).
No dependencies, no network, no build step: one Python script, one template.

## Requirements

- **Python ≥ 3.8, standard library only** — `argparse`, `json`, `os`, `re`,
  `sys`. There is no `requirements.txt` because there is nothing to install;
  the stock macOS `python3` (3.9.6) is enough.
- The output HTML is equally dependency-free: no D3, no CDN, no network —
  the force simulation and renderer are inlined vanilla JS on a canvas.
- **Obsidian is not required to run the tool.** It reads the vault's `.md`
  files directly (Obsidian only matters for *writing* the vault). Developed
  and tested against a vault created with **Obsidian 1.12.7**; the parsed
  surface is stable, long-standing syntax — `[[wikilinks]]` with `|` aliases
  and `#headings`, YAML frontmatter `tags:`/`aliases:` — plus `.obsidian/`
  folder detection, so older/newer vaults should work unchanged.

```
python3 vault_graph.py                # auto-detect the vault in the cwd
python3 vault_graph.py /path/to/vault # or point it anywhere
```

With no argument the vault is found relative to the current directory, in
order: `./Vault` → the cwd itself if it contains `.obsidian` → the single
subfolder that contains `.obsidian` (several candidates = explicit error).
Nothing else is ever assumed about paths: sources are scanned relative to the
vault (`--src`), links are emitted relative to the output file, and the HTML
template is loaded from next to the script itself.

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
  (default: the vault's parent folder). This is a *heuristic* — it can't know
  that a note called "Sweep Protocol" documents `sweep.sh`; only name-shaped
  notes are linked automatically.
- Emits all file links **relative to the output HTML**, so they work when the
  file sits in (or is served from) the repo the vault documents.

## Viewer features

Force layout pre-settles before first paint. Search (names, aliases, tags),
per-group legend filter chips, fit / zoom / label-mode / re-layout buttons,
tap-to-highlight neighborhoods, and an info panel (bottom sheet on phones)
with the note preview and clickable outgoing/incoming links.

## Options

| flag | meaning |
|------|---------|
| `VAULT` | vault folder (optional — auto-detected in cwd as described above) |
| `-o FILE` | output path (default `<vault>-graph.html` in cwd) |
| `--src DIR` | root scanned for source-file matches (default: vault's parent) |
| `--no-src` | disable source linking |
| `--title NAME` | header/brand title (default: vault folder name) |
| `--emoji CHAR` | brand + favicon emoji (default 🗺️) |
| `--color GROUP=HEX` | pin a group's color (repeatable) |

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

(The `--color` pins keep the semantic mapping — bugs red, components teal —
instead of the default size-ordered assignment.)

## Phone notes

Open the HTML any way you like — AirDrop the file, or serve the repo with
`python3 -m http.server` and browse to it. The ⚙️/📝 file links need the
surrounding tree (desktop or HTTP-served); a lone copied HTML still renders
the full graph, just not those links.
