"""Florida geography: the 67 counties, their regions, and name-to-county inference.

The scout began as a tri-county tool where ``county`` was one of three literals.
Going statewide, county became a real dimension: every adapter now has to place
an agency somewhere, and most portals never say which county they are in. They
say "City of Ocoee" or "Sarasota County Schools" and expect you to know.

So this module does two jobs. It is the canonical list of the 67 counties with a
stable slug and a region grouping for the dashboard, and it infers a county from
an agency's name when the portal does not tell us. Inference is deliberately
conservative: a confident match or ``statewide``, never a guess that would file a
Panhandle school district under Miami-Dade.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# The 67 counties
# ---------------------------------------------------------------------------

# region -> counties, following the way Florida agencies actually group
# themselves (FDOT districts and the regional planning councils broadly agree).
REGIONS: Dict[str, List[str]] = {
    "southeast": [
        "miami-dade", "broward", "palm-beach", "martin", "st-lucie",
        "indian-river", "okeechobee", "monroe",
    ],
    "southwest": [
        "lee", "collier", "charlotte", "sarasota", "manatee", "hendry",
        "glades", "desoto", "hardee", "highlands",
    ],
    "tampa-bay": [
        "hillsborough", "pinellas", "pasco", "polk", "hernando", "citrus",
        "sumter",
    ],
    "central": [
        "orange", "seminole", "osceola", "lake", "volusia", "brevard",
        "marion", "flagler",
    ],
    "northeast": [
        "duval", "st-johns", "clay", "nassau", "putnam", "alachua", "baker",
        "bradford", "union", "columbia", "gilchrist", "levy", "dixie",
        "lafayette", "suwannee", "hamilton",
    ],
    "northwest": [
        "leon", "escambia", "santa-rosa", "okaloosa", "walton", "bay",
        "gulf", "franklin", "wakulla", "jefferson", "madison", "taylor",
        "gadsden", "liberty", "calhoun", "jackson", "holmes", "washington",
    ],
}

#: Slug -> display name. Built from REGIONS so the two can never drift.
_SPECIAL_NAMES = {
    "miami-dade": "Miami-Dade",
    "palm-beach": "Palm Beach",
    "st-lucie": "St. Lucie",
    "st-johns": "St. Johns",
    "santa-rosa": "Santa Rosa",
    "indian-river": "Indian River",
    "desoto": "DeSoto",
}

COUNTY_NAMES: Dict[str, str] = {
    slug: _SPECIAL_NAMES.get(slug, slug.replace("-", " ").title())
    for counties in REGIONS.values()
    for slug in counties
}

COUNTY_REGION: Dict[str, str] = {
    slug: region for region, counties in REGIONS.items() for slug in counties
}

COUNTY_SLUGS = sorted(COUNTY_NAMES)

# Buckets that are not one of the 67 but still need somewhere to live.
PSEUDO_COUNTIES: Dict[str, str] = {
    "statewide": "Statewide",   # state agencies, universities, co-ops
    "federal": "Federal",       # SAM.gov
    "unknown": "Unknown",
}

ALL_REGIONS: Dict[str, str] = {**COUNTY_NAMES, **PSEUDO_COUNTIES}

#: Display names for the region keys above. Used to group the county picker —
#: 67 counties in one flat list is a scroll, six regions is a choice.
REGION_LABEL: Dict[str, str] = {
    "southeast": "Southeast Florida",
    "southwest": "Southwest Florida",
    "tampa-bay": "Tampa Bay",
    "central": "Central Florida",
    "northeast": "Northeast Florida",
    "northwest": "Northwest Florida",
    "statewide": "Statewide & other",
    "federal": "Statewide & other",
    "unknown": "Statewide & other",
}


def county_label(slug: str) -> str:
    """Display name for a county slug, tolerant of anything unrecognised."""
    return ALL_REGIONS.get(slug) or slug.replace("-", " ").title()


def region_of(slug: str) -> str:
    return COUNTY_REGION.get(slug, slug if slug in PSEUDO_COUNTIES else "unknown")


# ---------------------------------------------------------------------------
# Inferring a county from an agency name
# ---------------------------------------------------------------------------

# Cities and other well-known entities whose name gives no county away.
# Only entries that are unambiguous statewide belong here — where a city name
# repeats across counties (Belleair, Greenville, Lake Park…) we leave it out
# and let the entry fall through to `unknown` rather than pick wrong.
CITY_COUNTY: Dict[str, str] = {
    # Southeast
    "miami": "miami-dade", "miami beach": "miami-dade", "hialeah": "miami-dade",
    "coral gables": "miami-dade", "homestead": "miami-dade", "doral": "miami-dade",
    "aventura": "miami-dade", "miami gardens": "miami-dade", "north miami": "miami-dade",
    "north miami beach": "miami-dade", "opa-locka": "miami-dade", "sweetwater": "miami-dade",
    "miami lakes": "miami-dade", "palmetto bay": "miami-dade", "pinecrest": "miami-dade",
    "cutler bay": "miami-dade", "key biscayne": "miami-dade", "sunny isles beach": "miami-dade",
    "bal harbour": "miami-dade", "surfside": "miami-dade", "hialeah gardens": "miami-dade",
    "south miami": "miami-dade", "west miami": "miami-dade", "medley": "miami-dade",
    "bay harbor islands": "miami-dade", "golden beach": "miami-dade",
    "fort lauderdale": "broward", "hollywood": "broward", "pembroke pines": "broward",
    "coral springs": "broward", "miramar": "broward", "plantation": "broward",
    "sunrise": "broward", "davie": "broward", "deerfield beach": "broward",
    "pompano beach": "broward", "weston": "broward", "tamarac": "broward",
    "margate": "broward", "coconut creek": "broward", "lauderhill": "broward",
    "oakland park": "broward", "hallandale beach": "broward", "dania beach": "broward",
    "cooper city": "broward", "parkland": "broward", "wilton manors": "broward",
    "lauderdale lakes": "broward", "north lauderdale": "broward", "southwest ranches": "broward",
    "lighthouse point": "broward", "sea ranch lakes": "broward", "pembroke park": "broward",
    "west park": "broward", "lazy lake": "broward",
    "west palm beach": "palm-beach", "boca raton": "palm-beach", "delray beach": "palm-beach",
    "boynton beach": "palm-beach", "jupiter": "palm-beach", "wellington": "palm-beach",
    "palm beach gardens": "palm-beach", "royal palm beach": "palm-beach",
    "riviera beach": "palm-beach", "greenacres": "palm-beach", "lake worth": "palm-beach",
    "lake worth beach": "palm-beach", "north palm beach": "palm-beach",
    "palm beach": "palm-beach", "belle glade": "palm-beach", "pahokee": "palm-beach",
    "south bay": "palm-beach", "tequesta": "palm-beach", "juno beach": "palm-beach",
    "lantana": "palm-beach", "manalapan": "palm-beach", "gulf stream": "palm-beach",
    "highland beach": "palm-beach", "ocean ridge": "palm-beach", "palm springs": "palm-beach",
    "atlantis": "palm-beach", "loxahatchee groves": "palm-beach", "westlake": "palm-beach",
    "stuart": "martin", "jensen beach": "martin", "sewall's point": "martin",
    "port st. lucie": "st-lucie", "port st lucie": "st-lucie", "fort pierce": "st-lucie",
    "vero beach": "indian-river", "sebastian": "indian-river",
    "key west": "monroe", "marathon": "monroe", "islamorada": "monroe", "key largo": "monroe",
    # Southwest
    "fort myers": "lee", "cape coral": "lee", "bonita springs": "lee",
    "fort myers beach": "lee", "sanibel": "lee", "estero": "lee",
    "naples": "collier", "marco island": "collier",
    "punta gorda": "charlotte",
    "sarasota": "sarasota", "venice": "sarasota", "north port": "sarasota",
    "bradenton": "manatee", "palmetto": "manatee", "anna maria": "manatee",
    "clewiston": "hendry", "labelle": "hendry",
    "sebring": "highlands", "avon park": "highlands", "lake placid": "highlands",
    "arcadia": "desoto", "wauchula": "hardee", "moore haven": "glades",
    # Tampa Bay
    "tampa": "hillsborough", "plant city": "hillsborough", "temple terrace": "hillsborough",
    "st. petersburg": "pinellas", "st petersburg": "pinellas", "clearwater": "pinellas",
    "largo": "pinellas", "pinellas park": "pinellas", "dunedin": "pinellas",
    "tarpon springs": "pinellas", "safety harbor": "pinellas", "oldsmar": "pinellas",
    "seminole": "pinellas", "gulfport": "pinellas", "treasure island": "pinellas",
    "madeira beach": "pinellas", "st. pete beach": "pinellas", "indian rocks beach": "pinellas",
    "new port richey": "pasco", "port richey": "pasco", "zephyrhills": "pasco",
    "dade city": "pasco", "san antonio": "pasco",
    "lakeland": "polk", "winter haven": "polk", "bartow": "polk", "haines city": "polk",
    "auburndale": "polk", "lake wales": "polk", "davenport": "polk", "mulberry": "polk",
    "brooksville": "hernando", "weeki wachee": "hernando",
    "crystal river": "citrus", "inverness": "citrus",
    "bushnell": "sumter", "wildwood": "sumter", "the villages": "sumter",
    # Central
    "orlando": "orange", "winter park": "orange", "apopka": "orange", "ocoee": "orange",
    "winter garden": "orange", "maitland": "orange", "belle isle": "orange",
    "eatonville": "orange", "edgewood": "orange", "windermere": "orange",
    "sanford": "seminole", "altamonte springs": "seminole", "casselberry": "seminole",
    "lake mary": "seminole", "longwood": "seminole", "oviedo": "seminole",
    "winter springs": "seminole",
    "kissimmee": "osceola", "st. cloud": "osceola", "st cloud": "osceola",
    "leesburg": "lake", "eustis": "lake", "mount dora": "lake", "clermont": "lake",
    "tavares": "lake", "groveland": "lake", "minneola": "lake",
    "daytona beach": "volusia", "deltona": "volusia", "ormond beach": "volusia",
    "port orange": "volusia", "new smyrna beach": "volusia", "deland": "volusia",
    "edgewater": "volusia", "holly hill": "volusia", "south daytona": "volusia",
    "debary": "volusia", "orange city": "volusia",
    "melbourne": "brevard", "palm bay": "brevard", "titusville": "brevard",
    "cocoa": "brevard", "cocoa beach": "brevard", "rockledge": "brevard",
    "satellite beach": "brevard", "cape canaveral": "brevard", "west melbourne": "brevard",
    "ocala": "marion", "dunnellon": "marion", "belleview": "marion",
    "palm coast": "flagler", "bunnell": "flagler", "flagler beach": "flagler",
    # Northeast
    "jacksonville": "duval", "jacksonville beach": "duval", "neptune beach": "duval",
    "atlantic beach": "duval", "baldwin": "duval",
    "st. augustine": "st-johns", "st augustine": "st-johns", "ponte vedra": "st-johns",
    "green cove springs": "clay", "orange park": "clay", "keystone heights": "clay",
    "fernandina beach": "nassau", "callahan": "nassau", "hilliard": "nassau",
    "palatka": "putnam", "crescent city": "putnam", "interlachen": "putnam",
    "gainesville": "alachua", "alachua": "alachua", "newberry": "alachua",
    "high springs": "alachua", "archer": "alachua", "waldo": "alachua",
    "macclenny": "baker", "starke": "bradford", "lake butler": "union",
    "lake city": "columbia", "trenton": "gilchrist", "bronson": "levy",
    "cedar key": "levy", "williston": "levy", "chiefland": "levy",
    "cross city": "dixie", "mayo": "lafayette", "live oak": "suwannee",
    "jasper": "hamilton",
    # Northwest
    "tallahassee": "leon",
    "pensacola": "escambia", "century": "escambia",
    "milton": "santa-rosa", "gulf breeze": "santa-rosa", "jay": "santa-rosa",
    "fort walton beach": "okaloosa", "crestview": "okaloosa", "destin": "okaloosa",
    "niceville": "okaloosa", "valparaiso": "okaloosa", "mary esther": "okaloosa",
    "defuniak springs": "walton", "freeport": "walton", "santa rosa beach": "walton",
    "panama city": "bay", "panama city beach": "bay", "lynn haven": "bay",
    "callaway": "bay", "springfield": "bay", "parker": "bay", "mexico beach": "bay",
    "port st. joe": "gulf", "wewahitchka": "gulf",
    "apalachicola": "franklin", "carrabelle": "franklin",
    "crawfordville": "wakulla", "sopchoppy": "wakulla",
    "monticello": "jefferson", "madison": "madison", "perry": "taylor",
    "quincy": "gadsden", "havana": "gadsden", "chattahoochee": "gadsden", "midway": "gadsden",
    "bristol": "liberty", "blountstown": "calhoun",
    "marianna": "jackson", "graceville": "jackson", "sneads": "jackson",
    "bonifay": "holmes", "chipley": "washington",
}

# Named institutions whose county is not in the name at all.
INSTITUTION_COUNTY: Dict[str, str] = {
    "florida international university": "miami-dade",
    "miami dade college": "miami-dade",
    "florida memorial university": "miami-dade",
    "jackson health": "miami-dade",
    "florida atlantic university": "palm-beach",
    "palm beach state college": "palm-beach",
    "solid waste authority": "palm-beach",
    "broward college": "broward",
    "broward health": "broward",
    "nova southeastern": "broward",
    "south florida regional transportation": "broward",
    "tri-rail": "broward",
    "florida state university": "leon",
    "florida a&m": "leon",
    "tallahassee state college": "leon",
    "university of florida": "alachua",
    "santa fe college": "alachua",
    "university of central florida": "orange",
    "valencia college": "orange",
    "orange county convention": "orange",
    "lynx": "orange",
    "central florida expressway": "orange",
    "greater orlando aviation": "orange",
    "reedy creek": "orange",
    "central florida tourism oversight": "orange",
    "university of south florida": "hillsborough",
    "hillsborough community college": "hillsborough",
    "tampa international": "hillsborough",
    "hart ": "hillsborough",
    "st. petersburg college": "pinellas",
    "university of north florida": "duval",
    "florida state college at jacksonville": "duval",
    "jacksonville transportation": "duval",
    "jacksonville aviation": "duval",
    "jea": "duval",
    "university of west florida": "escambia",
    "pensacola state college": "escambia",
    "emerald coast utilities": "escambia",
    "florida gulf coast university": "lee",
    "florida southwestern state college": "lee",
    "lee health": "lee",
    "new college of florida": "sarasota",
    "state college of florida": "manatee",
    "florida polytechnic": "polk",
    "polk state college": "polk",
    "embry-riddle": "volusia",
    "daytona state college": "volusia",
    "bethune-cookman": "volusia",
    "eastern florida state college": "brevard",
    "space florida": "brevard",
    "canaveral port": "brevard",
    "indian river state college": "st-lucie",
    "seminole state college": "seminole",
    "lake-sumter state college": "lake",
    "college of central florida": "marion",
    "chipola college": "jackson",
    "gulf coast state college": "bay",
    "northwest florida state college": "okaloosa",
    "pasco-hernando state college": "pasco",
    "south florida state college": "highlands",
    "the villages": "sumter",
    "naples airport": "collier",
    "parrish medical": "brevard",
}

# Entities that genuinely have no single county.
STATEWIDE_MARKERS = (
    "state of florida", "florida department of", "department of transportation",
    "water management district", "florida division of", "office of the",
    "legislative branch", "state courts", "auditor general", "citizens property",
    "enterprise florida", "volunteer florida", "florida lottery", "myflorida",
    "sourcewell", "omnia", "naspo", "buyboard", "1gpa", "equalis", "tips-usa",
    "florida sheriffs association", "florida buy", "paec",
)

_COUNTY_PATTERN = re.compile(
    r"\b(" + "|".join(
        sorted(
            (re.escape(name.lower()) for name in COUNTY_NAMES.values()),
            key=len,
            reverse=True,
        )
    ) + r")\b(?:\s+county)?",
    re.I,
)

#: A name that opens with one of these is a state body, not a local one.
#: Anchored at the start on purpose — "Miami-Dade County Department of
#: Transportation" must stay in Miami-Dade.
_STATE_BODY = re.compile(
    r"^(?:the\s+)?(?:florida\s+)?"
    r"(?:department|agency|division|office|commission|board|bureau|council|"
    r"authority|executive office|state board)\s+(?:of|for|on)\b",
    re.I,
)

# "St. Johns" and "St Johns" should both hit; likewise "Miami-Dade"/"Miami Dade".
_NORMALISE = ((".", ""), ("’", "'"))


def _normalise(text: str) -> str:
    out = text.lower().strip()
    for a, b in _NORMALISE:
        out = out.replace(a, b)
    return re.sub(r"\s+", " ", out)


_NAME_TO_SLUG: Dict[str, str] = {
    _normalise(name): slug for slug, name in COUNTY_NAMES.items()
}
# Accept the hyphenless spellings agencies actually use.
_NAME_TO_SLUG.update({
    "miami dade": "miami-dade", "st johns": "st-johns", "st lucie": "st-lucie",
    "santa rosa": "santa-rosa", "indian river": "indian-river", "desoto": "desoto",
    "de soto": "desoto",
})


@lru_cache(maxsize=4096)
def infer_county(agency_name: str, *, hint: Optional[str] = None) -> str:
    """Best-effort county slug for an agency name.

    Returns a county slug, ``statewide`` for entities that span the state, or
    ``unknown`` when nothing matches confidently. ``hint`` is any county the
    portal supplied; it always wins, since a portal that names its county is
    more trustworthy than our string matching.
    """
    if hint:
        h = _normalise(hint)
        if h in _NAME_TO_SLUG:
            return _NAME_TO_SLUG[h]
        if hint in COUNTY_NAMES or hint in PSEUDO_COUNTIES:
            return hint

    if not agency_name:
        return "unknown"

    name = _normalise(agency_name)

    # 1. Explicit "<County> County" is the strongest signal.
    m = re.search(r"\b([a-z][a-z' -]+?)\s+county\b", name)
    if m and _NAME_TO_SLUG.get(m.group(1).strip()):
        return _NAME_TO_SLUG[m.group(1).strip()]

    # 2. Statewide bodies, checked before city matching so "Florida Department
    #    of Transportation District 4" does not get filed under a city.
    if any(marker in name for marker in STATEWIDE_MARKERS):
        return "statewide"

    # 2b. State agencies are routinely published under their bare name —
    #     "Department of Children and Families (DCF)", "Agency for Persons with
    #     Disabilities". No county appears anywhere in the string, and without
    #     this they would all land in `unknown`.
    if _STATE_BODY.match(name):
        return "statewide"

    # 3. Named institutions.
    for needle, slug in INSTITUTION_COUNTY.items():
        if needle in name:
            return slug

    # 4. "City of X" / "Town of X" / "Village of X".
    m = re.search(r"\b(?:city|town|village) of ([a-z' .-]+)", name)
    if m:
        city = _normalise(m.group(1))
        city = re.sub(
            r"\s+(purchasing|procurement|finance|utilities|police|fire|water|"
            r"public works|department|dept|division|office|florida|fl)\b.*$",
            "",
            city,
        ).strip()
        if city in CITY_COUNTY:
            return CITY_COUNTY[city]

    # 5. A bare city name anywhere in the string (longest match wins, so
    #    "Miami Beach" is not swallowed by "Miami").
    for city in sorted(CITY_COUNTY, key=len, reverse=True):
        if re.search(rf"\b{re.escape(city)}\b", name):
            return CITY_COUNTY[city]

    # 6. A bare county name — "Sarasota Schools", "Leon Sheriff".
    for county_name, slug in sorted(
        _NAME_TO_SLUG.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        if re.search(rf"\b{re.escape(county_name)}\b", name):
            return slug

    return "unknown"


def counties_in_region(region: str) -> List[str]:
    return list(REGIONS.get(region, []))


def summarise_coverage(county_slugs) -> Tuple[int, int]:
    """(counties covered, 67) — for the dashboard's coverage meter."""
    real = {c for c in county_slugs if c in COUNTY_NAMES}
    return len(real), len(COUNTY_NAMES)
