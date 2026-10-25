"""Which conference-years the explorer knows and where each one's data comes from.

Two public sources:

* ``miniconf``: the official conference websites (neurips.cc, icml.cc, iclr.cc,
  cvpr.thecvf.com, iccv.thecvf.com, eccv.ecva.net) publish every accepted paper with
  its authors, each author's institution, the abstract, the session and the
  OpenReview link as one JSON file.
* ``papercopilot``: Paper Copilot's paper lists (github.com/papercopilot/paperlists)
  cover the venues without a miniconf site (ACL, EMNLP, AAAI, CoRL, ...) and the
  years a miniconf site no longer serves. Affiliations come normalised for most of
  them; a few (ACL 2025, recent OpenReview venues) carry none, so those get the topic
  view only.

Keys are ``<series><year>`` (``neurips2026``). Add a year by adding it to ``SERIES``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Series:
    slug: str            # url / key prefix
    name: str            # display name
    field: str           # "ML", "Vision", "NLP", "Robotics", "AI", "Data"
    host: str = ""       # miniconf host, empty when the series has none
    pc_dir: str = ""     # Paper Copilot folder
    years_miniconf: tuple[int, ...] = ()
    years_pc: tuple[int, ...] = ()


SERIES: list[Series] = [
    Series("neurips", "NeurIPS", "ML", "neurips.cc", "nips",
           years_miniconf=(2020, 2021, 2022, 2023, 2024, 2025, 2026)),
    Series("icml", "ICML", "ML", "icml.cc", "icml",
           years_miniconf=(2022, 2023, 2024, 2025, 2026)),
    Series("iclr", "ICLR", "ML", "iclr.cc", "iclr",
           years_miniconf=(2022, 2023, 2024, 2025, 2026)),
    Series("cvpr", "CVPR", "Vision", "cvpr.thecvf.com", "cvpr",
           years_miniconf=(2023, 2024, 2025, 2026), years_pc=(2022,)),
    Series("iccv", "ICCV", "Vision", "iccv.thecvf.com", "iccv",
           years_miniconf=(2025,), years_pc=(2021, 2023)),
    Series("eccv", "ECCV", "Vision", "eccv.ecva.net", "eccv",
           years_miniconf=(2024, 2026), years_pc=(2022,)),
    Series("wacv", "WACV", "Vision", pc_dir="wacv", years_pc=(2024, 2025)),
    Series("acl", "ACL", "NLP", pc_dir="acl", years_pc=(2022, 2023, 2024, 2025)),
    Series("emnlp", "EMNLP", "NLP", pc_dir="emnlp", years_pc=(2021, 2022, 2023, 2024)),
    Series("naacl", "NAACL", "NLP", pc_dir="naacl", years_pc=(2024, 2025)),
    Series("colm", "COLM", "NLP", pc_dir="colm", years_pc=(2024, 2025)),
    Series("aaai", "AAAI", "AI", pc_dir="aaai", years_pc=(2023, 2024, 2025)),
    Series("ijcai", "IJCAI", "AI", pc_dir="ijcai", years_pc=(2022, 2023, 2024)),
    Series("aistats", "AISTATS", "ML", pc_dir="aistats", years_pc=(2023, 2024, 2025)),
    Series("uai", "UAI", "ML", pc_dir="uai", years_pc=(2022, 2023, 2024)),
    Series("colt", "COLT", "ML", pc_dir="colt", years_pc=(2022, 2023, 2024)),
    Series("corl", "CoRL", "Robotics", pc_dir="corl", years_pc=(2022, 2023, 2024, 2025)),
    Series("rss", "RSS", "Robotics", pc_dir="rss", years_pc=(2023, 2024, 2025)),
    Series("icra", "ICRA", "Robotics", pc_dir="icra", years_pc=(2023, 2024)),
    Series("iros", "IROS", "Robotics", pc_dir="iros", years_pc=(2023, 2024)),
    Series("kdd", "KDD", "Data", pc_dir="kdd", years_pc=(2023, 2024)),
    Series("www", "WWW", "Data", pc_dir="www", years_pc=(2024, 2025)),
]

_BY_SLUG = {s.slug: s for s in SERIES}


@dataclass(frozen=True)
class Edition:
    key: str
    series: Series
    year: int
    source: str          # "miniconf" or "papercopilot"

    @property
    def name(self) -> str:
        return f"{self.series.name} {self.year}"

    @property
    def source_url(self) -> str:
        if self.source == "miniconf":
            host = self.series.host
            return f"https://{host}/static/virtual/data/{host.split('.')[0]}-{self.year}-orals-posters.json"
        return (f"https://raw.githubusercontent.com/papercopilot/paperlists/main/"
                f"{self.series.pc_dir}/{self.series.pc_dir}{self.year}.json")


def editions() -> list[Edition]:
    """Every known conference-year, newest first within each series."""
    out: list[Edition] = []
    for s in SERIES:
        years = {y: "miniconf" for y in s.years_miniconf}
        for y in s.years_pc:
            years.setdefault(y, "papercopilot")
        for y in sorted(years, reverse=True):
            out.append(Edition(f"{s.slug}{y}", s, y, years[y]))
    return out


def get_edition(key: str) -> Edition | None:
    key = key.strip().lower()
    for e in editions():
        if e.key == key:
            return e
    return None


def resolve(name: str) -> Edition | None:
    """Accept ``neurips2026``, ``NeurIPS 2026``, ``neurips-2026`` or a bare series name
    (``neurips`` = its latest year)."""
    compact = "".join(ch for ch in name.lower() if ch.isalnum())
    hit = get_edition(compact)
    if hit:
        return hit
    if compact == "nips" or compact.startswith("nips"):
        compact = "neurips" + compact[4:]
        hit = get_edition(compact)
        if hit:
            return hit
    series = _BY_SLUG.get(compact)
    if series:
        return next(e for e in editions() if e.series.slug == series.slug)
    return None
