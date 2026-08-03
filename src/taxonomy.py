"""The canonical vocabulary of what a government buys.

This module exists because a filter built from *observed* data can only ever
offer what has already come through the door. Ask it for "wetland mitigation"
before a wetland bid has ever been fetched and the option simply is not there —
so the one thing a watchlist is for, being told when something new appears,
is exactly the thing it cannot do.

So the taxonomy is declared, not derived. It is a census of what a Florida
government body can put out to bid, whether or not any such bid is in the
database today. Categories with no current matches are a feature: the watchlist
fires the day the first one is posted.

Two consequences worth stating plainly:

* **Every category here must be reachable.** A category the classifier can
  never emit is a filter that silently matches nothing forever, which is worse
  than not offering it — the user reads "0 matches" as "no such work exists"
  rather than "this filter is broken". ``tests/test_taxonomy.py`` enforces that
  every category either carries patterns or is explicitly marked
  ``anticipated``, and the API reports a live count next to each one so the
  distinction is visible in the UI rather than buried here.
* **The twelve original slugs stay valid.** They are stored on every
  opportunity already fetched and referenced by saved watchlists. They survive
  as ``umbrella`` categories: a bid tagged ``roofing`` is also tagged
  ``construction``, so a watchlist written before this taxonomy existed keeps
  matching exactly what it used to.

Groups are the dropdown's top level. Within a group the order is roughly
most-common-first, since that is the order someone scanning the list expects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .models.opportunity import OfferType

#: The twelve category slugs that predate this module. Stored on live
#: opportunities and referenced by saved watchlists, so they may never be
#: renamed or removed — only widened.
LEGACY_SLUGS = (
    "construction",
    "architecture_engineering",
    "it_software",
    "facilities_maintenance",
    "professional_services",
    "transportation",
    "public_safety",
    "utilities_water",
    "waste_recycling",
    "goods_supplies",
    "healthcare",
    "general",
)


@dataclass(frozen=True)
class Category:
    """One filterable kind of work.

    ``patterns`` are case-insensitive regexes tried against title + description.
    ``umbrella`` names a legacy slug that is applied alongside this one, which
    is what keeps pre-existing watchlists working as the taxonomy grows.
    ``anticipated`` marks a category we expect to see but cannot yet detect
    from a title alone — it stays selectable, and starts matching the moment
    someone gives it patterns.
    """

    slug: str
    label: str
    group: str
    offer: OfferType
    patterns: Tuple[str, ...] = ()
    umbrella: Optional[str] = None
    anticipated: bool = False


@dataclass(frozen=True)
class Group:
    slug: str
    label: str
    blurb: str = ""


GROUPS: Tuple[Group, ...] = (
    Group("construction", "Construction & Trades", "Vertical, horizontal, and the trades"),
    Group("design", "Architecture, Engineering & Design", "CCNA and design professionals"),
    Group("professional", "Professional & Business Services", "Advice, expertise, and back office"),
    Group("it", "Information Technology", "Software, hardware, networks, security"),
    Group("facilities", "Facilities & Grounds", "Keeping buildings and land running"),
    Group("transport", "Transportation & Fleet", "Transit, vehicles, roads in service"),
    Group("utilities", "Utilities, Water & Energy", "Treatment, distribution, power"),
    Group("environment", "Environmental & Waste", "Waste, remediation, monitoring"),
    Group("safety", "Public Safety & Justice", "Police, fire, EMS, corrections"),
    Group("health", "Health & Human Services", "Clinical care and social programs"),
    Group("education", "Education & Training", "Schools, workforce, libraries"),
    Group("goods", "Goods, Equipment & Supplies", "Anything furnished and delivered"),
    Group("property", "Real Estate & Property", "Land, leases, property management"),
    Group("financial", "Financial & Insurance", "Banking, insurance, risk"),
    Group("media", "Media, Marketing & Events", "Communications and public-facing work"),
    Group("food", "Food & Agriculture", "Food service, supply, agriculture"),
    Group("parks", "Parks, Recreation & Culture", "Recreation programs and venues"),
    Group("revenue", "Concessions, Leases & Revenue", "Contracts that pay the government"),
)

# --- the categories ---------------------------------------------------------
#
# Ordering matters twice over: it is the order shown in the dropdown, and
# `classify` walks it top to bottom, so the more specific entry should precede
# the umbrella it rolls up into.

C = Category
_CATS: List[Category] = [
    # -- Construction & Trades ------------------------------------------------
    C("construction", "General construction", "construction", OfferType.CONSTRUCTION, (
        r"\bconstruction\b", r"\brenovation\b", r"\bremodel", r"\bbuild[- ]?out\b",
        r"\bdesign[- ]build\b", r"\bCMAR\b", r"\bgeneral\s+contract",
        r"\bfacility\s+renovation", r"\btenant\s+improvement",
    )),
    C("roadway_bridge", "Roadway & bridge", "construction", OfferType.CONSTRUCTION, (
        r"\bpaving\b", r"\basphalt\b", r"\bmilling\s+and\s+resurfac",
        r"\bresurfacing\b", r"\bsidewalk\b", r"\bcurb\s+and\s+gutter\b",
        r"\bbridge\b", r"\broadway\b", r"\bstreet\s+improvement",
        r"\bguardrail\b", r"\bstriping\b", r"\bpothole\b",
    ), umbrella="construction"),
    C("water_sewer_infra", "Water & sewer infrastructure", "construction", OfferType.CONSTRUCTION, (
        r"\bwater\s+main\b", r"\bforce\s+main\b", r"\bsanitary\s+sewer\b",
        r"\blift\s+station\b", r"\bpump\s+station\b", r"\bstormwater\s+(?:improve|system|pipe)",
        r"\bdrainage\s+improvement", r"\bpipe\s+lining\b", r"\bmanhole\b",
        r"\bpipeline\b", r"\bculvert\b",
    ), umbrella="construction"),
    C("roofing", "Roofing", "construction", OfferType.CONSTRUCTION, (
        r"\broof(?:ing|s)?\b", r"\bre[- ]?roof", r"\bshingle\b", r"\bmembrane\s+roof",
    ), umbrella="construction"),
    C("electrical_trade", "Electrical", "construction", OfferType.CONSTRUCTION, (
        r"\belectrical\s+(?:work|contract|service|install|upgrade|construction)",
        r"\bswitchgear\b", r"\bsubstation\b", r"\bconduit\b", r"\bwiring\b",
    ), umbrella="construction"),
    C("plumbing_trade", "Plumbing", "construction", OfferType.CONSTRUCTION, (
        r"\bplumbing\b", r"\bpiping\s+install", r"\bbackflow\s+install",
    ), umbrella="construction"),
    C("hvac_mechanical", "HVAC & mechanical", "construction", OfferType.CONSTRUCTION, (
        r"\bhvac\b", r"\bair\s+handler\b", r"\bchiller\b", r"\bcooling\s+tower\b",
        r"\bmechanical\s+(?:system|contract|install)", r"\bboiler\b", r"\bductwork\b",
        r"\bair\s+condition", r"\bventilation\b",
    ), umbrella="construction"),
    C("painting_coatings", "Painting & coatings", "construction", OfferType.CONSTRUCTION, (
        r"\bpainting\b", r"\bcoating\b", r"\bwaterproofing\b", r"\bsealant\b",
    ), umbrella="construction"),
    C("flooring", "Flooring", "construction", OfferType.CONSTRUCTION, (
        r"\bflooring\b", r"\bcarpet\b", r"\btile\s+(?:install|replace)", r"\bepoxy\s+floor",
    ), umbrella="construction"),
    C("doors_windows", "Doors, windows & glazing", "construction", OfferType.CONSTRUCTION, (
        r"\bglazing\b", r"\bimpact\s+window", r"\bwindow\s+replacement",
        r"\bdoor\s+(?:replace|install)", r"\boverhead\s+door\b", r"\bhurricane\s+shutter",
    ), umbrella="construction"),
    C("masonry_concrete", "Masonry & concrete", "construction", OfferType.CONSTRUCTION, (
        r"\bconcrete\b", r"\bmasonry\b", r"\bstucco\b", r"\bseawall\s+cap\b",
    ), umbrella="construction"),
    C("structural_steel", "Structural & steel", "construction", OfferType.CONSTRUCTION, (
        r"\bstructural\s+steel\b", r"\bsteel\s+erection\b", r"\bwelding\b",
    ), umbrella="construction"),
    C("demolition_abatement", "Demolition & abatement", "construction", OfferType.CONSTRUCTION, (
        r"\bdemolition\b", r"\bdemo\s+of\b", r"\basbestos\b", r"\blead\s+(?:paint|abate)",
        r"\bmold\s+remediation\b", r"\bboard\s+up\b", r"\blot\s+clear",
    ), umbrella="construction"),
    C("marine_waterfront", "Marine & waterfront", "construction", OfferType.CONSTRUCTION, (
        r"\bseawall\b", r"\bdock\b", r"\bpier\b", r"\bdredg", r"\bboat\s+ramp\b",
        r"\bbulkhead\b", r"\bmarina\s+(?:construct|repair)", r"\bshoreline\b",
    ), umbrella="construction"),
    C("airfield_construction", "Airfield construction", "construction", OfferType.CONSTRUCTION, (
        r"\brunway\b", r"\btaxiway\b", r"\bapron\s+(?:rehab|construct)", r"\bairfield\b",
    ), umbrella="construction"),
    C("fencing_gates", "Fencing & gates", "construction", OfferType.CONSTRUCTION, (
        r"\bfenc(?:e|ing)\b", r"\bgate\s+(?:install|replace|operator)", r"\bbollard\b",
    ), umbrella="construction"),
    C("sitework_earthwork", "Site work & earthwork", "construction", OfferType.CONSTRUCTION, (
        r"\bearthwork\b", r"\bexcavation\b", r"\bgrading\b", r"\bsite\s+work\b",
        r"\bland\s+clearing\b", r"\bfill\s+dirt\b",
    ), umbrella="construction"),
    C("well_drilling", "Wells & drilling", "construction", OfferType.CONSTRUCTION, (
        r"\bwell\s+drill", r"\bmonitoring\s+well\b", r"\binjection\s+well\b", r"\bborehole\b",
    ), umbrella="construction"),
    C("elevator_install", "Elevators & conveyance", "construction", OfferType.CONSTRUCTION, (
        r"\belevator\s+(?:modern|install|replace)", r"\bescalator\b", r"\blift\s+install",
    ), umbrella="construction"),
    C("fire_protection_systems", "Fire protection systems", "construction", OfferType.CONSTRUCTION, (
        r"\bsprinkler\s+system\b", r"\bfire\s+suppression\b", r"\bfire\s+alarm\s+(?:install|system)",
        r"\bstandpipe\b",
    ), umbrella="construction"),
    C("solar_install", "Solar & energy installation", "construction", OfferType.CONSTRUCTION, (
        r"\bsolar\s+(?:panel|array|install|photovolta)", r"\bphotovoltaic\b",
        r"\bbattery\s+storage\b",
    ), umbrella="construction"),
    C("generator_install", "Generators & backup power", "construction", OfferType.CONSTRUCTION, (
        r"\bgenerator\b", r"\bemergency\s+power\b", r"\bUPS\s+system\b", r"\btransfer\s+switch\b",
    ), umbrella="construction"),

    # -- Architecture, Engineering & Design -----------------------------------
    C("architecture_engineering", "Architecture & engineering", "design",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\barchitect(?:ural|ure)?\b", r"\bengineering\b", r"\bCCNA\b",
        r"\bdesign\s+services\b", r"\bA/?E\s+services\b", r"\bcontinuing\s+services\b",
    )),
    C("civil_engineering", "Civil engineering", "design", OfferType.PROFESSIONAL_SERVICES, (
        r"\bcivil\s+engineer", r"\bsite\s+civil\b", r"\bdrainage\s+(?:study|design)",
    ), umbrella="architecture_engineering"),
    C("structural_engineering", "Structural engineering", "design", OfferType.PROFESSIONAL_SERVICES, (
        r"\bstructural\s+engineer", r"\bstructural\s+(?:assess|analysis|design)",
        r"\bmilestone\s+inspection\b", r"\bthreshold\s+inspection\b",
    ), umbrella="architecture_engineering"),
    C("mep_engineering", "MEP engineering", "design", OfferType.PROFESSIONAL_SERVICES, (
        r"\bmechanical,?\s+electrical", r"\bMEP\b", r"\belectrical\s+engineer",
    ), umbrella="architecture_engineering"),
    C("environmental_engineering", "Environmental engineering", "design",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\benvironmental\s+(?:engineer|consult|assess|permit)",
        r"\bNEPA\b", r"\benvironmental\s+impact\b",
    ), umbrella="architecture_engineering"),
    C("geotechnical", "Geotechnical", "design", OfferType.PROFESSIONAL_SERVICES, (
        r"\bgeotechnical\b", r"\bsoil\s+(?:boring|test)", r"\bsubsurface\s+investigat",
    ), umbrella="architecture_engineering"),
    C("surveying_mapping", "Surveying & mapping", "design", OfferType.PROFESSIONAL_SERVICES, (
        r"\bsurvey(?:ing|or)?\b", r"\bmapping\b", r"\baerial\s+(?:photo|survey)",
        r"\bLiDAR\b", r"\bphotogrammetr",
    ), umbrella="architecture_engineering"),
    C("landscape_architecture", "Landscape architecture", "design",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\blandscape\s+architect", r"\bstreetscape\s+design\b",
    ), umbrella="architecture_engineering"),
    C("interior_design", "Interior design", "design", OfferType.PROFESSIONAL_SERVICES, (
        r"\binterior\s+design", r"\bspace\s+planning\b",
    ), umbrella="architecture_engineering"),
    C("construction_management", "Construction management & CEI", "design",
      OfferType.PROFESSIONAL_SERVICES, (
        r"construction\s+management", r"\bCEI\b", r"\bowner'?s\s+representative\b",
        r"\bconstruction\s+engineering\s+and\s+inspection\b", r"\bprogram\s+management\b",
    ), umbrella="architecture_engineering"),
    C("materials_testing", "Materials testing & inspection", "design",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\bmaterials\s+testing\b", r"\btesting\s+laborator", r"\bspecial\s+inspection\b",
        r"\bnon[- ]?destructive\s+test",
    ), umbrella="architecture_engineering"),
    C("transportation_planning", "Transportation planning", "design",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\btraffic\s+(?:study|engineer|analysis)", r"\btransportation\s+planning\b",
        r"\bcorridor\s+study\b", r"\bmobility\s+plan\b",
    ), umbrella="architecture_engineering"),
    C("urban_planning", "Urban & comprehensive planning", "design",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\burban\s+design\b", r"\bcomprehensive\s+plan\b", r"\bmaster\s+plan\b",
        r"\bland\s+use\s+plan", r"\bzoning\s+(?:study|code)", r"\bplanning\b",
    ), umbrella="architecture_engineering"),

    # -- Professional & Business Services -------------------------------------
    C("professional_services", "General professional services", "professional",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\bconsult(?:ing|ant)\b", r"\bprofessional\s+services\b",
        r"\bproject\s+management\b", r"\btechnical\s+assistance\b",
    )),
    C("legal_services", "Legal services", "professional", OfferType.PROFESSIONAL_SERVICES, (
        r"\blegal\s+(?:services|counsel|represent)", r"\battorney\b", r"\blaw\s+firm\b",
        r"\boutside\s+counsel\b", r"\bbond\s+counsel\b", r"\blitigation\b",
    ), umbrella="professional_services"),
    C("audit_accounting", "Audit & accounting", "professional", OfferType.PROFESSIONAL_SERVICES, (
        r"\baudit(?:ing|or)?\b", r"\baccounting\s+services\b", r"\bCPA\b",
        r"\bfinancial\s+statement\b", r"\bsingle\s+audit\b",
    ), umbrella="professional_services"),
    C("financial_advisory", "Financial advisory", "professional", OfferType.PROFESSIONAL_SERVICES, (
        r"\bfinancial\s+advis", r"\bmunicipal\s+advis", r"\bfeasibility\s+study\b",
        r"\brate\s+study\b", r"\bimpact\s+fee\s+study\b",
    ), umbrella="professional_services"),
    C("actuarial", "Actuarial services", "professional", OfferType.PROFESSIONAL_SERVICES, (
        r"\bactuarial\b", r"\bactuary\b",
    ), umbrella="professional_services"),
    C("management_consulting", "Management consulting", "professional",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\bmanagement\s+consult", r"\borganizational\s+(?:study|assess)",
        r"\bclassification\s+and\s+compensation\b", r"\bstrategic\s+plan",
        r"\bbusiness\s+process\b",
    ), umbrella="professional_services"),
    C("lobbying_govt_relations", "Lobbying & government relations", "professional",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\blobby(?:ing|ist)\b", r"\bgovernment(?:al)?\s+(?:relations|affairs)\b",
        r"\blegislative\s+consult",
    ), umbrella="professional_services"),
    C("hr_services", "Human resources services", "professional", OfferType.PROFESSIONAL_SERVICES, (
        r"\bhuman\s+resources?\b", r"\bexecutive\s+search\b", r"\brecruit(?:ing|ment)\b",
        r"\bbackground\s+(?:screen|check)", r"\bdrug\s+testing\b",
    ), umbrella="professional_services"),
    C("staffing_temp", "Staffing & temporary labor", "professional",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\bstaffing\b", r"\btemporary\s+(?:labor|personnel|staff)",
        r"\bcontract\s+employee\b", r"\bemployment\s+agency\b",
    ), umbrella="professional_services"),
    C("records_management", "Records & document management", "professional",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\brecords\s+management\b", r"\bdocument\s+(?:scan|imaging|conversion)",
        r"\bmicrofilm\b", r"\bshredding\b",
    ), umbrella="professional_services"),
    C("translation_interpretation", "Translation & interpretation", "professional",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\btranslation\b", r"\binterpret(?:er|ation)\b", r"\bsign\s+language\b",
        r"\bASL\b",
    ), umbrella="professional_services"),
    C("court_reporting", "Court reporting", "professional", OfferType.PROFESSIONAL_SERVICES, (
        r"\bcourt\s+report", r"\bstenograph", r"\btranscription\s+services\b",
    ), umbrella="professional_services"),
    C("grant_administration", "Grant writing & administration", "professional",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\bgrant\s+(?:writ|administ|manage|consult)", r"\bCDBG\b",
        r"\bdisaster\s+recovery\s+administ",
    ), umbrella="professional_services"),
    C("program_evaluation", "Program evaluation & research", "professional",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\bprogram\s+evaluation\b", r"\bneeds\s+assessment\b", r"\bdisparity\s+study\b",
    ), umbrella="professional_services"),

    # -- Information Technology -----------------------------------------------
    C("it_software", "Software & IT services", "it", OfferType.SERVICES, (
        r"\bsoftware\b", r"\binformation\s+technology\b", r"\bIT\s+services\b",
        r"\bapplication\s+(?:develop|support|system)", r"\bsystem\s+integrat",
    )),
    C("saas_subscription", "SaaS & software licensing", "it", OfferType.SERVICES, (
        r"\bsoftware\s+(?:licens|subscription|maintenance|as\s+a\s+service)",
        r"\bSaaS\b", r"\bannual\s+licens", r"\brenewal\s+of\s+licens",
    ), umbrella="it_software"),
    C("cybersecurity", "Cybersecurity", "it", OfferType.SERVICES, (
        r"\bcyber\b", r"\bpenetration\s+test", r"\bmanaged\s+security\b", r"\bSOC\b",
        r"\bvulnerability\s+assess", r"\bsecurity\s+assess", r"\bincident\s+response\b",
    ), umbrella="it_software"),
    C("cloud_hosting", "Cloud & hosting", "it", OfferType.SERVICES, (
        r"\bcloud\b", r"\bhosting\b", r"\bdata\s+center\b", r"\bcolocation\b",
        r"\bdisaster\s+recovery\s+(?:site|service)", r"\bbackup\s+solution\b",
    ), umbrella="it_software"),
    C("network_infrastructure", "Network infrastructure", "it", OfferType.SERVICES, (
        r"\bnetwork\s+(?:service|infrastructure|upgrade|equipment)", r"\bfiber\s+optic\b",
        r"\bstructured\s+cabling\b", r"\bswitch(?:es)?\s+and\s+router", r"\bWi[- ]?Fi\b",
        r"\bwireless\s+network\b", r"\bLAN\b", r"\bWAN\b",
    ), umbrella="it_software"),
    C("telecom_voice", "Telecom & voice", "it", OfferType.SERVICES, (
        r"\btelecom", r"\bVoIP\b", r"\btelephone\s+system\b", r"\bcellular\b",
        r"\bmobile\s+service\b", r"\bpaging\s+service\b",
    ), umbrella="it_software"),
    C("radio_communications", "Radio & land mobile communications", "it", OfferType.MIXED, (
        r"\bland\s+mobile\s+radio\b", r"\bLMR\b", r"\bP25\b", r"\btwo[- ]way\s+radio\b",
        r"\bradio\s+system\b", r"\bdispatch\s+console\b",
    ), umbrella="it_software"),
    C("data_analytics", "Data & analytics", "it", OfferType.SERVICES, (
        r"\bdata\s+(?:analytic|warehouse|migration|governance)", r"\bbusiness\s+intelligence\b",
        r"\bdashboard\b", r"\bmachine\s+learning\b", r"\bartificial\s+intelligence\b",
    ), umbrella="it_software"),
    C("gis_systems", "GIS systems", "it", OfferType.SERVICES, (
        r"\bGIS\b", r"\bgeographic\s+information\b", r"\bEsri\b", r"\bArcGIS\b",
    ), umbrella="it_software"),
    C("erp_financial_systems", "ERP & financial systems", "it", OfferType.SERVICES, (
        r"\bERP\b", r"\benterprise\s+resource\b", r"\bfinancial\s+system\b",
        r"\butility\s+billing\s+system\b", r"\bpayroll\s+system\b",
    ), umbrella="it_software"),
    C("public_safety_software", "Public safety software (CAD/RMS)", "it", OfferType.SERVICES, (
        r"\bCAD/?RMS\b", r"\bcomputer[- ]aided\s+dispatch\b", r"\brecords\s+management\s+system\b",
        r"\bjail\s+management\s+system\b", r"\bevidence\s+management\b",
    ), umbrella="it_software"),
    C("permitting_software", "Permitting & land management software", "it", OfferType.SERVICES, (
        r"\bpermitting\s+(?:software|system)", r"\bland\s+management\s+system\b",
        r"\bcode\s+enforcement\s+software\b", r"\basset\s+management\s+system\b",
    ), umbrella="it_software"),
    C("website_digital", "Website & digital services", "it", OfferType.SERVICES, (
        r"\bwebsite\b", r"\bweb\s+(?:design|development|portal)", r"\bintranet\b",
        r"\bmobile\s+app\b", r"\bdigital\s+accessibility\b", r"\bADA\s+website\b",
    ), umbrella="it_software"),
    C("av_systems", "Audio-visual systems", "it", OfferType.MIXED, (
        r"\baudio[- ]?visual\b", r"\bA/?V\s+system\b", r"\bchamber\s+(?:av|audio)",
        r"\bvideo\s+wall\b", r"\bbroadcast\s+equipment\b",
    ), umbrella="it_software"),
    C("surveillance_access", "Surveillance & access control", "it", OfferType.MIXED, (
        r"\bcamera\s+system\b", r"\bCCTV\b", r"\bvideo\s+surveillance\b",
        r"\baccess\s+control\b", r"\bbadge\s+system\b", r"\brecording\s+system\b",
    ), umbrella="it_software"),
    C("it_hardware", "IT hardware", "it", OfferType.GOODS, (
        r"\bcomputer\s+(?:hardware|equipment)\b", r"\blaptop\b", r"\bdesktop\s+comput",
        r"\bserver\s+(?:hardware|purchase)", r"\btablet\b", r"\bprinter\s+purchase\b",
    ), umbrella="it_software"),
    C("help_desk", "Help desk & IT support", "it", OfferType.SERVICES, (
        r"\bhelp\s+desk\b", r"\bservice\s+desk\b", r"\bIT\s+support\b",
        r"\bmanaged\s+(?:IT|services)\b", r"\bstaff\s+augmentation\b",
    ), umbrella="it_software"),
    C("managed_print", "Managed print", "it", OfferType.SERVICES, (
        r"\bmanaged\s+print\b", r"\bcopier\b", r"\bmultifunction\s+device\b",
    ), umbrella="it_software"),

    # -- Facilities & Grounds --------------------------------------------------
    C("facilities_maintenance", "Facilities maintenance", "facilities", OfferType.SERVICES, (
        r"\bmaintenance\b", r"\bfacility\s+(?:service|support)", r"\brepair\s+services\b",
        r"\bhandyman\b", r"\bbuilding\s+maintenance\b",
    )),
    C("janitorial_custodial", "Janitorial & custodial", "facilities", OfferType.SERVICES, (
        r"\bjanitorial\b", r"\bcustodial\b", r"\bcleaning\s+service", r"\bporter\s+service\b",
        r"\bdisinfect", r"\bfloor\s+care\b",
    ), umbrella="facilities_maintenance"),
    C("landscaping_grounds", "Landscaping & grounds", "facilities", OfferType.SERVICES, (
        r"\blandscap", r"\blawn\b", r"\bmowing\b", r"\bgrounds\s+maintenance\b",
        r"\birrigation\b", r"\bright[- ]of[- ]way\s+mow", r"\bsod\b",
    ), umbrella="facilities_maintenance"),
    C("tree_services", "Tree & arbor services", "facilities", OfferType.SERVICES, (
        r"\btree\s+(?:trim|remov|servic|plant|prun)", r"\barborist\b", r"\bstump\s+grind",
        r"\bcanopy\s+(?:manage|assess)",
    ), umbrella="facilities_maintenance"),
    C("pest_control", "Pest control", "facilities", OfferType.SERVICES, (
        r"\bpest\s+control\b", r"\bexterminat", r"\bterm(?:ite|inal)\s+treat", r"\brodent\b",
    ), umbrella="facilities_maintenance"),
    C("pressure_washing", "Pressure washing", "facilities", OfferType.SERVICES, (
        r"\bpressure\s+wash", r"\bpower\s+wash", r"\bsteam\s+clean",
    ), umbrella="facilities_maintenance"),
    C("security_guard", "Security guard services", "facilities", OfferType.SERVICES, (
        r"\bsecurity\s+(?:guard|officer|service|patrol)", r"\bunarmed\s+security\b",
        r"\barmed\s+security\b", r"\bcrowd\s+control\b",
    ), umbrella="facilities_maintenance"),
    C("hvac_maintenance", "HVAC maintenance", "facilities", OfferType.SERVICES, (
        r"\bhvac\s+(?:maintenance|service|repair|preventive)", r"\bchiller\s+maintenance\b",
        r"\bair\s+filter\s+(?:service|replacement)",
    ), umbrella="facilities_maintenance"),
    C("elevator_maintenance", "Elevator maintenance", "facilities", OfferType.SERVICES, (
        r"\belevator\s+(?:maintenance|service|inspect|repair)",
    ), umbrella="facilities_maintenance"),
    C("fire_alarm_inspection", "Fire & life-safety inspection", "facilities", OfferType.SERVICES, (
        r"\bfire\s+(?:alarm|extinguisher)\s+(?:inspect|service|test|maintenance)",
        r"\blife\s+safety\s+inspect", r"\bsprinkler\s+inspect",
    ), umbrella="facilities_maintenance"),
    C("pool_aquatic_maintenance", "Pool & aquatic maintenance", "facilities", OfferType.SERVICES, (
        r"\bpool\s+(?:maintenance|service|chemical|clean)", r"\baquatic\s+facility\s+maintenance\b",
    ), umbrella="facilities_maintenance"),
    C("moving_storage", "Moving, storage & warehousing", "facilities", OfferType.SERVICES, (
        r"\bmoving\s+service", r"\brelocation\s+service", r"\bwarehous", r"\bstorage\s+service",
    ), umbrella="facilities_maintenance"),
    C("window_cleaning", "Window & exterior cleaning", "facilities", OfferType.SERVICES, (
        r"\bwindow\s+clean", r"\bfacade\s+clean", r"\bhigh[- ]rise\s+clean",
    ), umbrella="facilities_maintenance"),

    # -- Transportation & Fleet -----------------------------------------------
    C("transportation", "Transportation services", "transport", OfferType.SERVICES, (
        r"\btransportation\b", r"\btransit\b", r"\bbus\b", r"\bshuttle\b",
    )),
    C("transit_operations", "Transit operations", "transport", OfferType.SERVICES, (
        r"\btransit\s+(?:operation|service|system)", r"\bfixed[- ]route\b",
        r"\bcircular\s+route\b", r"\btrolley\b",
    ), umbrella="transportation"),
    C("paratransit", "Paratransit & specialized transport", "transport", OfferType.SERVICES, (
        r"\bparatransit\b", r"\bADA\s+transport", r"\bnon[- ]emergency\s+(?:medical\s+)?transport",
        r"\bwheelchair\s+transport",
    ), umbrella="transportation"),
    C("school_transportation", "School transportation", "transport", OfferType.SERVICES, (
        r"\bschool\s+bus\b", r"\bstudent\s+transport",
    ), umbrella="transportation"),
    C("fleet_maintenance", "Fleet maintenance & repair", "transport", OfferType.SERVICES, (
        r"\bfleet\s+(?:maintenance|service|management)", r"\bvehicle\s+(?:repair|maintenance)",
        r"\bauto\s+(?:repair|body)", r"\btransmission\s+repair\b",
    ), umbrella="transportation"),
    C("vehicle_purchase", "Vehicle purchase & lease", "transport", OfferType.GOODS, (
        r"\bvehicle\s+(?:purchase|acquisition|lease)", r"\bpickup\s+truck\b",
        r"\bsedan\b", r"\bpatrol\s+vehicle\b", r"\bambulance\s+purchase\b",
        r"\bfire\s+(?:apparatus|truck|engine)\b", r"\bbus\s+(?:purchase|procurement)",
    ), umbrella="goods_supplies"),
    C("heavy_equipment", "Heavy equipment", "transport", OfferType.GOODS, (
        r"\bheavy\s+equipment\b", r"\bbackhoe\b", r"\bexcavator\b", r"\bloader\b",
        r"\bbucket\s+truck\b", r"\bvacuum\s+truck\b", r"\bcrane\b", r"\btractor\b",
    ), umbrella="goods_supplies"),
    C("fuel_supply", "Fuel & lubricants", "transport", OfferType.GOODS, (
        r"\bfuel\b", r"\bdiesel\b", r"\bgasoline\b", r"\blubricant\b", r"\bmotor\s+oil\b",
    ), umbrella="transportation"),
    C("towing_recovery", "Towing & recovery", "transport", OfferType.SERVICES, (
        r"\btowing\b", r"\bwrecker\b", r"\bvehicle\s+impound\b",
    ), umbrella="transportation"),
    C("parking_management", "Parking management", "transport", OfferType.SERVICES, (
        r"\bparking\b", r"\bvalet\b", r"\bparking\s+(?:meter|enforcement|garage)",
    ), umbrella="transportation"),
    C("airport_services", "Airport services", "transport", OfferType.MIXED, (
        r"\bairport\b", r"\bFLL\b", r"\baviation\b", r"\bterminal\s+(?:service|operation)",
        r"\bground\s+handling\b",
    ), umbrella="transportation"),
    C("seaport_marine_services", "Seaport & marine services", "transport", OfferType.MIXED, (
        r"\bseaport\b", r"\bport\s+(?:everglades|operation|service)", r"\bstevedor",
        r"\bharbor\b", r"\bferry\b",
    ), umbrella="transportation"),
    C("traffic_signals", "Traffic signals & ITS", "transport", OfferType.MIXED, (
        r"\btraffic\s+signal\b", r"\bsignalization\b", r"\bintelligent\s+transportation\b",
        r"\bITS\s+(?:system|equipment)", r"\bschool\s+zone\s+flash",
    ), umbrella="transportation"),
    C("street_lighting", "Street & area lighting", "transport", OfferType.MIXED, (
        r"\bstreet\s+light", r"\broadway\s+lighting\b", r"\bdecorative\s+light",
    ), umbrella="transportation"),
    C("ev_charging", "EV charging infrastructure", "transport", OfferType.MIXED, (
        r"\bEV\s+charg", r"\belectric\s+vehicle\s+charg", r"\bcharging\s+station\b",
    ), umbrella="transportation"),

    # -- Utilities, Water & Energy --------------------------------------------
    C("utilities_water", "Water & utilities", "utilities", OfferType.MIXED, (
        r"\bwater\b", r"\bwastewater\b", r"\butilit", r"\bWWTF\b", r"\bWTP\b",
    )),
    C("water_treatment", "Water treatment", "utilities", OfferType.MIXED, (
        r"\bwater\s+treatment\b", r"\bpotable\s+water\b", r"\bdesalinat",
        r"\breverse\s+osmosis\b", r"\bfiltration\s+(?:plant|system)",
    ), umbrella="utilities_water"),
    C("wastewater_treatment", "Wastewater treatment", "utilities", OfferType.MIXED, (
        r"\bwastewater\s+treatment\b", r"\bsludge\b", r"\bbiosolids\b",
        r"\beffluent\b", r"\bseptic\b",
    ), umbrella="utilities_water"),
    C("treatment_chemicals", "Treatment chemicals", "utilities", OfferType.GOODS, (
        r"\bchemical\b", r"\baluminum\s+sulfate\b", r"\bsodium\s+hypochlorite\b",
        r"\bcarbon\s+dioxide\b", r"\bchlorine\b", r"\bpolymer\b", r"\bcaustic\s+soda\b",
    ), umbrella="utilities_water"),
    C("water_meters", "Meters & AMI", "utilities", OfferType.MIXED, (
        r"\bmeter\s+(?:read|replac|install)", r"\bwater\s+meter\b", r"\bAMI\b",
        r"\badvanced\s+metering\b",
    ), umbrella="utilities_water"),
    C("stormwater_management", "Stormwater management", "utilities", OfferType.MIXED, (
        r"\bstormwater\b", r"\bcanal\s+(?:maintenance|dredg)", r"\bdrainage\s+maintenance\b",
        r"\bcatch\s+basin\b", r"\bMS4\b",
    ), umbrella="utilities_water"),
    C("pipeline_rehabilitation", "Pipeline rehabilitation", "utilities", OfferType.MIXED, (
        r"\bpipe\s+(?:rehab|lining|burst)", r"\bCIPP\b", r"\bsewer\s+(?:rehab|assessment)",
        r"\bmanhole\s+rehab", r"\bsmoke\s+testing\b",
    ), umbrella="utilities_water"),
    C("utility_locating", "Utility locating & inspection", "utilities", OfferType.SERVICES, (
        r"\butility\s+locat", r"\bsubsurface\s+utility\s+engineering\b", r"\bSUE\b",
        r"\bCCTV\s+(?:sewer|pipe)", r"\bvideo\s+pipe\s+inspect",
    ), umbrella="utilities_water"),
    C("electric_utility", "Electric utility services", "utilities", OfferType.MIXED, (
        r"\belectric\s+(?:utility|service|distribution)", r"\bpower\s+supply\s+agreement\b",
        r"\bsubstation\s+maintenance\b",
    ), umbrella="utilities_water"),
    C("natural_gas", "Natural gas", "utilities", OfferType.MIXED, (
        r"\bnatural\s+gas\b", r"\bpropane\b", r"\bLNG\b",
    ), umbrella="utilities_water"),
    C("energy_performance", "Energy performance & efficiency", "utilities", OfferType.MIXED, (
        r"\benergy\s+(?:performance|efficien|audit|savings)", r"\bESCO\b",
        r"\bLED\s+retrofit\b", r"\bbuilding\s+automation\b",
    ), umbrella="utilities_water"),
    C("backflow_testing", "Backflow & cross-connection", "utilities", OfferType.SERVICES, (
        r"\bbackflow\s+(?:test|prevent|certif)", r"\bcross[- ]connection\b",
    ), umbrella="utilities_water"),

    # -- Environmental & Waste -------------------------------------------------
    C("waste_recycling", "Waste & recycling", "environment", OfferType.SERVICES, (
        r"\bsolid\s+waste\b", r"\brecycl", r"\blandfill\b", r"\bdebris\b",
        r"\bhazardous\b", r"\bwaste\s+(?:collection|disposal)",
    )),
    C("solid_waste_collection", "Solid waste collection", "environment", OfferType.SERVICES, (
        r"\bgarbage\s+collect", r"\brefuse\s+collect", r"\bcurbside\s+collect",
        r"\bbulk\s+(?:trash|waste)\b", r"\byard\s+waste\b", r"\broll[- ]?off\b",
    ), umbrella="waste_recycling"),
    C("recycling_processing", "Recycling processing", "environment", OfferType.SERVICES, (
        r"\brecycling\s+(?:process|facility|material)", r"\bMRF\b",
        r"\bsingle[- ]stream\b", r"\bscrap\s+metal\b",
    ), umbrella="waste_recycling"),
    C("landfill_operations", "Landfill operations", "environment", OfferType.SERVICES, (
        r"\blandfill\s+(?:operat|gas|cell|closure)", r"\btransfer\s+station\b",
        r"\bleachate\b",
    ), umbrella="waste_recycling"),
    C("hazardous_waste", "Hazardous waste", "environment", OfferType.SERVICES, (
        r"\bhazardous\s+(?:waste|material)", r"\bhousehold\s+hazardous\b",
        r"\bbiohazard\b", r"\bmedical\s+waste\b", r"\bused\s+oil\b",
    ), umbrella="waste_recycling"),
    C("disaster_debris", "Disaster debris management", "environment", OfferType.SERVICES, (
        r"\bdisaster\s+debris\b", r"\bstorm\s+debris\b", r"\bdebris\s+monitor",
        r"\bemergency\s+debris\b", r"\bhurricane\s+(?:recovery|debris)",
    ), umbrella="waste_recycling"),
    C("environmental_remediation", "Environmental remediation", "environment",
      OfferType.SERVICES, (
        r"\bremediat", r"\bcontamina", r"\bbrownfield\b", r"\bsoil\s+removal\b",
        r"\bpetroleum\s+cleanup\b", r"\btank\s+removal\b",
    )),
    # No umbrella below this line in the group. These are environmental work,
    # not waste-stream work, and the old `waste_recycling` patterns never
    # reached them — rolling them up would invent false positives in the very
    # filter someone picked to be precise, rather than preserve old behaviour.
    C("environmental_monitoring", "Environmental monitoring", "environment",
      OfferType.SERVICES, (
        r"\benvironmental\s+monitor", r"\bgroundwater\s+monitor", r"\bair\s+quality\b",
        r"\bemissions\s+test", r"\bnoise\s+study\b",
    )),
    C("laboratory_services", "Laboratory & water quality testing", "environment",
      OfferType.SERVICES, (
        r"\blaborator", r"\bwater\s+quality\s+(?:test|sampl|analys)",
        r"\bsample\s+analysis\b", r"\bNELAP\b",
    )),
    C("mosquito_control", "Mosquito & vector control", "environment", OfferType.SERVICES, (
        r"\bmosquito\b", r"\bvector\s+control\b", r"\baerial\s+spray",
        r"\blarvicide\b", r"\badulticide\b",
    )),
    C("beach_renourishment", "Beach & shoreline restoration", "environment",
      OfferType.MIXED, (
        r"\bbeach\s+(?:renourish|nourish|restor)", r"\bdune\s+restor", r"\bsand\s+placement\b",
    )),
    C("habitat_mitigation", "Habitat & wetland mitigation", "environment", OfferType.SERVICES, (
        r"\bwetland\b", r"\bmitigation\s+(?:bank|credit|area)", r"\bhabitat\s+restor",
        r"\bexotic\s+(?:plant|vegetation)\s+remov", r"\bseagrass\b", r"\bmangrove\b",
    )),

    # -- Public Safety & Justice -----------------------------------------------
    C("public_safety", "Public safety", "safety", OfferType.MIXED, (
        r"\bpublic\s+safety\b", r"\bpolice\b", r"\bfire\s+(?:department|rescue|station)\b",
        r"\bemergency\b", r"\bsheriff\b", r"\bsecurity\b",
    )),
    C("law_enforcement_equipment", "Law enforcement equipment", "safety", OfferType.GOODS, (
        r"\bbody[- ]worn\s+camera\b", r"\btaser\b", r"\bballistic\s+vest\b",
        r"\bbody\s+armor\b", r"\bfirearm\b", r"\bammunition\b", r"\bin[- ]car\s+camera\b",
        r"\bpolice\s+equipment\b",
    ), umbrella="public_safety"),
    C("fire_rescue_equipment", "Fire & rescue equipment", "safety", OfferType.GOODS, (
        r"\bturnout\s+gear\b", r"\bbunker\s+gear\b", r"\bSCBA\b", r"\bfire\s+hose\b",
        r"\bextrication\s+(?:tool|equipment)", r"\bfire\s+equipment\b",
    ), umbrella="public_safety"),
    C("ems_services", "EMS & ambulance services", "safety", OfferType.SERVICES, (
        r"\bEMS\b", r"\bambulance\s+service\b", r"\bemergency\s+medical\s+service",
        r"\bEMT\b", r"\bparamedic\b", r"\bmedical\s+transport\b",
    ), umbrella="public_safety"),
    C("emergency_management", "Emergency management", "safety", OfferType.SERVICES, (
        r"\bemergency\s+(?:management|operations|preparedness)", r"\bCOOP\b",
        r"\bhazard\s+mitigation\s+plan\b", r"\bEOC\b", r"\bmass\s+notification\b",
    ), umbrella="public_safety"),
    C("corrections_services", "Corrections & detention", "safety", OfferType.SERVICES, (
        r"\bcorrection", r"\binmate\b", r"\bdetention\b", r"\bjail\b", r"\bprison\b",
        r"\bcommissary\b", r"\bre[- ]?entry\s+program\b",
    ), umbrella="public_safety"),
    C("forensic_services", "Forensic & crime lab", "safety", OfferType.SERVICES, (
        r"\bforensic\b", r"\bcrime\s+(?:lab|scene)", r"\bDNA\s+(?:test|analys)",
        r"\btoxicolog", r"\bmedical\s+examiner\b", r"\bautopsy\b",
    ), umbrella="public_safety"),
    C("animal_control", "Animal services & control", "safety", OfferType.SERVICES, (
        r"\banimal\s+(?:control|service|shelter|care)", r"\bveterinar", r"\bspay\b",
        r"\bkennel\b",
    ), umbrella="public_safety"),
    C("code_enforcement", "Code enforcement & inspection", "safety", OfferType.SERVICES, (
        r"\bcode\s+enforcement\b", r"\bbuilding\s+(?:inspection|official)\s+service",
        r"\bplan\s+review\s+service", r"\bpermit\s+(?:review|process)\s+service",
    ), umbrella="public_safety"),
    C("dispatch_911", "911 & dispatch", "safety", OfferType.MIXED, (
        r"\b911\b", r"\bE9[- ]?1[- ]?1\b", r"\bdispatch\b", r"\bnext\s+generation\s+911\b",
    ), umbrella="public_safety"),
    C("crossing_guards", "Crossing guards", "safety", OfferType.SERVICES, (
        r"\bcrossing\s+guard\b", r"\bschool\s+crossing\b",
    ), umbrella="public_safety"),
    C("ppe_safety_equipment", "PPE & safety equipment", "safety", OfferType.GOODS, (
        r"\bpersonal\s+protective\s+equipment\b", r"\bPPE\b", r"\bsafety\s+(?:equipment|supplies)",
        r"\bhard\s+hat\b", r"\bhigh[- ]visibility\b",
    ), umbrella="goods_supplies"),
    C("security_screening", "Security screening", "safety", OfferType.MIXED, (
        r"\bx[- ]?ray\s+(?:machine|screen)", r"\bmagnetometer\b", r"\bscreening\s+equipment\b",
        r"\bweapons\s+detection\b",
    ), umbrella="public_safety"),

    # -- Health & Human Services -----------------------------------------------
    C("healthcare", "Healthcare", "health", OfferType.MIXED, (
        r"\bmedical\b", r"\bhealth\b", r"\bhospital\b", r"\bclinical\b", r"\bpatient\b",
    )),
    C("behavioral_health", "Behavioral & mental health", "health", OfferType.SERVICES, (
        r"\bbehavioral\s+health\b", r"\bmental\s+health\b", r"\bcounsel(?:ing|or)\b",
        r"\bcrisis\s+(?:intervention|stabiliz)", r"\bBaker\s+Act\b", r"\bpsychiatr",
    ), umbrella="healthcare"),
    C("substance_abuse", "Substance abuse services", "health", OfferType.SERVICES, (
        r"\bsubstance\s+abuse\b", r"\baddiction\b", r"\bdetox", r"\bopioid\b",
        r"\bmedication[- ]assisted\s+treatment\b",
    ), umbrella="healthcare"),
    C("medical_supplies", "Medical supplies & equipment", "health", OfferType.GOODS, (
        r"\bmedical\s+(?:supplies|equipment)", r"\bdefibrillator\b", r"\bAED\b",
        r"\bpharmaceutical\b", r"\bvaccine\b", r"\bglove\s+(?:purchase|supply)",
    ), umbrella="healthcare"),
    C("clinical_services", "Clinical & nursing services", "health", OfferType.SERVICES, (
        r"\bnursing\s+service", r"\bphysician\s+service", r"\bclinical\s+service",
        r"\bhome\s+health\b", r"\bskilled\s+nursing\b", r"\btelehealth\b",
    ), umbrella="healthcare"),
    C("dental_services", "Dental services", "health", OfferType.SERVICES, (
        r"\bdental\b", r"\bdentist\b", r"\borthodont",
    ), umbrella="healthcare"),
    C("pharmacy_services", "Pharmacy services", "health", OfferType.MIXED, (
        r"\bpharmacy\b", r"\bpharmacist\b", r"\bprescription\s+(?:drug|benefit)",
        r"\bPBM\b",
    ), umbrella="healthcare"),
    C("senior_services", "Senior & aging services", "health", OfferType.SERVICES, (
        r"\bsenior\s+(?:service|center|program)", r"\belderly\b", r"\baging\b",
        r"\bmeals\s+on\s+wheels\b", r"\badult\s+day\s+care\b",
    )),
    C("child_family_services", "Child & family services", "health", OfferType.SERVICES, (
        r"\bchild\s+(?:welfare|protect|care)", r"\bfoster\s+care\b", r"\bfamily\s+service",
        r"\bhead\s+start\b", r"\bjuvenile\s+(?:program|justice)",
    )),
    C("homeless_services", "Homeless & housing assistance", "health", OfferType.SERVICES, (
        r"\bhomeless", r"\bshelter\s+(?:service|operation)", r"\brapid\s+re[- ]?hous",
        r"\bhousing\s+assistance\b", r"\bcontinuum\s+of\s+care\b",
    )),
    C("food_assistance", "Food & nutrition assistance", "health", OfferType.SERVICES, (
        r"\bfood\s+(?:bank|pantry|assistance)", r"\bnutrition\s+program\b", r"\bWIC\b",
        r"\bcongregate\s+meal\b",
    )),
    C("veterans_services", "Veterans services", "health", OfferType.SERVICES, (
        r"\bveteran", r"\bVA\s+program\b",
    )),
    C("disability_services", "Disability services", "health", OfferType.SERVICES, (
        r"\bdisabilit", r"\bdevelopmental\s+disab", r"\bvocational\s+rehab",
        r"\bindependent\s+living\b",
    )),
    C("public_health_programs", "Public health programs", "health", OfferType.SERVICES, (
        r"\bpublic\s+health\b", r"\bepidemiolog", r"\bimmuniz", r"\bcommunity\s+health\b",
        r"\bhealth\s+education\b",
    ), umbrella="healthcare"),

    # -- Education & Training --------------------------------------------------
    C("education_services", "Education services", "education", OfferType.SERVICES, (
        r"\beducation(?:al)?\s+(?:service|program)", r"\bschool\s+(?:program|service)",
        r"\bcharter\s+school\b", r"\bacademic\b",
    )),
    C("workforce_training", "Workforce & vocational training", "education", OfferType.SERVICES, (
        r"\bworkforce\s+(?:training|development)", r"\bvocational\s+training\b",
        r"\bapprentice", r"\bjob\s+placement\b", r"\bWIOA\b",
    ), umbrella="education_services"),
    C("professional_development", "Professional development & training", "education",
      OfferType.SERVICES, (
        r"\btraining\b", r"\bprofessional\s+development\b", r"\bcertification\s+course\b",
        r"\bseminar\b", r"\bworkshop\b", r"\be[- ]?learning\b",
    ), umbrella="education_services"),
    C("tutoring_instruction", "Tutoring & instruction", "education", OfferType.SERVICES, (
        r"\btutor", r"\binstructional\s+service", r"\bsupplemental\s+instruction\b",
        r"\bafter[- ]school\s+program\b", r"\bsummer\s+program\b",
    ), umbrella="education_services"),
    C("instructional_materials", "Instructional materials & curriculum", "education",
      OfferType.GOODS, (
        r"\btextbook\b", r"\bcurriculum\b", r"\binstructional\s+material",
        r"\beducational\s+(?:software|supplies)",
    ), umbrella="education_services"),
    C("library_services", "Library services & materials", "education", OfferType.MIXED, (
        r"\blibrary\b", r"\bbook\s+(?:purchase|supply)", r"\bperiodical\b",
        r"\bdatabase\s+subscription\b", r"\barchival\b",
    ), umbrella="education_services"),
    C("childcare_early_learning", "Childcare & early learning", "education", OfferType.SERVICES, (
        r"\bchild\s?care\b", r"\bearly\s+(?:learning|childhood)", r"\bpre[- ]?k\b",
        r"\bVPK\b",
    ), umbrella="education_services"),
    C("testing_assessment", "Testing & assessment", "education", OfferType.SERVICES, (
        r"\bassessment\s+(?:service|tool)", r"\bstandardized\s+test", r"\bproctor",
        r"\bexam\s+administration\b",
    ), umbrella="education_services"),

    # -- Goods, Equipment & Supplies -------------------------------------------
    C("goods_supplies", "General goods & supplies", "goods", OfferType.GOODS, (
        r"\bpurchase\s+and\s+deliver", r"\bfurnish\s+and\s+deliver", r"\bsupplies?\b",
        r"\bequipment\b", r"\bmaterials\s+(?:purchase|supply)",
    )),
    C("office_supplies", "Office supplies", "goods", OfferType.GOODS, (
        r"\boffice\s+supplies\b", r"\bpaper\s+(?:supply|product)", r"\btoner\b",
        r"\bstationery\b",
    ), umbrella="goods_supplies"),
    C("furniture_fixtures", "Furniture & fixtures", "goods", OfferType.GOODS, (
        r"\bfurniture\b", r"\bfurnishing\b", r"\bmodular\s+workstation\b",
        r"\bshelving\b", r"\blocker\b", r"\bcasework\b",
    ), umbrella="goods_supplies"),
    C("janitorial_supplies", "Janitorial supplies", "goods", OfferType.GOODS, (
        r"\bjanitorial\s+supplies\b", r"\bcleaning\s+(?:supplies|product)",
        r"\bpaper\s+towel\b", r"\btrash\s+(?:bag|liner)\b",
    ), umbrella="goods_supplies"),
    C("uniforms_apparel", "Uniforms & apparel", "goods", OfferType.GOODS, (
        r"\buniform\b", r"\bapparel\b", r"\bshoes?\b", r"\bboots?\b", r"\bt[- ]?shirt\b",
    ), umbrella="goods_supplies"),
    C("construction_materials", "Construction materials", "goods", OfferType.GOODS, (
        r"\baggregate\b", r"\blimerock\b", r"\bready[- ]mix\b", r"\bhot\s+mix\b",
        r"\blumber\b", r"\bready\s+mix\s+concrete\b", r"\bprecast\b",
    ), umbrella="goods_supplies"),
    C("pipe_fittings", "Pipe, valves & fittings", "goods", OfferType.GOODS, (
        r"\bpipe\s+(?:and\s+)?fitting", r"\bvalve\b", r"\bhydrant\b", r"\bductile\s+iron\b",
    ), umbrella="goods_supplies"),
    C("electrical_supplies", "Electrical & lighting supplies", "goods", OfferType.GOODS, (
        r"\belectrical\s+supplies\b", r"\blighting\s+(?:supply|fixture)", r"\bLED\s+(?:lamp|bulb)",
        r"\bwire\s+and\s+cable\b",
    ), umbrella="goods_supplies"),
    C("industrial_supplies", "Industrial & MRO supplies", "goods", OfferType.GOODS, (
        r"\bMRO\b", r"\bindustrial\s+supplies\b", r"\bhardware\s+supplies\b",
        r"\btool\s+(?:purchase|supply)", r"\bfastener\b",
    ), umbrella="goods_supplies"),
    C("tires_auto_parts", "Tires & auto parts", "goods", OfferType.GOODS, (
        r"\btires?\b", r"\bauto(?:motive)?\s+part", r"\bbattery\s+(?:purchase|supply)",
        r"\bOEM\s+part",
    ), umbrella="goods_supplies"),
    C("athletic_equipment", "Athletic & recreation equipment", "goods", OfferType.GOODS, (
        r"\bathletic\s+equipment\b", r"\bplayground\s+equipment\b", r"\bfitness\s+equipment\b",
        r"\bsports\s+(?:equipment|supply)", r"\bbleacher\b",
    ), umbrella="goods_supplies"),
    C("kitchen_equipment", "Kitchen & food service equipment", "goods", OfferType.GOODS, (
        r"\bkitchen\s+equipment\b", r"\bfood\s+service\s+equipment\b", r"\bwalk[- ]in\s+cooler\b",
        r"\brefrigerat(?:or|ion)\s+(?:unit|equipment)",
    ), umbrella="goods_supplies"),
    C("signage_graphics", "Signage & graphics", "goods", OfferType.GOODS, (
        r"\bsign(?:age|s)\b", r"\bwayfinding\b", r"\bbanner\b", r"\bdecal\b",
        r"\bvehicle\s+wrap\b",
    ), umbrella="goods_supplies"),
    C("printing_publications", "Printing & publications", "goods", OfferType.GOODS, (
        r"\bprinting\b", r"\bpublication\b", r"\bbrochure\b", r"\bmailing\s+service\b",
        r"\benvelope\b",
    ), umbrella="goods_supplies"),
    C("lab_supplies", "Laboratory supplies", "goods", OfferType.GOODS, (
        r"\blaboratory\s+(?:supplies|equipment)", r"\breagent\b", r"\bglassware\b",
    ), umbrella="goods_supplies"),
    C("agricultural_supplies", "Agricultural & landscape supplies", "goods", OfferType.GOODS, (
        r"\bfertilizer\b", r"\bherbicide\b", r"\bpesticide\s+(?:purchase|supply)",
        r"\bmulch\b", r"\bplant\s+material\b", r"\bseed\b",
    ), umbrella="goods_supplies"),

    # -- Real Estate & Property ------------------------------------------------
    C("real_estate_services", "Real estate services", "property", OfferType.PROFESSIONAL_SERVICES, (
        r"\breal\s+estate\b", r"\bbroker(?:age)?\s+service", r"\bland\s+acquisition\b",
        r"\bright[- ]of[- ]way\s+acquisition\b",
    )),
    C("property_management", "Property management", "property", OfferType.SERVICES, (
        r"\bproperty\s+management\b", r"\basset\s+management\s+service",
        r"\bHOA\s+management\b",
    ), umbrella="real_estate_services"),
    C("appraisal_services", "Appraisal & valuation", "property", OfferType.PROFESSIONAL_SERVICES, (
        r"\bappraisal\b", r"\bappraiser\b", r"\bvaluation\s+service", r"\bmass\s+appraisal\b",
    ), umbrella="real_estate_services"),
    C("title_services", "Title & closing services", "property", OfferType.PROFESSIONAL_SERVICES, (
        r"\btitle\s+(?:service|search|insurance)", r"\bclosing\s+service", r"\bescrow\b",
    ), umbrella="real_estate_services"),
    C("space_leasing", "Space leasing & rental", "property", OfferType.MIXED, (
        r"\blease\s+of\s+space\b", r"\boffice\s+space\b", r"\bfacility\s+rental\b",
        r"\bwarehouse\s+space\b",
    ), umbrella="real_estate_services"),
    C("housing_development", "Affordable housing development", "property", OfferType.MIXED, (
        r"\baffordable\s+housing\b", r"\bworkforce\s+housing\b", r"\bSHIP\b",
        r"\bhousing\s+rehabilitation\b", r"\binfill\s+housing\b",
    ), umbrella="real_estate_services"),

    # -- Financial & Insurance -------------------------------------------------
    # The head is deliberately `financial_services`, not `banking_services`:
    # employee benefits and insurance are not a kind of banking, and an umbrella
    # only earns its keep when the roll-up is true.
    C("financial_services", "Financial services", "financial", OfferType.PROFESSIONAL_SERVICES, (
        r"\bfinancial\s+service", r"\bfiscal\s+agent\b",
    )),
    C("banking_services", "Banking & treasury", "financial", OfferType.PROFESSIONAL_SERVICES, (
        r"\bbanking\s+service", r"\btreasury\s+(?:service|management)",
        r"\bmerchant\s+service", r"\bcredit\s+card\s+process", r"\blockbox\b",
        r"\bdepository\b",
    ), umbrella="financial_services"),
    C("investment_management", "Investment management", "financial",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\binvestment\s+(?:management|advisor|service)", r"\bportfolio\s+management\b",
        r"\bpension\s+(?:fund|investment)", r"\bcustodial\s+bank\b",
    ), umbrella="financial_services"),
    C("insurance_brokerage", "Insurance & brokerage", "financial",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\binsurance\b", r"\bbroker\s+of\s+record\b", r"\bproperty\s+and\s+casualty\b",
        r"\bliability\s+coverage\b", r"\bexcess\s+coverage\b",
    ), umbrella="financial_services"),
    C("risk_management", "Risk management & claims", "financial",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\brisk\s+management\b", r"\bclaims\s+(?:administ|adjust|process)",
        r"\bthird[- ]party\s+administrator\b", r"\bTPA\b", r"\bworkers'?\s+compensation\b",
    ), umbrella="financial_services"),
    C("employee_benefits", "Employee benefits", "financial", OfferType.PROFESSIONAL_SERVICES, (
        r"\bemployee\s+benefit", r"\bhealth\s+(?:insurance|plan)\b", r"\bdeferred\s+compensation\b",
        r"\bwellness\s+program\b", r"\bCOBRA\b",
    ), umbrella="financial_services"),
    C("debt_collection", "Collections & revenue recovery", "financial", OfferType.SERVICES, (
        r"\bcollection\s+(?:agency|service)", r"\bdebt\s+collect", r"\brevenue\s+recovery\b",
        r"\bdelinquent\s+account",
    ), umbrella="financial_services"),
    C("bond_underwriting", "Bond underwriting & issuance", "financial",
      OfferType.PROFESSIONAL_SERVICES, (
        r"\bunderwrit", r"\bbond\s+(?:issuance|counsel|rating)", r"\bdisclosure\s+counsel\b",
    ), umbrella="financial_services"),
    C("armored_transport", "Armored car & cash handling", "financial", OfferType.SERVICES, (
        r"\barmored\s+(?:car|transport)", r"\bcash\s+(?:handling|collection)\s+service",
    ), umbrella="financial_services"),

    # -- Media, Marketing & Events ---------------------------------------------
    C("marketing_advertising", "Marketing & advertising", "media", OfferType.SERVICES, (
        r"\bmarketing\b", r"\badvertising\b", r"\bmedia\s+buy", r"\bbranding\b",
        r"\bcampaign\s+(?:develop|manage)",
    )),
    C("public_relations", "Public relations & communications", "media", OfferType.SERVICES, (
        r"\bpublic\s+(?:relations|information|outreach)", r"\bcommunications\s+service",
        r"\bcommunity\s+engagement\b", r"\bcrisis\s+communication\b",
    ), umbrella="marketing_advertising"),
    C("graphic_design", "Graphic design & creative", "media", OfferType.SERVICES, (
        r"\bgraphic\s+design\b", r"\bcreative\s+service", r"\billustration\b",
        r"\blayout\s+and\s+design\b",
    ), umbrella="marketing_advertising"),
    C("video_photography", "Video & photography", "media", OfferType.SERVICES, (
        r"\bvideo\s+(?:production|service)", r"\bphotograph", r"\bvideograph",
        r"\bdrone\s+(?:service|footage)", r"\blivestream",
    ), umbrella="marketing_advertising"),
    C("event_management", "Event management", "media", OfferType.SERVICES, (
        r"\bevent\s+(?:management|planning|production|service)", r"\bfestival\b",
        r"\bconference\s+(?:service|planning)", r"\btrade\s+show\b",
    ), umbrella="marketing_advertising"),
    C("market_research", "Market research & surveys", "media", OfferType.SERVICES, (
        r"\bmarket\s+research\b", r"\bpublic\s+opinion\b", r"\bsurvey\s+research\b",
        r"\bfocus\s+group\b", r"\bcustomer\s+satisfaction\s+survey\b",
    ), umbrella="marketing_advertising"),

    # -- Food & Agriculture ----------------------------------------------------
    C("food_services", "Food service & catering", "food", OfferType.SERVICES, (
        r"\bcatering\b", r"\bfood\s+service\b", r"\bcafeteria\b", r"\bmeal\s+(?:service|prepar)",
        r"\bconcession\s+(?:stand|operation)",
    )),
    C("food_supply", "Food & beverage supply", "food", OfferType.GOODS, (
        r"\bfood\s+(?:supply|product|purchase)", r"\bbeverage\b", r"\bproduce\b",
        r"\bdairy\b", r"\bbottled\s+water\b", r"\bbread\b",
    ), umbrella="food_services"),
    C("vending_services", "Vending services", "food", OfferType.SERVICES, (
        r"\bvending\b", r"\bcoffee\s+service\b", r"\bsnack\s+service\b",
    ), umbrella="food_services"),
    C("agriculture_services", "Agriculture & farm services", "food", OfferType.SERVICES, (
        r"\bagricultur", r"\bfarm(?:ing)?\s+(?:service|operation)", r"\bcrop\b",
        r"\bnursery\s+(?:service|stock)", r"\blivestock\b",
    )),

    # -- Parks, Recreation & Culture -------------------------------------------
    C("parks_recreation", "Parks & recreation", "parks", OfferType.MIXED, (
        r"\bpark\s+(?:improve|maintenance|service|develop)", r"\brecreation\b",
        r"\bplayground\b", r"\btrail\b", r"\bsports\s+field\b", r"\bathletic\s+field\b",
    )),
    C("aquatics_programs", "Aquatics & pool programs", "parks", OfferType.SERVICES, (
        r"\baquatic", r"\bswim\s+(?:lesson|program)", r"\blifeguard\b",
    ), umbrella="parks_recreation"),
    C("athletic_programs", "Athletic & sports programs", "parks", OfferType.SERVICES, (
        r"\bathletic\s+program\b", r"\bsports\s+(?:league|program|camp)",
        r"\byouth\s+sports\b", r"\bofficiating\b",
    ), umbrella="parks_recreation"),
    C("cultural_arts", "Cultural arts & museums", "parks", OfferType.SERVICES, (
        r"\bcultural\s+(?:art|program|service)", r"\bmuseum\b", r"\bpublic\s+art\b",
        r"\bperforming\s+arts\b", r"\bexhibit\b", r"\bhistoric\s+preservation\b",
    ), umbrella="parks_recreation"),
    C("golf_operations", "Golf course operations", "parks", OfferType.MIXED, (
        r"\bgolf\b", r"\bdriving\s+range\b", r"\bpro\s+shop\b",
    ), umbrella="parks_recreation"),
    C("marina_operations", "Marina operations", "parks", OfferType.MIXED, (
        r"\bmarina\s+(?:operation|management|service)", r"\bboat\s+slip\b", r"\bmooring\b",
    ), umbrella="parks_recreation"),

    # -- Concessions, Leases & Revenue -----------------------------------------
    C("concession_agreements", "Concession agreements", "revenue", OfferType.MIXED, (
        r"\bconcession(?:aire)?\s+(?:agreement|opportunity)", r"\brevenue[- ]generating\b",
        r"\bconcession\s+contract\b",
    )),
    C("advertising_rights", "Advertising & naming rights", "revenue", OfferType.MIXED, (
        r"\bnaming\s+rights\b", r"\badvertising\s+rights\b", r"\bsponsorship\b",
        r"\bbus\s+shelter\s+advertis",
    ), umbrella="concession_agreements"),
    C("surplus_disposal", "Surplus property & auction", "revenue", OfferType.MIXED, (
        r"\bsurplus\b", r"\bauction\b", r"\bdisposal\s+of\s+(?:property|asset)",
        r"\bsale\s+of\s+(?:surplus|equipment)",
    ), umbrella="concession_agreements"),
    C("franchise_agreements", "Franchise & utility agreements", "revenue", OfferType.MIXED, (
        r"\bfranchise\s+(?:agreement|fee)", r"\butility\s+franchise\b",
    ), umbrella="concession_agreements"),

    # -- Cross-cutting ---------------------------------------------------------
    C("grant_opportunities", "Grant opportunities", "professional", OfferType.MIXED, (
        r"\bgrant\s+(?:opportunit|application|award|funding|program)\b",
        r"\bnotice\s+of\s+funding\b", r"\bNOFO\b", r"\bRFA\b",
    )),
    C("general", "Uncategorized", "professional", OfferType.UNKNOWN, ()),
]

CATEGORIES: Tuple[Category, ...] = tuple(_CATS)

BY_SLUG: Dict[str, Category] = {c.slug: c for c in CATEGORIES}
GROUP_BY_SLUG: Dict[str, Group] = {g.slug: g for g in GROUPS}

#: Slugs that may appear on an opportunity or in a saved watchlist rule.
ALL_SLUGS: Tuple[str, ...] = tuple(c.slug for c in CATEGORIES)


def categories_in_group(group: str) -> List[Category]:
    return [c for c in CATEGORIES if c.group == group]


def label_for(slug: str) -> str:
    """Human label for a slug, degrading gracefully for anything unrecognised."""
    cat = BY_SLUG.get(slug)
    if cat:
        return cat.label
    return slug.replace("_", " ").replace("-", " ").capitalize()


def offer_for(slug: str) -> OfferType:
    cat = BY_SLUG.get(slug)
    return cat.offer if cat else OfferType.UNKNOWN


def expand(slugs) -> List[str]:
    """Add each slug's umbrella, so a narrow tag also satisfies broad filters.

    ``["roofing"]`` becomes ``["roofing", "construction"]`` — which is what lets
    a watchlist saved against the old twelve-category world keep matching bids
    tagged with the finer vocabulary.
    """
    out: List[str] = []
    for slug in slugs or []:
        if slug not in out:
            out.append(slug)
        umbrella = (BY_SLUG.get(slug) or Category("", "", "", OfferType.UNKNOWN)).umbrella
        if umbrella and umbrella not in out:
            out.append(umbrella)
    return out


def as_dicts() -> List[dict]:
    """Serialisable form for the API / frontend dropdown."""
    return [
        {
            "slug": c.slug,
            "label": c.label,
            "group": c.group,
            "offer_type": c.offer.value if hasattr(c.offer, "value") else str(c.offer),
            "detectable": bool(c.patterns),
        }
        for c in CATEGORIES
        if c.slug != "general"
    ]


def groups_as_dicts() -> List[dict]:
    return [{"slug": g.slug, "label": g.label, "blurb": g.blurb} for g in GROUPS]
