"""Rules of services/duplicate_scan.py, on cases taken from the real library (Oct 2026)."""
from services.duplicate_scan import (
    doi_variants, is_truncation, looks_like_garbage_title, normalize_doi, scan, wrong_doi_suspects,
)


def paper(pid, title, doi=None, *, pdf=False, project=None, stub=False, text=0, cited_by=0, created="2026-01-01"):
    return {
        "id": pid, "title": title, "doi": doi, "drive_file_id": f"drive-{pid}" if pdf else None,
        "text_chars": text, "has_abstract": pdf, "notes": 0, "annotations": 0,
        "projects": [project] if project else [], "tags": ["from-references"] if stub else ["pdf-upload"],
        "cited_by": cited_by, "cites": 0, "created_at": created,
    }


def ids(group):
    return group.keep["id"], sorted(p["id"] for p in group.remove)


def test_normalize_doi_unifies_arxiv_and_preprint_forms():
    assert normalize_doi("arXiv:2206.00364") == "arxiv:2206.00364"
    assert normalize_doi("2206.00364") == "arxiv:2206.00364"
    assert normalize_doi("10.48550/arXiv.2206.00364") == "arxiv:2206.00364"
    assert normalize_doi("https://doi.org/10.1101/2025.06.14.659707v2") == "10.1101/2025.06.14.659707"
    assert normalize_doi("10.1101/2024.07.17.604015doi:") == "10.1101/2024.07.17.604015"
    assert normalize_doi("not a doi") is None
    assert "10.48550/arXiv.2206.00364" in doi_variants("2206.00364")


def test_paper_absorbs_its_citation_stubs_including_author_list_titles():
    ps = [
        paper("edm", "Elucidating the Design Space of Diffusion-Based Generative Models", "arXiv:2206.00364",
              pdf=True, project="MasterThesis", text=126263),
        paper("s1", "Elucidating the Design Space of Diffusion-Based Generative Models",
              "10.48550/arXiv.2206.00364", stub=True, cited_by=6),
        paper("s2", "Tero Karras, Miika Aittala, Timo Aila, and Samuli Laine", "2206.00364", stub=True),
        paper("s3", "Elucidating the design space of diffusion based generative models", None, stub=True),
    ]
    (g,) = scan(ps).groups
    assert ids(g) == ("edm", ["s1", "s2", "s3"])
    assert g.klass == "paper_with_stubs"


def test_wrong_doi_on_upload_is_a_conflict_not_a_merge():
    ps = [
        paper("cadllm", "CAD-LLM: Large Language Model for CAD", "arXiv:2106.09685", pdf=True, text=8000),
        paper("lora", "LoRA: Low-Rank Adaptation of Large Language Models", "2106.09685", stub=True),
    ]
    r = scan(ps)
    assert r.groups == []
    ((s, o),) = wrong_doi_suspects(r)
    assert (s["id"], o["id"]) == ("cadllm", "lora")


def test_prefix_titles_with_unrelated_dois_stay_apart():
    ps = [
        paper("q1", "Quantum Convolutional Neural Networks for Groundwater Heat Plume Prediction: A Surrogate Model",
              "arXiv:2606.23411", pdf=True),
        paper("q2", "Quantum convolutional neural networks", "10.1038/s41567-019-0648-8", stub=True),
        paper("f1", "De novo design of orthogonal far-red, orange, and green f", "10.1021/acsnano.6c09991", pdf=True),
        paper("f2", "De novo design of orthogonal far-red, orange, and green fluorophore-binding proteins",
              "10.1007/978-1-60761-847-8_5", pdf=True),
    ]
    assert scan(ps).groups == []


def test_preprint_and_published_version_merge_and_two_pdfs_keep_the_richer():
    ps = [
        paper("bioemu-pre", "Scalable emulation of protein equilibrium ensembles with generative deep learning",
              "10.1101/2024.12.05.626885", project="MasterThesis", stub=True),
        paper("bioemu-sci", "Scalable emulation of protein equilibrium ensembles with generative deep learning",
              "10.1126/science.adv9817", stub=True),
        paper("cfg1", "Classifier-Free Diffusion Guidance", "10.48550/arXiv.2207.12598", pdf=True,
              project="MasterThesis", text=34861, cited_by=9),
        paper("cfg2", "CLASSIFIER -FREE DIFFUSION GUIDANCE", "arXiv:2207.12598", pdf=True,
              project="MasterThesis", text=34783),
    ]
    groups = {g.keep["id"]: g for g in scan(ps).groups}
    assert ids(groups["cfg1"]) == ("cfg1", ["cfg2"]) and groups["cfg1"].klass == "pdf_duplicates"
    assert ids(groups["bioemu-pre"]) == ("bioemu-pre", ["bioemu-sci"])


def test_generic_and_short_titles_never_merge():
    ps = [paper("a", "Supplementary information for the main text", stub=True),
          paper("b", "Supplementary information for the main text", stub=True),
          paper("c", "Introduction", stub=True), paper("d", "Introduction", stub=True)]
    assert scan(ps).groups == []


def test_helpers():
    assert is_truncation("DeepSeek-V2: A Strong, Economical, and Efficient",
                         "DeepSeek-V2: A Strong, Economical, and Efficient Mixture-of-Experts Language Model")
    assert not is_truncation("Quantum convolutional neural networks",
                             "Quantum Convolutional Neural Networks for Groundwater Heat Plume Prediction: A Surrogate M")
    assert looks_like_garbage_title("Xingchao Liu, Chengyue Gong, and Qiang Liu")
    assert looks_like_garbage_title("Figure\n Legends")
    assert not looks_like_garbage_title("Scaling Laws for Neural Language Models")


def test_author_list_stub_does_not_bridge_a_wrong_doi():
    ps = [
        paper("review", "Fold-switching proteins push the boundaries of conformational ensemble prediction",
              "arXiv:2304.02198", pdf=True, project="MasterThesis", text=69315),
        paper("eigen", "EigenFold: Generative Protein Structure Prediction with Diffusion Models",
              "10.48550/arXiv.2304.02198", stub=True),
        paper("authors", "Bowen Jing, Ezra Erives, Peter Pao-Huang, Gabriele Corso, Bonnie Berger, and Tommi Jaakkola",
              "2304.02198", stub=True),
    ]
    r = scan(ps)
    assert [ids(g) for g in r.groups] == [("eigen", ["authors"])]
    ((s, o),) = wrong_doi_suspects(r)
    assert (s["id"], o["id"]) == ("review", "eigen")


def test_author_list_stub_attaches_to_upload_only_with_title_evidence():
    ps = [
        paper("cad", "Generative AI meets CAD: enhancing engineering design to manufacturing processes",
              "arXiv:2109.00859", pdf=True),
        paper("codet5", "Wang Y , Wang W, Joty S, Hoi SC (2021) Codet5: identifier-aware unified pre-trained encoder-",
              "2109.00859", stub=True),
        paper("boltz", "Boltz-2: Towards Accurate and Efficient Binding Affinity Prediction",
              "10.1101/2025.06.14.659707", pdf=True),
        paper("cite", "Passaro, Saro, et al. “Boltz-2: Towards Accurate and Efficient Binding Affinity Prediction",
              "10.1101/2025.06.14.659707", stub=True),
    ]
    assert [ids(g) for g in scan(ps).groups] == [("boltz", ["cite"])]


def test_stub_prefix_titles_and_near_titles_that_are_different_papers():
    ps = [
        paper("ddpm", "Denoising Diffusion Probabilistic Models", "2006.11239", stub=True),
        paper("so3", "Denoising diffusion probabilistic models on so (3) for rotational alignment", stub=True),
        paper("drbo1", "Distributionally Robust Bayesian Optimization", stub=True),
        paper("drbo2", "Distributionally Robust Bayesian Optimization with φ-divergences", stub=True),
        paper("g1", "Efficient Per-Example Gradient Computations", "1510.01799", stub=True),
        paper("g2", "Efficient Per-Example Gradient Computations in Convolutional Neural Networks", "1912.06015", stub=True),
        paper("out", "What are the output fields and their types?", stub=True),
        paper("in", "What are the input fields and their types?", stub=True),
        paper("osdi1", "This paper is included in the Proceedings of the 16th USENIX Symposium on Operating Systems", stub=True),
        paper("osdi2", "This paper is included in the Proceedings of the 16th USENIX Symposium on Operating Systems", stub=True),
    ]
    assert scan(ps).groups == []


def test_truncated_upload_title_still_links_to_full_stub():
    ps = [
        paper("up", "Retrieval Augmented Generation or Long-Context LLMs?", pdf=True, text=48965),
        paper("st", "Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and Hybrid Approach",
              "2407.16833", stub=True),
        paper("p1", "Lost in the Middle: How Language Models Use Long Contexts", "2307.03172", stub=True),
        paper("p2", "Lost in the Middle: How Language Models Use Long Contexts", "2307.99999", stub=True),
    ]
    assert [ids(g) for g in scan(ps).groups] == [("up", ["st"])]


def test_roman_numerals_and_author_lists_do_not_link_by_title():
    ps = [
        paper("c13", "Critical Assessment of Methods of Protein Structure Prediction (CASP)—Round XIII", stub=True),
        paper("c15", "Critical Assessment of Methods of Protein Structure Prediction (CASP) – Round XV",
              "10.1002/prot.26617", stub=True),
        paper("a1", "Josh Abramson, Jonas Adler, Jack Dunger, Richard Evans, Tim Green, Alexander Pritzel", stub=True),
        paper("a2", "Josh Abramson, Jonas Adler, Jack Dunger, Richard Evans, Tim Green, Alexander Pritzel",
              "2506.23971", stub=True),
    ]
    assert scan(ps).groups == []
