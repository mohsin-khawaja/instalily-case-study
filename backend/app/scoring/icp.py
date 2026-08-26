"""The DuPont Tedlar Graphics & Signage ICP, as data.

Everything a human would argue about lives here -- vocabularies, weights, bands.
`score.py` is pure mechanism. Retargeting this pipeline at a different Tedlar
business unit (or a different client entirely) means editing this file only.
"""

from __future__ import annotations

# --- Component ceilings (sum = 100) -------------------------------------
MAX_INDUSTRY_FIT = 30.0
MAX_PRODUCT_FIT = 25.0
MAX_SIZE = 15.0
MAX_EVENT_ENGAGEMENT = 15.0
MAX_PAIN_ALIGNMENT = 15.0

# --- Tiering thresholds --------------------------------------------------
TIER_A_MIN = 75.0
TIER_B_MIN = 60.0
TIER_C_MIN = 40.0

# --- Industry vocabulary -------------------------------------------------
# tier1: core Tedlar buyer. tier2: adjacent, plausible. negative: wrong business.
INDUSTRY_TIER1 = [
    "signage",
    "sign manufacturing",
    "graphic films",
    "vehicle wrap",
    "vehicle graphics",
    "fleet graphics",
    "architectural graphics",
    "large format printing",
    "wide format printing",
    "protective film",
    "overlaminate",
    "self-adhesive vinyl",
    "pressure sensitive vinyl",
    "specialty films",
]
INDUSTRY_TIER2 = [
    "commercial printing",
    "outdoor advertising",
    "out-of-home",
    "billboard",
    "digital printing",
    "print media",
    "banner",
    "display graphics",
    "transit advertising",
    "awning",
    "coatings",
    "laminating",
]
INDUSTRY_NEGATIVE = [
    "staffing",
    "recruiting",
    "consulting services",
    "insurance",
    "software only",
    "travel agency",
]

# --- Tedlar application fit ---------------------------------------------
APPLICATION_KEYWORDS = [
    "outdoor signage",
    "exterior signage",
    "vehicle wrap",
    "fleet graphic",
    "transit graphic",
    "architectural graphic",
    "billboard",
    "wall graphic",
    "floor graphic",
    "large-format graphic",
    "overlaminate",
    "protective laminate",
    "window graphic",
    "digitally printed graphic",
]

# --- Tedlar pain points / value propositions -----------------------------
# Presence of these phrases in a company's own copy means they already sell on
# durability -- i.e. they are pre-sold on the problem Tedlar solves.
PAIN_KEYWORDS = {
    "uv resistance": ["uv resistant", "uv resistance", "uv stable", "uv protection", "fade resist"],
    "weatherability": [
        "weather resistant",
        "weatherable",
        "weatherability",
        "outdoor durability",
        "all-weather",
    ],
    "graffiti resistance": ["graffiti resistant", "anti-graffiti", "graffiti protection"],
    "chemical resistance": ["chemical resistant", "solvent resistant", "stain resistant"],
    "cleanability": ["easy to clean", "cleanability", "washable", "easy clean"],
    "lifespan": [
        "year warranty",
        "year durability",
        "extended life",
        "long-lasting graphic",
        "service life",
    ],
}

TEDLAR_VALUE_PROPS = {
    "uv resistance": "Tedlar PVF films hold colour and gloss through years of direct UV exposure.",
    "weatherability": (
        "Tedlar's proven outdoor weatherability extends graphic life in harsh climates."
    ),
    "graffiti resistance": (
        "Tedlar's low-surface-energy face makes graffiti and overspray wipe off cleanly."
    ),
    "chemical resistance": "Tedlar resists solvents, cleaners and road chemicals without hazing.",
    "cleanability": "Tedlar surfaces clean up with mild detergent, no abrasives, no gloss loss.",
    "lifespan": "Tedlar overlaminates let printers underwrite longer graphic warranties.",
}
DEFAULT_VALUE_PROP = TEDLAR_VALUE_PROPS["weatherability"]

# --- Size bands ----------------------------------------------------------
# (inclusive lower bound USD, label, points)
REVENUE_BANDS: list[tuple[float, str, float]] = [
    (1_000_000_000, "$1B+", 15.0),
    (250_000_000, "$250M-$1B", 12.0),
    (50_000_000, "$50M-$250M", 8.0),
    (0, "<$50M", 4.0),
]
# (inclusive lower bound headcount, label, points)
EMPLOYEE_BANDS: list[tuple[int, str, float]] = [
    (5000, "5000+", 15.0),
    (1000, "1000-4999", 12.0),
    (250, "250-999", 9.0),
    (50, "50-249", 6.0),
    (0, "1-49", 3.0),
]

# --- Event engagement ----------------------------------------------------
TIER1_EVENT_POINTS = 8.0
ADDITIONAL_EVENT_POINTS = 4.0
ASSOCIATION_POINTS = 3.0

# --- Reference accounts (lookalike seed) ---------------------------------
# Accounts known to be a strong fit, used as the anchor for lookalike matching.
# The brief itself names Avery Dennison Graphics Solutions as the archetype, so
# it seeds the set. In a real deployment this list is replaced by closed-won
# accounts pulled from the CRM — the mechanism is identical either way.
REFERENCE_ACCOUNT_DOMAINS = [
    "averydennison.com",
    "orafol.com",
    "drytac.com",
    "mactac.com",
]

# --- Decision-maker targeting -------------------------------------------
TARGET_TITLES = [
    "VP Product",
    "VP Product Development",
    "VP Innovation",
    "VP Research and Development",
    "Director of R&D",
    "Director of Product Development",
    "Director of Innovation",
    "Head of Materials",
    "Head of Coatings",
    "Product Manager Films",
    "Director of Business Development",
    "Director of Strategic Partnerships",
]
# Function fit. Seniority alone ranks a Finance Director above a Product Manager,
# but Tedlar is sold into product, R&D and materials decisions -- so the function
# a person owns matters as much as how senior they are.
FUNCTION_BONUS = {
    "product": 0.45,
    "research": 0.45,
    "r&d": 0.45,
    "innovation": 0.45,
    "development": 0.35,
    "technical": 0.30,
    "materials": 0.30,
    "engineering": 0.30,
    "operations": 0.15,
    "partnership": 0.15,
    "business development": 0.15,
}
FUNCTION_PENALTY = {
    "finance": -0.35,
    "accounting": -0.35,
    "human resources": -0.40,
    "recruit": -0.40,
    "legal": -0.35,
    "compliance": -0.35,
    "conflicts of interest": -0.50,
    "customer service": -0.25,
    "creative": -0.15,
    "social media": -0.30,
}

SENIORITY_PATTERNS = {
    "c_level": ["chief", "cto", "ceo", "coo", "cmo", "president"],
    "vp": ["vp", "vice president", "svp", "evp"],
    "director": ["director", "head of"],
    "manager": ["manager", "lead"],
}
