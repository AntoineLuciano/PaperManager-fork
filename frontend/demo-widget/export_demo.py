"""
Export recorded Knowledge Chat answers as the demo's data.

Runs anywhere it can reach a PaperManager backend (e.g. inside the backend container):

    PM_API=http://localhost:8000 PM_TOKEN=<access token> python export_demo.py tabs.json out/

`tabs.json` lists one tab per sample paper, in order:

    [{"slug": "guidance", "conversation": "<id>", "short": "Classifier-free guidance",
      "hint": "draws a formula and a plot",
      "paper": {"id": "<library id>", "authors": "Ho & Salimans", "venue": "...", "title": "(to correct the library title)"},
      "keep": ["<labels of the concept cards to show; all when omitted>"],
      "replace": [["text to redact", "replacement"]]}]

The tab shows the conversation's first question and its answer. Writes out/demo.json and
out/structures/<key>.json.gz for every ```structure block (mmCIF trimmed to the categories the
viewer reads). Paper title, year and DOI/arXiv link come from the library; the one-line blurb is
the first sentence of the paper's summary. Review the output before publishing it.
"""
import gzip
import json
import os
import re
import sys
import urllib.request

API = os.environ.get("PM_API", "http://localhost:8000").rstrip("/")
TOKEN = os.environ["PM_TOKEN"]

PAPER_LINK = re.compile(r"\]\(/paper/([0-9a-f-]{36})/?\)", re.I)
STRUCTURE_BLOCK = re.compile(r"```structure\n(.*?)```", re.S)
PDB_ID = re.compile(r"^[0-9][A-Za-z0-9]{3}$")
AF_ID = re.compile(r"^AF-([A-Z0-9]{6,10})(?:-F1)?$", re.I)
CIF_KEEP = {"_struct_conf", "_struct_conf_type", "_struct_sheet_range", "_atom_site"}


def get(path):
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def link_of(p):
    doi = (p.get("doi") or "").strip()
    if doi.lower().startswith("arxiv:"):
        return f"https://arxiv.org/abs/{doi[6:]}"
    return f"https://doi.org/{doi}" if doi.startswith("10.") else None


def blurb_of(summary):
    """The first sentence of the summary's first paragraph, without Markdown emphasis."""
    text = next((ln for ln in (summary or "").splitlines() if ln.strip() and not ln.startswith("#")), "")
    text = re.sub(r"[*_`]", "", text).strip()
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return (m.group(1) if m else text)[:300]


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


def export_structures(text, out_dir):
    for block in STRUCTURE_BLOCK.findall(text):
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


def main(tabs_path, out_dir):
    os.makedirs(os.path.join(out_dir, "structures"), exist_ok=True)
    tabs = []
    for tab in json.load(open(tabs_path)):
        msgs = get(f"/knowledge-chat/conversations/{tab['conversation']}/messages")
        question = next(m for m in msgs if m["role"] == "user")
        answer = next(m for m in msgs if m["role"] == "assistant")
        text = answer["content"]
        for old, new in tab.get("replace", []):
            text = text.replace(old, new)
        keep = tab.get("keep")
        concepts = [{"label": c.get("label"), "section": c.get("section", 0), "spec": c["spec"]}
                    for c in (answer.get("concepts") or []) if c.get("spec") and (keep is None or c.get("label") in keep)]
        cited = {}
        for pid in dict.fromkeys(PAPER_LINK.findall(text)):
            p = get(f"/papers/{pid}")
            cited[pid] = {"title": p.get("title"), "link": link_of(p)}
        p = get(f"/papers/{tab['paper']['id']}")
        paper = {"title": tab["paper"].get("title") or p.get("title"), "authors": tab["paper"].get("authors", ""), "year": p.get("year"),
                 "venue": tab["paper"].get("venue"), "blurb": tab["paper"].get("blurb") or blurb_of(p.get("summary")),
                 "link": link_of(p)}
        export_structures(text, out_dir)
        tabs.append({"slug": tab["slug"], "short": tab["short"], "hint": tab.get("hint"), "paper": paper,
                     "question": question["content"], "answer": text, "concepts": concepts, "cited": cited})
    with open(os.path.join(out_dir, "demo.json"), "w") as f:
        json.dump({"tabs": tabs}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
