"""Institution names: one canonical name per institution, and academia vs industry.

Conference feeds carry whatever each author typed: ``Tsinghua University, Tsinghua
University``, ``Department of Computer Science, ETHZ - ETH Zurich``, ``Google, TUM``,
``Xi&#x27;an Jiaotong University``, full-width letters. ``split_and_normalise`` turns
one such string into canonical institutions:

1. unescape HTML, NFKC (full-width -> ASCII), collapse whitespace;
2. split on ``;`` / ``|`` (several affiliations) and on commas, gluing a comma part that
   is only a place (``University of California, Berkeley``) back onto the one before
   and dropping department / school parts when an organisation is also named;
3. map each part through ``ALIASES`` (merges Google + DeepMind, Meta + FAIR, the CAS
   institutes, campus spellings, acronyms); anything else keeps its cleaned spelling and
   is merged with other spellings by a folded key (case, accents, punctuation, "The").

``sector`` says "A" (universities, institutes, labs, hospitals, non-profits) or "I"
(companies). Fix a wrong mapping by adding an alias line.
"""
from __future__ import annotations

import html
import re
import unicodedata

# (pattern on the folded lowercase text, canonical name, sector). First match wins,
# so specific patterns (Google Research) sit above general ones (Google).
_ALIAS_SPEC: list[tuple[str, str, str]] = [
    # Industry
    (r"\b(google|deepmind|alphabet|waymo)\b", "Google", "I"),
    (r"\b(meta|facebook|fair)\b(?! ?-?learn)", "Meta", "I"),
    (r"\bmicrosoft\b|\bmsr\b", "Microsoft", "I"),
    (r"\bnvidia\b", "NVIDIA", "I"),
    (r"\bamazon\b|\baws\b", "Amazon", "I"),
    (r"^apple\b|\bapple (inc|ai|ml|research)", "Apple", "I"),
    (r"\bopenai\b", "OpenAI", "I"),
    (r"\banthropic\b", "Anthropic", "I"),
    (r"\b(ibm|international business machines)\b", "IBM", "I"),
    (r"\bintel (corp|labs|corporation)|^intel$|\bintel labs\b", "Intel", "I"),
    (r"\b(amd|advanced micro devices)\b", "AMD", "I"),
    (r"\bqualcomm\b", "Qualcomm", "I"),
    (r"\badobe\b", "Adobe", "I"),
    (r"\bsalesforce\b", "Salesforce", "I"),
    (r"\bsamsung\b", "Samsung", "I"),
    (r"\b(lg ai|lg electronics|^lg$)", "LG", "I"),
    (r"^hp$|^hp inc\b|\bhewlett.packard\b|^hp labs\b", "HP", "I"),
    (r"\bnaver\b", "NAVER", "I"),
    (r"\bkakao\b", "Kakao", "I"),
    (r"\bsony\b", "Sony", "I"),
    (r"\b(toyota|tri)\b(?! ?univ)", "Toyota", "I"),
    (r"\bbosch\b", "Bosch", "I"),
    (r"\bsiemens\b", "Siemens", "I"),
    (r"\bhuawei\b|noah ?s ark", "Huawei", "I"),
    (r"\bbytedance\b|\btiktok\b|\bbyte dance\b|\bdouyin\b", "ByteDance", "I"),
    (r"\bant (group|financial|research)\b|\bantgroup\b|\bant international\b", "Ant Group", "I"),
    (r"\balibaba\b|\bdamo academy\b|\bqwen\b|\btongyi\b|\btaobao\b|\baliyun\b", "Alibaba", "I"),
    (r"\btencent\b|\bwechat\b|\byoutu\b|\bhunyuan\b", "Tencent", "I"),
    (r"\bbaidu\b", "Baidu", "I"),
    (r"\bkuaishou\b|快手", "Kuaishou", "I"),
    (r"\bmeituan\b", "Meituan", "I"),
    (r"\bjd\.?com\b|\bjd explore\b|\bjingdong\b|^jd$", "JD.com", "I"),
    (r"\bxiaomi\b", "Xiaomi", "I"),
    (r"\bxiaohongshu\b|\bred note\b|\brednote\b", "Xiaohongshu", "I"),
    (r"\bsensetime\b", "SenseTime", "I"),
    (r"\boppo\b", "OPPO", "I"),
    (r"\bvivo\b", "vivo", "I"),
    (r"\blenovo\b", "Lenovo", "I"),
    (r"\bhonor\b", "Honor", "I"),
    (r"\bmoonshot\b", "Moonshot AI", "I"),
    (r"\bdeepseek\b", "DeepSeek", "I"),
    (r"\bzhipu\b", "Zhipu AI", "I"),
    (r"\bminimax\b", "MiniMax", "I"),
    (r"\bstepfun\b", "StepFun", "I"),
    (r"\bmegvii\b", "Megvii", "I"),
    (r"\bhorizon robotics\b", "Horizon Robotics", "I"),
    (r"\bli auto\b", "Li Auto", "I"),
    (r"\bchina mobile\b", "China Mobile", "I"),
    (r"\bchina telecom\b", "China Telecom", "I"),
    (r"\bsnap (inc|research)\b|^snap$|\bsnapchat\b", "Snap", "I"),
    (r"\bnetflix\b", "Netflix", "I"),
    (r"\buber\b", "Uber", "I"),
    (r"\bspotify\b", "Spotify", "I"),
    (r"\boracle\b", "Oracle", "I"),
    (r"\bcisco\b", "Cisco", "I"),
    (r"\bcapital one\b", "Capital One", "I"),
    (r"\bjp ?morgan\b|\bjpmorgan\b", "JPMorgan Chase", "I"),
    (r"\bmorgan stanley\b", "Morgan Stanley", "I"),
    (r"\bgoldman sachs\b", "Goldman Sachs", "I"),
    (r"\bbloomberg\b", "Bloomberg", "I"),
    (r"\bmistral\b", "Mistral AI", "I"),
    (r"\bcohere\b", "Cohere", "I"),
    (r"\bhugging ?face\b", "Hugging Face", "I"),
    (r"\bscale ai\b", "Scale AI", "I"),
    (r"\btogether ai\b|\btogether computer\b", "Together AI", "I"),
    (r"\bxai\b|^x\.ai$", "xAI", "I"),
    (r"\bvalence labs\b|\brecursion\b", "Recursion", "I"),
    (r"\binstadeep\b", "InstaDeep", "I"),
    (r"\bisomorphic\b", "Isomorphic Labs", "I"),
    (r"\bgenentech\b|\broche\b", "Roche / Genentech", "I"),
    (r"\bnovartis\b", "Novartis", "I"),
    (r"\bastrazeneca\b", "AstraZeneca", "I"),
    (r"\bpfizer\b", "Pfizer", "I"),
    (r"\bmerck\b", "Merck", "I"),
    (r"\bsanofi\b", "Sanofi", "I"),
    (r"\bjohnson ?(&|and) ?johnson\b|\bjanssen\b", "Johnson & Johnson", "I"),
    # Academia: research institutes
    (r"\bmax[ -]planck\b|\bmpi[- ]", "Max Planck Society", "A"),
    (r"\bchinese academy of sciences\b|\bchinese academy of science\b|\bucas\b|\bcas\b(?! ?ai)"
     r"|institute of automation|institute of computing technology|shenzhen institutes? of advanced"
     r"|institute of software,? chinese|institute of information engineering", "Chinese Academy of Sciences", "A"),
    (r"\bshanghai (artificial intelligence|ai) (laboratory|lab)\b|\bshanghai ai lab\b", "Shanghai AI Laboratory", "A"),
    (r"\bpeng ?cheng lab", "Peng Cheng Laboratory", "A"),
    (r"\bbeijing academy of artificial intelligence\b|\bbaai\b", "Beijing Academy of AI (BAAI)", "A"),
    (r"\bmila\b|quebec (ai|artificial intelligence) institute", "Mila", "A"),
    (r"\bvector institute\b", "Vector Institute", "A"),
    (r"\ballen institute for (ai|artificial intelligence)\b|\bai2\b|\ballenai\b", "Allen Institute for AI", "A"),
    (r"\binria\b", "Inria", "A"),
    (r"\becole normale superieure\b.*lyon|^ens (de )?lyon\b", "ENS Lyon", "A"),
    (r"\becole normale superieure\b.*saclay|^ens paris[- ]saclay\b", "ENS Paris-Saclay", "A"),
    (r"\becole normale superieure\b|^ens( paris| psl|ulm)?$|^ens[- ]psl\b", "ENS Paris", "A"),
    (r"\bcnrs\b", "CNRS", "A"),
    (r"\briken\b", "RIKEN", "A"),
    (r"\ba\*star\b|\bastar\b|agency for science,? technology and research", "A*STAR", "A"),
    (r"\bcsiro\b|\bdata61\b", "CSIRO", "A"),
    (r"\bhelmholtz\b|\bcispa\b|\bdkfz\b|deutsches krebsforschungszentrum|german cancer research", "Helmholtz Association", "A"),
    (r"\bfraunhofer\b", "Fraunhofer", "A"),
    (r"\bellis\b", "ELLIS", "A"),
    (r"\btoyota technological institute\b|\bttic\b", "Toyota Technological Institute at Chicago", "A"),
    (r"\bbroad institute\b", "Broad Institute", "A"),
    (r"\bflatiron\b|\bsimons foundation\b", "Flatiron Institute", "A"),
    (r"\bhasso[ -]plattner\b", "Hasso Plattner Institute", "A"),
    (r"\bargonne\b", "Argonne National Laboratory", "A"),
    (r"\blawrence livermore\b", "Lawrence Livermore National Laboratory", "A"),
    (r"\blawrence berkeley\b", "Lawrence Berkeley National Laboratory", "A"),
    (r"\blos alamos\b", "Los Alamos National Laboratory", "A"),
    (r"\boak ridge\b", "Oak Ridge National Laboratory", "A"),
    (r"\bfondazione bruno kessler\b|\bfbk\b", "Fondazione Bruno Kessler", "A"),
    # Academia: universities (acronyms and common variants)
    (r"\bmassachusetts institute of technology\b|^mit\b|\bmit (csail|media lab)|\bcsail\b", "MIT", "A"),
    (r"\bcarnegie mellon\b|^cmu\b", "Carnegie Mellon University", "A"),
    (r"\bstanford\b", "Stanford University", "A"),
    (r"\bharvard\b", "Harvard University", "A"),
    (r"\bprinceton\b", "Princeton University", "A"),
    (r"\bcalifornia institute of technology\b|\bcaltech\b", "Caltech", "A"),
    (r"\b(university of california,? berkeley|uc ?berkeley)\b|^berkeley\b|\bberkeley ai research\b", "UC Berkeley", "A"),
    (r"\b(university of california,? los angeles|ucla)\b", "UCLA", "A"),
    (r"\b(university of california,? san diego|uc ?san diego|ucsd)\b", "UC San Diego", "A"),
    (r"\b(university of california,? irvine|uc ?irvine|uci)\b", "UC Irvine", "A"),
    (r"\b(university of california,? santa barbara|uc ?santa barbara|ucsb)\b", "UC Santa Barbara", "A"),
    (r"\b(university of california,? santa cruz|uc ?santa cruz|ucsc)\b", "UC Santa Cruz", "A"),
    (r"\b(university of california,? davis|uc ?davis)\b", "UC Davis", "A"),
    (r"\b(university of california,? riverside|uc ?riverside|ucr)\b", "UC Riverside", "A"),
    (r"\b(university of california,? merced|uc ?merced)\b", "UC Merced", "A"),
    (r"\b(university of california,? san francisco|ucsf)\b", "UCSF", "A"),
    (r"\b(university of illinois,? (at )?urbana|uiuc|illinois urbana)", "UIUC", "A"),
    (r"\buniversity of illinois,? (at )?chicago\b|\buic\b", "University of Illinois Chicago", "A"),
    (r"\bgeorgia (institute of technology|tech)\b", "Georgia Tech", "A"),
    (r"\bnew york university\b|^nyu\b", "New York University", "A"),
    (r"\b(university of texas,? (at )?austin|ut ?austin)\b", "UT Austin", "A"),
    (r"\buniversity of michigan\b|\bumich\b", "University of Michigan", "A"),
    (r"\buniversity of wisconsin\b.*madison|\buw[- ]madison\b", "University of Wisconsin-Madison", "A"),
    (r"\buniversity of washington\b|^uw$", "University of Washington", "A"),
    (r"\bwashington university\b.*(st\.? ?louis|saint louis)|\bwustl\b", "Washington University in St. Louis", "A"),
    (r"\buniversity of maryland\b|\bumd\b", "University of Maryland", "A"),
    (r"\buniversity of massachusetts\b.*amherst|\bumass amherst\b", "UMass Amherst", "A"),
    (r"\buniversity of minnesota\b", "University of Minnesota", "A"),
    (r"\b(unc|university of north carolina)\b.*chapel hill|^unc$", "UNC Chapel Hill", "A"),
    (r"\b(state university of new york at )?stony brook\b", "Stony Brook University", "A"),
    (r"\b(state university of new york at buffalo|university at buffalo|suny buffalo)\b", "University at Buffalo", "A"),
    (r"\btexas a ?& ?m\b|\btexas a and m\b", "Texas A&M University", "A"),
    (r"\bohio state\b", "Ohio State University", "A"),
    (r"\bpenn(sylvania)? state\b", "Penn State University", "A"),
    (r"\buniversity of pennsylvania\b|^upenn\b", "University of Pennsylvania", "A"),
    (r"\bvirginia (tech|polytechnic)\b", "Virginia Tech", "A"),
    (r"\buniversity of virginia\b", "University of Virginia", "A"),
    (r"\buniversity of southern california\b|^usc\b", "University of Southern California", "A"),
    (r"\bjohns hopkins\b", "Johns Hopkins University", "A"),
    (r"\bcolumbia university\b", "Columbia University", "A"),
    (r"\bcornell\b", "Cornell University", "A"),
    (r"\byale\b", "Yale University", "A"),
    (r"\buniversity of chicago\b", "University of Chicago", "A"),
    (r"\bboston university\b", "Boston University", "A"),
    (r"\bnortheastern university\b(?!.*(china|shenyang))", "Northeastern University", "A"),
    (r"\buniversity of oxford\b|\boxford university\b|^oxford\b", "University of Oxford", "A"),
    (r"\buniversity of cambridge\b|\bcambridge university\b", "University of Cambridge", "A"),
    (r"\bimperial college\b", "Imperial College London", "A"),
    (r"\buniversity college london\b|^ucl\b", "University College London", "A"),
    (r"\bking ?s college london\b|^kcl\b", "King's College London", "A"),
    (r"\buniversity of edinburgh\b", "University of Edinburgh", "A"),
    (r"\beth ?z(u|ue)rich\b|^ethz?\b|\bswiss federal institute of technology,? z", "ETH Zurich", "A"),
    (r"\bepfl\b|\becole polytechnique federale de lausanne\b|\bswiss federal institute of technology,? lausanne", "EPFL", "A"),
    (r"\b(technical university (of )?munich|technische universitat munchen|tu munich|tum)\b", "TU Munich", "A"),
    (r"\b(ludwig[- ]maximilians|lmu)\b", "LMU Munich", "A"),
    (r"\b(university of )?t(u|ue)bingen\b|\beberhard[- ]karls\b", "University of Tübingen", "A"),
    (r"\b(technische universitat darmstadt|tu darmstadt|technical university of darmstadt)\b", "TU Darmstadt", "A"),
    (r"\b(technische universitat berlin|tu berlin|technical university of berlin)\b", "TU Berlin", "A"),
    (r"\b(karlsruhe institute of technology|karlsruher institut|kit)\b", "Karlsruhe Institute of Technology", "A"),
    (r"\b(university of freiburg|universitat freiburg|albert[- ]ludwigs)\b", "University of Freiburg", "A"),
    (r"\b(university of amsterdam|universiteit van amsterdam)\b", "University of Amsterdam", "A"),
    (r"\b(delft university of technology|tu ?delft)\b", "TU Delft", "A"),
    (r"\b(ku ?leuven|katholieke universiteit leuven)\b", "KU Leuven", "A"),
    (r"\b(university of toronto|uoft)\b", "University of Toronto", "A"),
    (r"\b(universite de montreal|university of montreal|u\.? ?(de )?montreal|udem)\b", "Université de Montréal", "A"),
    (r"\bmcgill\b", "McGill University", "A"),
    (r"\b(university of british columbia|ubc)\b", "University of British Columbia", "A"),
    (r"\buniversity of waterloo\b", "University of Waterloo", "A"),
    (r"\buniversity of alberta\b", "University of Alberta", "A"),
    (r"\btechnion\b", "Technion", "A"),
    (r"\bweizmann\b", "Weizmann Institute of Science", "A"),
    (r"\bhebrew university\b", "Hebrew University of Jerusalem", "A"),
    (r"\btel[- ]aviv university\b", "Tel Aviv University", "A"),
    (r"\b(mohamed bin zayed|mbzuai)\b", "MBZUAI", "A"),
    (r"\b(king abdullah university of science and technology|kaust)\b", "KAUST", "A"),
    (r"\btsinghua\b", "Tsinghua University", "A"),
    (r"\bpeking university\b|^pku\b", "Peking University", "A"),
    (r"\bzhejiang university\b|^zju\b", "Zhejiang University", "A"),
    (r"\bshanghai ?jiao ?tong\b|^sjtu\b", "Shanghai Jiao Tong University", "A"),
    (r"\bfudan\b", "Fudan University", "A"),
    (r"\b(university of science and technology of china|ustc)\b", "USTC", "A"),
    (r"\bnanjing university\b(?! of)", "Nanjing University", "A"),
    (r"\bsun yat[- ]?sen\b", "Sun Yat-sen University", "A"),
    (r"\bharbin institute of technology\b|^hit\b", "Harbin Institute of Technology", "A"),
    (r"\b(beihang|beijing university of aeronautics and astronautics)\b", "Beihang University", "A"),
    (r"\bbeijing university of posts? and telecommunications?\b|^bupt\b", "BUPT", "A"),
    (r"\bxi ?an jiaotong[- ]liverpool\b", "Xi'an Jiaotong-Liverpool University", "A"),
    (r"\bxi ?an jiaotong\b|^xjtu\b", "Xi'an Jiaotong University", "A"),
    (r"\b(xidian|xi ?an university of electronic science)\b", "Xidian University", "A"),
    (r"\bnorthwest(ern)? polytechnical\b", "Northwestern Polytechnical University", "A"),
    (r"\bhuazhong university of science and technology\b|^hust\b", "Huazhong University of Science and Technology", "A"),
    (r"\buniversity of electronic science and technology of china\b|^uestc\b", "UESTC", "A"),
    (r"\brenmin university\b", "Renmin University of China", "A"),
    (r"\bwestlake university\b", "Westlake University", "A"),
    (r"\bshanghaitech\b", "ShanghaiTech University", "A"),
    (r"\bsouthern university of science and technology\b|^sustech\b", "SUSTech", "A"),
    (r"\b(hong kong university of science and technology|hkust)\b.*(guangzhou|gz)", "HKUST (Guangzhou)", "A"),
    (r"\bhong kong university of science and technology\b|\bhkust\b", "HKUST", "A"),
    (r"\bchinese university of hong kong\b.*shenzhen|\bcuhk[- ]?(sz|shenzhen)\b", "CUHK-Shenzhen", "A"),
    (r"\bchinese university of hong kong\b|\bcuhk\b", "CUHK", "A"),
    (r"\bcity university of hong kong\b|^cityu\b", "City University of Hong Kong", "A"),
    (r"\bhong kong polytechnic\b|^polyu\b", "Hong Kong Polytechnic University", "A"),
    (r"^(the )?university of hong kong\b|^hku\b", "University of Hong Kong", "A"),
    (r"\bnational university of sing", "National University of Singapore", "A"),
    (r"\bnanyang technological\b|^ntu singapore\b", "Nanyang Technological University", "A"),
    (r"\bsingapore management university\b", "Singapore Management University", "A"),
    (r"\b(korea advanced institute of science|kaist)\b", "KAIST", "A"),
    (r"\b(pohang university of science|postech)\b", "POSTECH", "A"),
    (r"\bseoul national university\b|^snu\b", "Seoul National University", "A"),
    (r"\bsung ?kyun ?kwan\b", "Sungkyunkwan University", "A"),
    (r"\b(ulsan national institute|unist)\b", "UNIST", "A"),
    (r"\b(university of tokyo|the university of tokyo)\b", "University of Tokyo", "A"),
    (r"\binstitute of science tokyo\b|\btokyo institute of technology\b", "Institute of Science Tokyo", "A"),
    (r"\bnational taiwan university\b", "National Taiwan University", "A"),
    (r"\bindian institute of science\b|^iisc\b", "Indian Institute of Science", "A"),
    (r"\baustralian national university\b|^anu\b", "Australian National University", "A"),
    (r"\buniversity of new south wales\b|^unsw\b", "UNSW Sydney", "A"),
    (r"\b(the )?university of melbourne\b", "University of Melbourne", "A"),
    (r"\b(the )?university of sydney\b", "University of Sydney", "A"),
    (r"\b(the )?university of queensland\b", "University of Queensland", "A"),
    (r"\b(the )?university of adelaide\b|^adelaide university\b", "University of Adelaide", "A"),
]

ALIASES = [(re.compile(p), name, sector) for p, name, sector in _ALIAS_SPEC]
_CANON_SECTOR = {name: sector for _, name, sector in _ALIAS_SPEC}
CANONICAL = frozenset(_CANON_SECTOR)

# Not institutions: dropped. Includes anonymised placeholders ("AXXX", "XXX", "Anonymous
# Institution"), bare category words ("University", "Company", "ML") and role-only strings.
_JUNK = re.compile(r"^(independent( researcher| scholar)?|individual( researcher)?|none|null|n/?a|unknown|"
                   r"unaffiliated|self|personal|freelance|private|-+|\.+|student|researcher|phd student|"
                   r"a?x{2,}|x+ (university|institute|company|inc)|anonymous( \w+)*|anon|tbd|tba|"
                   r"confidential|withheld|redacted|hidden|other|others|"
                   r"company|university|institute|industry|academia|research|lab|ai|ml|cs)$")
_EMAIL = re.compile(r"^(mailto:)?[\w.+-]+@[\w-]+(\.[\w-]+)+$")
# A bare web address or an academic / organisational domain says nothing countable.
_URL = re.compile(r"^(https?://|www\.)|^[\w-]+(\.[\w-]+)*(\.(edu|ac|gov)(\.[a-z]{2})?|\.org\.[a-z]{2})/?$|/$")

_DEPT = re.compile(r"^(dept\.?|department|school of|faculty of|college of|division of|centre for|center for|"
                   r"computer science|electrical|the school of|graduate school|lab(oratory)? of|key lab|state key|"
                   r"institute for ai$|ai lab$)")

_ACADEMIC = re.compile(
    r"universi|\binstitut|istitut|instituut|\buniv\.|\bcollege\b|\bschool\b|\bacadem|\becole\b|hochschule|polytechn|politecnico|"
    r"\blaborator|\blab\b|national lab|\bcent(er|re)\b|\bhospital|\bclinic|\bfoundation\b|\bmuseum\b|"
    r"\bcnrs\b|\binria\b|\binserm\b|\bcea\b|\bcsic\b|\bcnr\b|\bnasa\b|\bnih\b|\bnist\b|\bkaust\b|\btechnion\b|"
    r"\bconservatoire\b|\bobservatory\b|\binstituto\b|\buniv\b|\bschule\b|\bhopital\b|\bmedical\b|\bcollege\b|"
    r"vidyap(i|ee)th|\bsorbonne\b|\bpsl\b|\bmila\b|\bminist|\bgovernment\b|\bnational\b")
_COMPANY = re.compile(
    r"\b(inc|ltd|llc|corp|corporation|co|company|gmbh|ag|sa|sas|plc|limited|pte|bv|nv|kk|oy|ab)\b|"
    r"\btechnolog(y|ies)\b|\bsystems\b|\bsoftware\b|\bai research\b|\blabs\b|\bresearch$|\b(ai|robotics)$")

_LEGAL_ONLY = re.compile(r"^(co|ltd|inc|llc|corp|gmbh|limited|ag|sa|plc|s\.?a|b\.?v)\.?( ?(ltd|limited|inc)\.?)?$")
_PLACE_ONLY = re.compile(r"^[a-z .'-]{2,40}$")


def fold(s: str) -> str:
    """Lowercase ASCII folding used for matching and merging spellings."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("&", " & ")
    s = re.sub(r"[‐-―]", "-", s)
    s = re.sub(r"[^\w&*.'\- ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def merge_key(name: str) -> str:
    k = fold(name)
    k = re.sub(r"^the ", "", k)
    k = re.sub(r"\(.*?\)", "", k)
    return re.sub(r"[^a-z0-9]+", "", k)


def clean(raw: str) -> str:
    s = html.unescape(raw or "")
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip(" ,;.-")
    return s


def alias(part: str) -> tuple[str, str] | None:
    f = fold(part)
    for rx, name, sector in ALIASES:
        if rx.search(f):
            return name, sector
    return None


def sector(name: str) -> str:
    if name in _CANON_SECTOR:
        return _CANON_SECTOR[name]
    f = fold(name)
    if _ACADEMIC.search(f):
        return "A"
    if _COMPANY.search(f):
        return "I"
    # A bare name with no academic word ("Meituan", "Bosch", "Oracle") is almost always
    # a company; universities and institutes say so in their name or have an alias.
    return "I"


def _segments(part: str) -> list[str]:
    """Split one affiliation on commas, gluing place-only pieces onto the previous one."""
    out: list[str] = []
    for seg in [x.strip() for x in part.split(",") if x.strip()]:
        f = fold(seg)
        if out and not alias(out[-1]) and alias(f"{out[-1]}, {seg}"):
            # "University of California, Berkeley": only the pair names the institution.
            out[-1] = f"{out[-1]}, {seg}"
            continue
        if out and _LEGAL_ONLY.match(f):
            out[-1] = f"{out[-1]}, {seg}"      # "Corp., Ltd."
            continue
        is_org = bool(alias(seg) or _ACADEMIC.search(f) or _COMPANY.search(f))
        if out and not is_org and _PLACE_ONLY.match(f) and len(f.split()) <= 3:
            out[-1] = f"{out[-1]}, {seg}"
        else:
            out.append(seg)
    return out


# "University of Science and Technology of China": the piece after "and" continues a
# name rather than starting a new organisation.
_SUBJECT = re.compile(r"^(technolog|engineering|science|arts|medicine|design|applied|management|economics|"
                      r"mathematics|physics|computer|computing|information|astronomy|research|innovation|"
                      r"telecommunication|health|business|law|education|electronics|automation)")


_HEAD = re.compile(r"universi|institut|\bcollege\b|\blabs?\b|laborator|\binc\b|\bltd\b|\bcorp|\bresearch\b|"
                   r"\bcent(er|re)\b|\bhospital|\bgroup\b|\bacadem|\bschool\b|\bai\b|\.ai\b|ecole|polytechn|"
                   r"\bfoundation\b|\bcompany\b|\btechnologies\b")


def _is_org(part: str) -> bool:
    """A complete organisation name on its own: an alias, or at least two words with a head
    noun ("Liquid AI", "Tel Aviv University"), not "Robotics" or "Shandong Medical"."""
    f = fold(part)
    if _DEPT.match(f):
        return False
    return bool(alias(part)) or (len(f.split()) >= 2 and bool(_HEAD.search(f)))


def _parts(s: str) -> list[str]:
    """Split one affiliation field into the affiliations it names: on ``;`` and ``|``, on
    ``/`` between names ("CMU/MBZUAI", but not "TU/e"), and on " & " / " and " when both
    sides are organisations ("Tel Aviv University and Facebook AI Research", but not
    "Texas A&M" or "Department of Physics and Astronomy")."""
    out: list[str] = []
    for part in re.split(r"\s*[;|]\s*", s):
        pieces = part.split("/")
        if len(pieces) > 1 and all(len(p.strip()) >= 2 for p in pieces):
            out.extend(p.strip() for p in pieces)
        else:
            out.append(part.strip())
    final: list[str] = []
    for part in out:
        bits = re.split(r"\s+(?:&|and)\s+", part)
        if (len(bits) > 1 and "," not in part
                and all(_is_org(b) for b in bits)
                and not any(_SUBJECT.match(fold(b)) for b in bits[1:])):
            final.extend(bits)
        else:
            final.append(part)
    return [p for p in final if p]


def _junk_name(name: str) -> bool:
    """A placeholder, a fragment ("e)", "HY"), an e-mail address or a URL. Two-letter names
    are too ambiguous to count; real ones ("LG", "HP") have aliases, which come first."""
    f = fold(name)
    if _JUNK.match(f) or _EMAIL.match(name) or _URL.search(name.strip().lower()):
        return True
    return len(re.sub(r"[^a-z0-9]", "", f)) <= 2


def split_and_normalise(raw: str) -> list[tuple[str, str]]:
    """One raw affiliation string -> distinct ``(canonical name, sector)`` pairs."""
    s = clean(raw)
    if not s or _JUNK.match(fold(s)) or _EMAIL.match(s):
        return []
    if "@" in s:
        # "Head of AI @ Squirrel AI", "PALMLab @ Southeast University": the organisation
        # follows the last "@"; what precedes it is a role or a group.
        s = s.rsplit("@", 1)[1].strip(" ,;.-")
        if not s:
            return []
    found: list[tuple[str, str]] = []
    keys: set[str] = set()
    for part in _parts(s):
        if "," not in part:
            orgs = [part]
        else:
            segs = _segments(part)
            orgs = [g for g in segs if not _DEPT.match(fold(g))] or segs[-1:]
            if len(orgs) > 1:
                # "University College London, University of London": the federal parent adds nothing.
                orgs = [g for g in orgs if fold(g) not in ("university of london",)]
        for g in orgs:
            hit = alias(g)
            if hit:
                name, sec = hit
            else:
                name = re.sub(r"^(the) ", "", g, flags=re.I).strip(" ,;.-")
                name = re.sub(r"\s*-\s*$", "", name)
                if not name or _junk_name(name):
                    continue
                sec = sector(name)
            k = merge_key(name)
            if k and k not in keys:
                keys.add(k)
                found.append((name, sec))
    return found
