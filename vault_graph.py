#!/usr/bin/env python3
"""vault-graph — render an Obsidian vault as a single self-contained HTML knowledge graph.

Parses every .md note in a vault, resolves [[wikilinks]] (including aliases,
[[link|display]], [[link#heading]] and table-escaped [[link\\|display]] forms),
and injects the result into an interactive force-directed canvas graph that
works with mouse and touch (pan / pinch-zoom / tap-select / drag).

Optionally links notes to the source files they document: any note whose name
matches a real file's name or stem under --src (any language: .sh, .py, .conf,
extensionless, even directories) gets a "view source" link in its info panel.
Note and source file contents are embedded into the HTML itself, so the file
links open in an in-page viewer and keep working when the output file travels
alone. Anything that can't be embedded (binary, over --max-embed, a directory)
falls back to a relative link that resolves when the HTML lives inside (or is
served from) the same tree.

Usage:
  vault_graph.py [VAULT] [-o out.html] [--src DIR | --no-src] [--title NAME]
                 [--emoji CHAR] [--color GROUP=HEX ...]

With no VAULT argument, the vault is found relative to the cwd, in order:
  1. ./Vault            2. the cwd itself, if it contains .obsidian
  3. the single subfolder of the cwd that contains .obsidian

Examples:
  vault_graph.py                      # auto-detect vault in cwd
  vault_graph.py ~/notes/my-vault
  vault_graph.py nullexit-knowledge-graph --src . -o knowledge-graph.html \
      --title nullexit --emoji 🕳️ --color Bugs=#e66767 --color Concepts=#3987e5
"""
import argparse
import json
import os
import re
import sys

WIKILINK = re.compile(r"\[\[([^\]\[]+?)\]\]")

# Validated categorical palette for the dark surface (#1a1a19) — slots are
# assigned to groups in descending note-count order; extra groups fold to gray.
PALETTE = ["#3987e5", "#199e70", "#c98500", "#008300",
           "#9085e9", "#e66767", "#d55181", "#d95926"]
GRAY = "#8a897f"
SKIP_DIRS = {".git", ".obsidian", "node_modules", "__pycache__",
             ".venv", "venv", "dist", "build", ".trash"}


def parse_frontmatter(text):
    fm = {"tags": [], "aliases": []}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            raw, body = text[3:end], text[end + 4:]
            key = None
            for line in raw.splitlines():
                m = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    if val and key in fm:
                        fm[key] = [v.strip().strip('"') for v in val.strip("[]").split(",") if v.strip()]
                elif re.match(r"^\s*-\s+", line) and key in fm:
                    fm[key].append(re.sub(r"^\s*-\s+", "", line).strip().strip('"'))
    return fm, body


def clean_inline(s):
    s = re.sub(r"\[\[([^\]\[]+?)\]\]",
               lambda m: (m.group(1).split("|")[-1] if "|" in m.group(1)
                          else m.group(1).split("#")[0]), s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    return s.strip()


def extract_preview(body, limit=260):
    para = []
    for ln in body.splitlines():
        t = ln.strip()
        if not t:
            if para:
                break
            continue
        if t.startswith("#") or t.startswith(">"):
            if para:
                break
            continue
        para.append(t)
    text = clean_inline(" ".join(para))
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def pretty_label(group):
    if group == "Root":
        return "Root"
    label = re.sub(r"^\d+[-_ ]*", "", group)
    return label.replace("-", " ").replace("_", " ").strip() or group


def collect_notes(vault, outdir):
    notes, alias_map = {}, {}
    for root, dirs, files in os.walk(vault):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in SKIP_DIRS)
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            path = os.path.join(root, f)
            name = f[:-3]
            folder = os.path.relpath(root, vault)
            group = "Root" if folder == "." else folder.split(os.sep)[0]
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            fm, body = parse_frontmatter(text)
            notes[name] = {
                "id": name, "group": group,
                "path": os.path.relpath(path, outdir).replace(os.sep, "/"),
                "tags": fm["tags"], "aliases": fm["aliases"],
                "preview": extract_preview(body),
                "_abs": path,
            }
            alias_map[name.lower()] = name
            for a in fm["aliases"]:
                alias_map.setdefault(a.lower(), name)
    return notes, alias_map


def resolve_links(notes, alias_map):
    edges, unresolved = set(), {}
    for name, n in notes.items():
        with open(n["_abs"], encoding="utf-8", errors="replace") as fh:
            _, body = parse_frontmatter(fh.read())
        for m in WIKILINK.finditer(body):
            target = m.group(1).split("|")[0].split("#")[0].strip().rstrip("\\").strip()
            if not target:
                continue
            target = target.split("/")[-1]
            resolved = alias_map.get(target.lower())
            if resolved:
                if resolved != name:
                    edges.add((name, resolved))
            else:
                unresolved.setdefault(target, set()).add(name)
    return edges, unresolved


def read_embed(path, limit):
    """Return a file's text for embedding, or None (missing, binary, too big)."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > limit:
            return None
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    return raw.decode("utf-8", errors="replace")


def build_src_map(src_root, vault, outdir):
    """Map note names to real files: exact filename match beats stem match,
    shallower paths beat deeper ones. Any extension / language / directory."""
    vault = os.path.abspath(vault)
    candidates = {}  # lowered key -> (priority, depth, relpath, abspath)

    def offer(key, prio, depth, path):
        rel = os.path.relpath(path, outdir).replace(os.sep, "/")
        cur = candidates.get(key)
        if cur is None or (prio, depth) < cur[:2]:
            candidates[key] = (prio, depth, rel, path)

    for root, dirs, files in os.walk(src_root):
        if os.path.abspath(root).startswith(vault):
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in SKIP_DIRS)
        depth = os.path.relpath(root, src_root).count(os.sep)
        for entry in sorted(files) + sorted(dirs):
            offer(entry.lower(), 0, depth, os.path.join(root, entry))
            stem = os.path.splitext(entry)[0]
            if stem != entry:
                offer(stem.lower(), 1, depth, os.path.join(root, entry))
    return candidates


def find_vault(cwd):
    v = os.path.join(cwd, "Vault")
    if os.path.isdir(v):
        return v
    if os.path.isdir(os.path.join(cwd, ".obsidian")):
        return cwd
    cands = [os.path.join(cwd, d) for d in sorted(os.listdir(cwd))
             if os.path.isdir(os.path.join(cwd, d, ".obsidian"))]
    if len(cands) == 1:
        return cands[0]
    if cands:
        sys.exit("error: several vaults in the current directory — pass one explicitly:\n  "
                 + "\n  ".join(os.path.basename(c) for c in cands))
    sys.exit("error: no vault given and none found in the current directory\n"
             "(looked for ./Vault, ./.obsidian, or a subfolder containing .obsidian)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="\n".join(__doc__.splitlines()[1:]))
    ap.add_argument("vault", nargs="?",
                    help="path to the Obsidian vault folder (default: ./Vault, the cwd "
                         "if it is a vault, or the single vault folder inside the cwd)")
    ap.add_argument("-o", "--output", help="output HTML file (default: <vault>-graph.html in cwd)")
    ap.add_argument("--src", help="root to scan for source files matching note names "
                                  "(default: the vault's parent directory)")
    ap.add_argument("--no-src", action="store_true", help="disable source-file linking")
    ap.add_argument("--title", help="brand title shown in the header (default: vault folder name)")
    ap.add_argument("--emoji", default="🗺️", help="brand/favicon emoji (default: 🗺️)")
    ap.add_argument("--color", action="append", default=[], metavar="GROUP=HEX",
                    help="pin a group's color, repeatable (e.g. --color Bugs=#e66767)")
    ap.add_argument("--max-embed", type=int, default=512, metavar="KB",
                    help="per-file cap for embedding file contents into the HTML "
                         "(default 512; 0 disables embedding)")
    args = ap.parse_args()

    vault = os.path.abspath(args.vault) if args.vault else find_vault(os.getcwd())
    if not os.path.isdir(vault):
        sys.exit(f"error: vault not found: {vault}")
    title = args.title or os.path.basename(vault.rstrip(os.sep))
    output = os.path.abspath(args.output or f"{title}-graph.html")
    outdir = os.path.dirname(output)

    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
    with open(template_path, encoding="utf-8") as fh:
        template = fh.read()

    notes, alias_map = collect_notes(vault, outdir)
    if not notes:
        sys.exit(f"error: no .md notes found in {vault}")
    edges, unresolved = resolve_links(notes, alias_map)

    embed_limit = args.max_embed * 1024
    files = {}

    src_mapped = 0
    if not args.no_src:
        src_root = os.path.abspath(args.src or os.path.dirname(vault))
        src_map = build_src_map(src_root, vault, outdir)
        for name, n in notes.items():
            hit = src_map.get(name.lower())
            if hit:
                n["src"] = hit[2]
                src_mapped += 1
                text = read_embed(hit[3], embed_limit)
                if text is not None:
                    files[hit[2]] = text

    for n in notes.values():
        text = read_embed(n["_abs"], embed_limit)
        if text is not None:
            files[n["path"]] = text

    ghosts = [{"id": t, "group": "Unresolved", "refs": sorted(refs)}
              for t, refs in sorted(unresolved.items())]
    for g in ghosts:
        for s in g["refs"]:
            edges.add((s, g["id"]))

    node_list = []
    for n in sorted(notes.values(), key=lambda n: n["id"].lower()):
        n = dict(n)
        n.pop("_abs")
        node_list.append(n)
    data = {"nodes": node_list, "ghosts": ghosts,
            "edges": [{"s": a, "t": b} for a, b in sorted(edges)],
            "files": files}

    # group palette: slots by descending note count, overrides win, extras gray
    counts = {}
    for n in node_list:
        counts[n["group"]] = counts.get(n["group"], 0) + 1
    overrides = {}
    for spec in args.color:
        if "=" not in spec:
            sys.exit(f"error: bad --color '{spec}' (expected GROUP=HEX)")
        g, _, hexv = spec.partition("=")
        overrides[g] = hexv
    ordered = sorted(counts, key=lambda g: (-counts[g], g.lower()))
    slots = iter([c for c in PALETTE if c not in overrides.values()])
    group_meta = []
    for g in ordered:
        color = overrides.get(g) or next(slots, GRAY)
        group_meta.append([g, color, pretty_label(g)])
    group_meta.append(["Unresolved", "#6b6a60", "Unresolved"])

    esc_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # "</" must not appear inside the inline <script> (embedded file contents
    # can contain literal "</script>"); "<\/" is the same string in JSON.
    js = lambda obj, **kw: json.dumps(obj, ensure_ascii=False, **kw).replace("</", "<\\/")
    html = (template
            .replace("__GROUP_META__", js(group_meta))
            .replace("__GRAPH_DATA__", js(data, separators=(",", ":")))
            .replace("__TITLE__", esc_title)
            .replace("__EMOJI__", args.emoji))
    with open(output, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"vault:    {vault}")
    print(f"output:   {output} ({os.path.getsize(output):,} bytes)")
    print(f"notes:    {len(node_list)}  links: {len(edges)}  unresolved: {len(ghosts)}")
    print(f"groups:   " + ", ".join(f"{g}={counts[g]}" for g in ordered))
    print(f"sources:  {src_mapped} notes linked to real files" if not args.no_src
          else "sources:  disabled (--no-src)")
    embed_bytes = sum(len(v.encode("utf-8")) for v in files.values())
    print(f"embedded: {len(files)} files ({embed_bytes:,} bytes) — file links work anywhere")


if __name__ == "__main__":
    main()
