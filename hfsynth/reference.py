"""Static reference data. All business names are fictional (no real brands)."""

# --------------------------------------------------------------------------
# Category taxonomy: (code, name, parent_code, type, is_spending, is_budgetable)
# --------------------------------------------------------------------------
CATEGORIES = [
    ("ESS", "Essentials", None, "EXPENSE", 0, 0),
    ("LIF", "Lifestyle", None, "EXPENSE", 0, 0),
    ("INC", "Income", None, "INCOME", 0, 0),
    ("TFR", "Transfers", None, "TRANSFER", 0, 0),
    ("SYS", "System", None, "SYSTEM", 0, 0),
    ("HOU", "Housing", "ESS", "EXPENSE", 1, 1),
    ("UTL", "Utilities", "ESS", "EXPENSE", 1, 1),
    ("INS", "Insurance", "ESS", "EXPENSE", 1, 1),
    ("GRO", "Groceries", "ESS", "EXPENSE", 1, 1),
    ("TRN", "Transit & Rideshare", "ESS", "EXPENSE", 1, 1),
    ("FUE", "Fuel", "ESS", "EXPENSE", 1, 1),
    ("HLT", "Health & Pharmacy", "ESS", "EXPENSE", 1, 1),
    ("DIN", "Dining & Coffee", "LIF", "EXPENSE", 1, 1),
    ("SHP", "Shopping", "LIF", "EXPENSE", 1, 1),
    ("ENT", "Entertainment", "LIF", "EXPENSE", 1, 1),
    ("TRV", "Travel", "LIF", "EXPENSE", 1, 1),
    ("EDU", "Education", "LIF", "EXPENSE", 1, 1),
    ("HME", "Home & Garden", "LIF", "EXPENSE", 1, 1),
    ("PET", "Pets", "LIF", "EXPENSE", 1, 1),
    ("GFT", "Gifts & Donations", "LIF", "EXPENSE", 1, 1),
    ("SUB", "Subscriptions", "LIF", "EXPENSE", 1, 1),
    ("SAL", "Salary", "INC", "INCOME", 0, 0),
    ("XFR", "Internal Transfer", "TFR", "TRANSFER", 0, 0),
    # Uncategorised is conservatively treated as spending, which is exactly why
    # mis-routed rows (e.g. a transfer duplicate) inflate spend until reviewed.
    ("UNC", "Uncategorized", "SYS", "SYSTEM", 1, 0),
]
CAT_SPENDING = {c[0]: bool(c[4]) for c in CATEGORIES}

# Legacy budget codes that are NOT part of the taxonomy (edge case E5).
LEGACY_CODES = {
    "GRO": "GROC", "DIN": "DINING", "TRN": "TRANSPORT", "FUE": "GAS", "SHP": "MISC",
    "ENT": "FUN", "HLT": "MEDICAL", "UTL": "BILLS", "INS": "COVER", "SUB": "SUBS",
    "TRV": "TRAVEL", "EDU": "SCHOOL", "HME": "HOME", "PET": "PETS", "GFT": "GIVING",
}

# --------------------------------------------------------------------------
# Discretionary spending model: code -> (relative weight, median USD, lognormal sigma)
# --------------------------------------------------------------------------
CAT_MODEL = {
    "GRO": (0.220, 48.0, 0.55), "DIN": (0.170, 22.0, 0.60), "TRN": (0.060, 12.0, 0.50),
    "FUE": (0.070, 42.0, 0.35), "SHP": (0.140, 45.0, 0.80), "ENT": (0.050, 24.0, 0.60),
    "HLT": (0.040, 40.0, 0.80), "TRV": (0.012, 260.0, 0.80), "EDU": (0.010, 90.0, 0.80),
    "HME": (0.045, 55.0, 0.80), "PET": (0.025, 38.0, 0.60), "GFT": (0.025, 40.0, 0.70),
}
DISCRETIONARY = list(CAT_MODEL)


def _season(default, over):
    return [over.get(m, default) for m in range(1, 13)]


SEASON = {c: _season(1.0, {}) for c in DISCRETIONARY}
SEASON["SHP"] = _season(1.0, {11: 1.35, 12: 1.8})
SEASON["GFT"] = _season(1.0, {2: 1.4, 5: 1.3, 12: 2.5})
SEASON["TRV"] = _season(0.8, {6: 1.5, 7: 2.0, 8: 1.8, 12: 2.0})
SEASON["EDU"] = _season(0.7, {1: 2.0, 8: 2.5, 9: 2.0})
SEASON["HME"] = _season(1.0, {3: 1.2, 4: 1.5, 5: 1.5, 6: 1.5})
SEASON["ENT"] = _season(1.0, {6: 1.3, 7: 1.3, 8: 1.3, 12: 1.3})
SEASON["DIN"] = _season(1.0, {7: 1.2, 12: 1.3})
SEASON["GRO"] = _season(1.0, {11: 1.1, 12: 1.25})
SEASON["FUE"] = _season(1.0, {6: 1.2, 7: 1.2, 8: 1.2})
SEASON["HLT"] = _season(1.0, {1: 1.2, 10: 1.1})

MONTH_ACTIVITY = [0.95, 0.88, 1.0, 1.0, 1.02, 1.0, 1.04, 1.02, 0.98, 1.0, 1.08, 1.2]

HOUR_WEIGHTS = [0.2, 0.1, 0.05, 0.05, 0.05, 0.1, 0.3, 0.8, 1.2, 1.6, 2.0, 2.6,
                3.2, 2.6, 2.2, 2.0, 2.2, 2.8, 3.2, 2.8, 2.0, 1.2, 0.6, 0.3]
HOUR_CUM = []
_t = 0.0
for _w in HOUR_WEIGHTS:
    _t += _w
    HOUR_CUM.append(_t)

# persona -> (probability, spend factor, {category: weight multiplier})
PERSONAS = {
    "FRUGAL": (0.30, 0.80, {"DIN": 0.6, "ENT": 0.6, "SHP": 0.7, "TRV": 0.5}),
    "BALANCED": (0.50, 1.00, {}),
    "SPENDER": (0.20, 1.25, {"DIN": 1.5, "SHP": 1.4, "ENT": 1.5, "TRV": 1.8}),
}

AGE_BANDS = (("18-24", 0.10), ("25-34", 0.28), ("35-44", 0.26), ("45-54", 0.18), ("55-64", 0.12), ("65+", 0.06))

# (iana name, region code, standard UTC offset minutes, probability)
TIMEZONES = [
    ("America/New_York", "US-EAST", -300, 0.45),
    ("America/Chicago", "US-CENTRAL", -360, 0.25),
    ("America/Denver", "US-MOUNTAIN", -420, 0.08),
    ("America/Los_Angeles", "US-WEST", -480, 0.22),
]
CITIES = {
    "America/New_York": ["BOSTON MA", "MIAMI FL", "NEW YORK NY", "ATLANTA GA"],
    "America/Chicago": ["CHICAGO IL", "AUSTIN TX", "DALLAS TX"],
    "America/Denver": ["DENVER CO", "SALT LAKE UT"],
    "America/Los_Angeles": ["SEATTLE WA", "PORTLAND OR", "SAN DIEGO CA"],
}

PREFIXES = ["POS PURCHASE", "DEBIT CARD PURCHASE", "CARD PURCHASE", "SQ *", "TST*", "PAYPAL *", "", ""]

# --------------------------------------------------------------------------
# Merchant catalogue
# --------------------------------------------------------------------------
RETAIL = {
    "GRO": ["FreshMart Grocers", "GreenBasket Market", "Harvest Table Foods", "ValueFoods Supermarket",
            "Corner Pantry Market", "Sunrise Organic Grocers", "Bulk Barn Wholesale Foods", "Meadow Fresh Market"],
    "DIN": ["Taco Casa Restaurant", "Blue Fig Bistro", "Noodle Harbor Restaurant", "Brew & Bean Coffee",
            "Pizza Orbit Restaurant", "Spice Route Kitchen", "Burger Junction Grill", "Sakura Sushi Restaurant",
            "Daily Grind Coffee"],
    "TRN": ["MetroLink Transit", "RideNow Taxi", "CityBike Share", "Park-It Garage", "Express Rail Tickets",
            "TollWay Pass"],
    "FUE": ["Summit Fuel", "Pinnacle Gas Station", "RoadStar Fuel", "Eagle Petro"],
    "SHP": ["Urban Threads Apparel", "Gadget Garden Electronics", "Bookworm Books", "Sportify Outfitters",
            "Luma Home Decor", "ShoeBox Footwear"],
    "ENT": ["Starlight Cinemas", "Pixel Arcade", "Concert Hub Tickets", "Bowl-O-Rama", "Streamline Games Store"],
    "HLT": ["Greenleaf Pharmacy", "CareFirst Clinic", "BrightSmile Dental", "Vision Plus Optical",
            "Wellspring Physio"],
    "TRV": ["SkyHigh Airlines", "Stay Inn Hotels", "Wanderlust Travel Co", "RoadRunner Car Rental"],
    "EDU": ["Learnly Online Courses", "Campus Bookstore", "Bright Minds Tutoring"],
    "HME": ["Hammer & Nail Hardware", "Garden Gate Nursery", "Nest Furnishings", "FixIt Home Supply"],
    "PET": ["Paws & Claws Pet Supply", "Happy Tails Vet", "Whisker Warehouse"],
    "GFT": ["Giftbox Boutique", "Hope Foundation Donations", "Bloom Florists"],
}
TYPE_BY_CAT = {
    "GRO": "RETAILER", "DIN": "RESTAURANT", "TRN": "TRANSPORT", "FUE": "FUEL", "SHP": "RETAILER",
    "ENT": "ENTERTAINMENT", "HLT": "HEALTHCARE", "TRV": "TRAVEL", "EDU": "EDUCATION", "HME": "RETAILER",
    "PET": "RETAILER", "GFT": "RETAILER",
}
MCC = {
    "GRO": "5411", "DIN": "5812", "TRN": "4111", "FUE": "5541", "SHP": "5311", "ENT": "7832", "HLT": "5912",
    "TRV": "4511", "EDU": "8299", "HME": "5200", "PET": "5995", "GFT": "5947", "SUB": "4899", "UTL": "4900",
    "INS": "6300", "HOU": "6513", "SAL": None,
}
# Multi-category ("ambiguous") merchants: category -> share of that merchant's baskets.
AMBIGUOUS = [
    ("MegaMart Superstore", {"GRO": 0.50, "SHP": 0.25, "HME": 0.10, "HLT": 0.15}),
    ("OneStop Convenience", {"GRO": 0.40, "FUE": 0.35, "DIN": 0.25}),
    ("Skyline Online Marketplace", {"SHP": 0.60, "HME": 0.15, "GRO": 0.15, "ENT": 0.10}),
    ("QuickDash Delivery", {"DIN": 0.70, "GRO": 0.30}),
    ("PayLink Checkout", {"SHP": 0.50, "GFT": 0.20, "ENT": 0.30}),
    ("CampusPlaza Store", {"EDU": 0.35, "SHP": 0.45, "DIN": 0.20}),
]
SUBSCRIPTIONS = [  # (name, price menu USD, cadence)
    ("Streamflix Video", [8.99, 15.49], "MONTHLY"),
    ("TuneBox Music", [10.99], "MONTHLY"),
    ("CloudVault Storage", [2.99, 9.99], "MONTHLY"),
    ("FitPulse Gym", [29.99, 49.00], "MONTHLY"),
    ("Daily Chronicle News", [12.00], "MONTHLY"),
    ("GameLoop Pass", [14.99], "MONTHLY"),
    ("Readly Books Club", [9.99], "MONTHLY"),
    ("MindEase Meditation", [12.99], "MONTHLY"),
    ("PetPals Box", [34.00], "MONTHLY"),
    ("MealKit Weekly", [59.00], "MONTHLY"),
    ("PrimeCart Membership", [139.00], "ANNUAL"),
    ("SoftSuite Office", [99.99], "ANNUAL"),
]
UTILITIES = {  # kind -> providers, base monthly USD, variable amount?, ownership probability
    "ELECTRIC": dict(providers=["Metro Electric", "Voltline Power"], base=95.0, variable=True, prob=1.00),
    "GAS": dict(providers=["CityGas Energy", "BlueFlame Gas"], base=55.0, variable=True, prob=0.40),
    "WATER": dict(providers=["AquaFlow Water", "ClearStream Water"], base=52.0, variable=True, prob=0.70),
    "INTERNET": dict(providers=["FiberNet Internet", "SkyLink Broadband"], base=68.0, variable=False, prob=0.85),
    "MOBILE": dict(providers=["Zenith Mobile", "Nova Wireless"], base=62.0, variable=False, prob=0.90),
    "WASTE": dict(providers=["Waste Away Services", "GreenBin Disposal"], base=34.0, variable=False, prob=0.35),
}
UTIL_SEASON = {
    "ELECTRIC": [1.15, 1.05, 0.90, 0.85, 0.90, 1.15, 1.35, 1.40, 1.10, 0.90, 0.95, 1.15],
    "GAS": [1.40, 1.30, 1.10, 0.85, 0.70, 0.60, 0.55, 0.55, 0.65, 0.85, 1.15, 1.40],
    "WATER": [0.95, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.15, 1.05, 1.00, 0.95, 0.95],
}
INSURERS = ["Shieldwell Insurance", "SafeHarbor Auto Insurance", "LifeSure Health Plans"]
LANDLORDS = ["Greenfield Properties", "Oakridge Residential", "Harbor View Rentals", "Maple Court Apartments",
             "Cedar Point Living", "Riverstone Lofts", "Summit Ridge Homes", "Lakeside Residences",
             "Pinecrest Towers", "Bayfront Suites", "Hillcrest Manor", "Willow Creek Estates"]
_ADJ = ["Apex", "Northwind", "Bluebird", "Summit", "Crestview", "Ironwood", "Lumen", "Oakline", "Redwood",
        "Silverline"]
_NOUN = ["Logistics", "Analytics", "Health Group", "Foods Inc", "Systems", "Builders", "Media", "Energy"]
EMPLOYERS = [f"{a} {n}" for a in _ADJ for n in _NOUN][:40]

SERIES_HOURS = {  # (first hour inclusive, last hour exclusive), local time
    "SALARY": (6, 10), "RENT": (9, 17), "SUBSCRIPTION": (0, 6), "UTILITY": (8, 15),
    "INSURANCE": (8, 15), "SAVINGS_TRANSFER": (10, 12),
}
SERIES_DESC = {
    "SALARY": "ACH CREDIT PAYROLL {alias}",
    "RENT": "ACH DEBIT RENT {alias}",
    "SUBSCRIPTION": "RECURRING PMT {alias} {ref}",
    "UTILITY": "BILL PAY {alias} {ref}",
    "INSURANCE": "AUTOPAY {alias} {ref}",
}

# Descriptor keywords (token match) used by the rule engine for unresolved merchants.
# Order is significant: earlier entries win (e.g. TRANSIT words before generic TICKETS).
KEYWORDS = [
    ("GRO", ["GROCERS", "MARKET", "SUPERMARKET", "FOODS"]),
    ("DIN", ["RESTAURANT", "BISTRO", "KITCHEN", "GRILL", "COFFEE", "SUSHI", "PIZZA"]),
    ("HLT", ["PHARMACY", "CLINIC", "DENTAL", "OPTICAL", "PHYSIO"]),
    ("FUE", ["FUEL", "PETRO", "GAS", "STATION"]),
    ("TRN", ["TRANSIT", "TAXI", "RAIL", "GARAGE", "SHARE"]),
    ("TRV", ["AIRLINES", "HOTELS", "TRAVEL", "RENTAL"]),
    ("PET", ["PET", "VET", "WHISKER"]),
    ("ENT", ["CINEMAS", "ARCADE", "TICKETS", "BOWL", "GAMES"]),
    ("HME", ["HARDWARE", "NURSERY", "FURNISHINGS", "SUPPLY"]),
    ("EDU", ["COURSES", "BOOKSTORE", "TUTORING"]),
    ("GFT", ["BOUTIQUE", "DONATIONS", "FLORISTS", "FOUNDATION"]),
    ("SHP", ["APPAREL", "ELECTRONICS", "BOOKS", "OUTFITTERS", "DECOR", "FOOTWEAR"]),
]
