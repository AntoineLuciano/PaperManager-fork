"""
Export Knowledge Chat conversations as static data for the demo widget.

Runs anywhere it can reach a PaperManager backend (e.g. inside the backend container):

    PM_API=http://localhost:8000 PM_TOKEN=<access token> python export_demo.py tabs.json out/

`tabs.json` lists the conversations to export, in tab order:

    [{"slug": "derivation", "conversation": "<id>", "title": "...", "hint": "...",
      "parent": "<slug of the conversation a strand came from>", "fork_at": 1,
      "replace": [["text to redact", "replacement"]]}]

Writes out/manifest.json, out/<slug>.json per conversation and out/structures/<key>.json.gz
for every ```structure block (mmCIF trimmed to the categories the viewer reads). Only what the
widget renders is kept: messages, cited papers (title, year, venue, summary, link),
concept cards and a short list of the papers that were in context. Review the output before
publishing it: it is whatever the conversations and the papers' summaries say.
"""
import gzip
import json
import os
import re
import sys
import urllib.request

API = os.environ.get("PM_API", "http://localhost:8000").rstrip("/")
TOKEN = os.environ["PM_TOKEN"]
CONTEXT_KEEP = 8          # papers "in context" listed under an answer
SUMMARY_CHARS = 1400      # summary shown in the paper preview

PAPER_LINK = re.compile(r"\]\(/paper/([0-9a-f-]{36})/?\)", re.I)
STRUCTURE_BLOCK = re.compile(r"```structure\n(.*?)```", re.S)
PDB_ID = re.compile(r"^[0-9][A-Za-z0-9]{3}$")
AF_ID = re.compile(r"^AF-([A-Z0-9]{6,10})(?:-F1)?$", re.I)
CIF_KEEP = {"_struct_conf", "_struct_conf_type", "_struct_sheet_range", "_atom_site"}


def get(path):
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def paper_card(pid):
    p = get(f"/papers/{pid}")
    summary = (p.get("summary") or p.get("abstract") or "").strip()
    if len(summary) > SUMMARY_CHARS:
        cut = summary.rfind("\n", 0, SUMMARY_CHARS)
        summary = summary[: cut if cut > SUMMARY_CHARS // 2 else SUMMARY_CHARS].rstrip() + " …"
    doi = (p.get("doi") or "").strip()
    link = (f"https://arxiv.org/abs/{doi[6:]}" if doi.lower().startswith("arxiv:")
            else f"https://doi.org/{doi}" if doi.startswith("10.") else None)
    return {"title": p.get("title"), "year": p.get("year"), "venue": p.get("venue"), "summary": summary,
            "link": link, "cited": True}


def structure_models(source):
    t = source.strip().strip("`")
    if t.startswith("{"):
        d = json.loads(t)
        return d.get("models") or [d]
    if PDB_ID.match(t):
        return [{"pdb": t.upper()}]
    m = AF_ID.match(t)
    return [{"afdb": m.group(1).upper()}] if m else []


def trim_cif(data):
    """Keep the data_ line and the categories the viewer reads (atoms, helices, sheets)."""
    blocks, cur = [], []
    for line in data.splitlines():
        if line.strip() == "#":
            blocks.append(cur)
            cur = []
        else:
            cur.append(line)
    blocks.append(cur)
    out = []
    for b in blocks:
        if b and b[0].startswith("data_"):
            out.append(b[0])
            continue
        head = next((ln for ln in b if ln.startswith("_")), "")
        if head.split(".")[0] in CIF_KEEP:
            out += ["#", *b]
    return "\n".join(out + ["#", ""])


def main(tabs_path, out_dir):
    tabs = json.load(open(tabs_path))
    os.makedirs(os.path.join(out_dir, "structures"), exist_ok=True)
    manifest = []
    for tab in tabs:
        msgs = get(f"/knowledge-chat/conversations/{tab['conversation']}/messages")
        cited, messages = [], []
        for m in msgs:
            if m["role"] not in ("user", "assistant"):
                continue
            content = m["content"]
            for old, new in tab.get("replace", []):
                content = content.replace(old, new)
            out = {"role": m["role"], "content": content}
            if m["role"] == "assistant":
                ids = list(dict.fromkeys(PAPER_LINK.findall(content)))
                cited += [i for i in ids if i not in cited]
                context = [p for p in (m.get("papers") or [])]
                context.sort(key=lambda p: p["id"] not in ids)
                out["papers"] = [{"id": p["id"], "title": p.get("title"), "year": p.get("year")}
                                 for p in context[:CONTEXT_KEEP]]
                out["concepts"] = [{"label": c.get("label"), "section": c.get("section", 0), "spec": c["spec"]}
                                   for c in (m.get("concepts") or []) if c.get("spec")]
                for block in STRUCTURE_BLOCK.findall(content):
                    for model in structure_models(block):
                        key = f"pdb-{model['pdb'].upper()}" if model.get("pdb") else f"afdb-{model['afdb'].upper()}"
                        path = os.path.join(out_dir, "structures", f"{key}.json.gz")
                        if os.path.exists(path):
                            continue
                        q = f"pdb={model['pdb']}" if model.get("pdb") else f"afdb={model['afdb']}"
                        c = get(f"/knowledge-chat/structures?{q}")
                        if c["format"] == "cif":
                            c["data"] = trim_cif(c["data"])
                        with gzip.open(path, "wt", compresslevel=9) as f:
                            json.dump(c, f, separators=(",", ":"))
            messages.append(out)
        context_ids = {p["id"] for m in messages for p in m.get("papers", [])}
        papers = {pid: paper_card(pid) for pid in cited}
        for pid in context_ids - set(papers):
            p = get(f"/papers/{pid}")
            papers[pid] = {"title": p.get("title"), "year": p.get("year"), "venue": p.get("venue"), "summary": "", "link": None}
        conv = {"slug": tab["slug"], "title": tab["title"], "parent": tab.get("parent"), "fork_at": tab.get("fork_at"), "messages": messages, "papers": papers}
        with open(os.path.join(out_dir, f"{tab['slug']}.json"), "w") as f:
            json.dump(conv, f, ensure_ascii=False, separators=(",", ":"))
        manifest.append({k: tab.get(k) for k in ("slug", "title", "hint", "parent", "fork_at")})
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump({"tabs": manifest}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
