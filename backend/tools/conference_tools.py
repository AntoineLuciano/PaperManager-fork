"""Conference explorer tools: who publishes on a topic at NeurIPS / ICML / ICLR / CVPR /
ACL / ..., and what one institution published there. Read-only; they use the datasets
the backend has built (services/conferences/) and never call a language model."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from services.conferences import areas, catalog, store


def _ready(conference: str):
    ed = catalog.resolve(conference)
    if ed is None:
        return None, {"error": f"Unknown conference '{conference}'. Call list_conferences for the keys."}
    ds = store.load(ed.key)
    if ds is None:
        st = store.status(ed.key)
        return None, {"error": f"{ed.name} is not loaded (state: {st.get('state')}). "
                               "Open it in the app's Conferences page, or call list_conferences."}
    return ds, None


def _paper(p: dict) -> dict:
    names = [a["short"] for a in areas.AREAS]
    out = {
        "title": p["title"], "decision": p["decision"],
        "area": names[p["area"]] if p.get("area", -1) >= 0 else None,
        "institutions": [i["name"] for i in p["institutions"]],
        "url": p.get("url") or p.get("forum") or None,
    }
    if p.get("match") is not None:
        out["match"] = p["match"]
    if p.get("library_id"):
        out["library_paper_id"] = p["library_id"]
    return out


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def list_conferences(only_loaded: bool = True) -> dict:
        """Conference-years the explorer knows (NeurIPS, ICML, ICLR, CVPR, ICCV, ECCV, ACL,
        EMNLP, AAAI, CoRL, ...) with key (e.g. "neurips2026"), state and paper count.
        only_loaded=False also lists the ones not downloaded yet."""
        rows = store.catalog_rows()
        if only_loaded:
            rows = [r for r in rows if r["state"] in ("ready", "partial", "embedding")]
        return {"conferences": [{k: r[k] for k in ("key", "name", "state", "papers", "institutions")}
                                for r in rows]}

    @mcp.tool()
    def conference_topic(conference: str, query: str, k: int = 100, papers: int = 15) -> dict:
        """Who publishes on a topic at one conference. `conference` is a key or name
        ("neurips2026", "ICML 2025", "iclr" = latest). `query` is a topic or a pasted
        abstract. Takes the k papers closest to the query (bge-small embeddings of title
        + abstract), counts them per institution, and returns the top universities and
        companies, the research-area mix and the closest papers (with library_paper_id
        when the paper is already in the library)."""
        ds, err = _ready(conference)
        if err:
            return err
        res = store.topic(ds, query, k=k, paper_top=max(1, min(int(papers), 40)))
        mix = sorted((a for a in res["areas"] if a["count"]), key=lambda a: -a["count"])
        return {
            "conference": ds.raw["name"], "query": query, "mode": res["mode"],
            "closest_papers_considered": res["k"], "of_papers": res["total"],
            "with_company_author": res["with_industry"],
            "areas": [{"area": a["name"], "papers": a["count"]} for a in mix[:8]],
            "universities_and_institutes": [{"name": x["name"], "papers": x["count"],
                                             "share_of_their_papers": x["of_own"]} for x in res["academia"]],
            "companies": [{"name": x["name"], "papers": x["count"],
                           "share_of_their_papers": x["of_own"]} for x in res["industry"]],
            "papers": [_paper(p) for p in res["papers"]],
        }

    @mcp.tool()
    def conference_institution(conference: str, institution: str, papers: int = 40) -> dict:
        """What one institution published at a conference: rank, paper count (full and
        fractional), research-area mix against the whole conference, main collaborators,
        most frequent authors and its papers. `institution` is matched by name
        ("MIT", "Google", "Tsinghua")."""
        ds, err = _ready(conference)
        if err:
            return err
        hits = store.search_institutions(ds, q=institution, limit=5)["rows"]
        if not hits:
            return {"error": f"No institution matching '{institution}' at {ds.raw['name']}."}
        d = store.institution_detail(ds, hits[0]["slug"])
        total = sum(a["count"] for a in d["conference_areas"]) or 1
        mix = sorted((a for a in d["areas"] if a["count"]), key=lambda a: -a["count"])
        conf = {a["index"]: a["count"] for a in d["conference_areas"]}
        return {
            "conference": ds.raw["name"], "institution": d["name"],
            "other_matches": [h["name"] for h in hits[1:]],
            "sector": "industry" if d["sector"] == "I" else "academia",
            "rank": d["rank"], "papers": d["papers"], "fractional_papers": d["fractional"],
            "areas": [{"area": a["name"], "papers": a["count"],
                       "conference_share": round(conf[a["index"]] / total, 3)} for a in mix[:10]],
            "collaborators": [{"name": c["name"], "shared_papers": c["shared"]} for c in d["collaborators"][:8]],
            "authors": d["authors"][:10],
            "paper_list": [_paper(p) for p in d["paper_list"][:max(1, min(int(papers), 100))]],
        }
