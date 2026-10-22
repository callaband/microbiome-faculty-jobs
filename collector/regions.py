"""Country / region lookups (no external dependency)."""

from __future__ import annotations

import re
import unicodedata

_RAW = {
    "North America": "US:United States|CA:Canada|MX:Mexico|GT:Guatemala|BZ:Belize|HN:Honduras|SV:El Salvador|NI:Nicaragua|CR:Costa Rica|PA:Panama|CU:Cuba|JM:Jamaica|HT:Haiti|DO:Dominican Republic|PR:Puerto Rico|BS:Bahamas|BB:Barbados|TT:Trinidad and Tobago|GL:Greenland|BM:Bermuda",
    "South America": "BR:Brazil|AR:Argentina|CL:Chile|CO:Colombia|PE:Peru|VE:Venezuela|EC:Ecuador|BO:Bolivia|PY:Paraguay|UY:Uruguay|GY:Guyana|SR:Suriname",
    "Europe": "GB:United Kingdom|IE:Ireland|FR:France|DE:Germany|NL:Netherlands|BE:Belgium|LU:Luxembourg|CH:Switzerland|AT:Austria|IT:Italy|ES:Spain|PT:Portugal|DK:Denmark|SE:Sweden|NO:Norway|FI:Finland|IS:Iceland|PL:Poland|CZ:Czech Republic|SK:Slovakia|HU:Hungary|SI:Slovenia|HR:Croatia|RS:Serbia|BA:Bosnia and Herzegovina|ME:Montenegro|MK:North Macedonia|AL:Albania|GR:Greece|BG:Bulgaria|RO:Romania|MD:Moldova|UA:Ukraine|BY:Belarus|LT:Lithuania|LV:Latvia|EE:Estonia|MT:Malta|CY:Cyprus|MC:Monaco|LI:Liechtenstein|AD:Andorra|SM:San Marino|RU:Russia|TR:Turkey",
    "Asia": "CN:China|HK:Hong Kong|MO:Macau|TW:Taiwan|JP:Japan|KR:South Korea|KP:North Korea|MN:Mongolia|IN:India|PK:Pakistan|BD:Bangladesh|LK:Sri Lanka|NP:Nepal|BT:Bhutan|MV:Maldives|AF:Afghanistan|SG:Singapore|MY:Malaysia|TH:Thailand|VN:Vietnam|KH:Cambodia|LA:Laos|MM:Myanmar|PH:Philippines|ID:Indonesia|BN:Brunei|TL:Timor-Leste|KZ:Kazakhstan|UZ:Uzbekistan|KG:Kyrgyzstan|TJ:Tajikistan|TM:Turkmenistan|GE:Georgia|AM:Armenia|AZ:Azerbaijan",
    "Middle East": "SA:Saudi Arabia|AE:United Arab Emirates|QA:Qatar|KW:Kuwait|BH:Bahrain|OM:Oman|YE:Yemen|IL:Israel|PS:Palestine|JO:Jordan|LB:Lebanon|SY:Syria|IQ:Iraq|IR:Iran",
    "Africa": "EG:Egypt|MA:Morocco|DZ:Algeria|TN:Tunisia|LY:Libya|SD:Sudan|ET:Ethiopia|KE:Kenya|UG:Uganda|TZ:Tanzania|RW:Rwanda|BI:Burundi|SO:Somalia|NG:Nigeria|GH:Ghana|SN:Senegal|CI:Ivory Coast|CM:Cameroon|BF:Burkina Faso|ML:Mali|NE:Niger|TD:Chad|BJ:Benin|TG:Togo|SL:Sierra Leone|LR:Liberia|GN:Guinea|GM:Gambia|CD:DR Congo|CG:Republic of the Congo|GA:Gabon|AO:Angola|ZM:Zambia|ZW:Zimbabwe|MW:Malawi|MZ:Mozambique|BW:Botswana|NA:Namibia|ZA:South Africa|LS:Lesotho|SZ:Eswatini|MG:Madagascar|MU:Mauritius|SC:Seychelles",
    "Oceania": "AU:Australia|NZ:New Zealand|FJ:Fiji|PG:Papua New Guinea|WS:Samoa|TO:Tonga|NC:New Caledonia|PF:French Polynesia|GU:Guam",
}

COUNTRIES: dict[str, tuple[str, str]] = {}  # code -> (name, region)
for _region, _blob in _RAW.items():
    for _pair in _blob.split("|"):
        _code, _name = _pair.split(":", 1)
        COUNTRIES[_code] = (_name, _region)

_ALIASES = {
    "usa": "US", "u.s.": "US", "u.s.a.": "US", "united states of america": "US", "america": "US",
    "uk": "GB", "u.k.": "GB", "great britain": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "britain": "GB",
    "korea": "KR", "republic of korea": "KR", "korea, republic of": "KR",
    "czechia": "CZ", "the netherlands": "NL", "holland": "NL",
    "russian federation": "RU", "turkiye": "TR", "türkiye": "TR",
    "viet nam": "VN", "uae": "AE", "prc": "CN", "people's republic of china": "CN",
    "hong kong sar": "HK", "hong kong sar, china": "HK", "cote d'ivoire": "CI", "côte d'ivoire": "CI",
    "kingdom of saudi arabia": "SA", "ksa": "SA", "macao": "MO",
}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico", "GU": "Guam",
    "VI": "U.S. Virgin Islands",
}
CA_PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories", "NU": "Nunavut",
    "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec", "SK": "Saskatchewan", "YT": "Yukon",
}
_STATE_NAMES = {v.lower(): k for k, v in US_STATES.items()}
_PROV_NAMES = {v.lower(): k for k, v in CA_PROVINCES.items()} | {"québec": "QC"}

_NAME_TO_CODE = {name.lower(): code for code, (name, _) in COUNTRIES.items()} | _ALIASES


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip().strip(".").lower()


def country_code(s: str | None) -> str | None:
    """'US', 'United States', 'Germany', 'Québec' ... -> ISO code (or None)."""
    if not s:
        return None
    raw = s.strip()
    if len(raw) == 2 and raw.upper() in COUNTRIES:
        return raw.upper()
    f = _fold(raw)
    if f in _NAME_TO_CODE:
        return _NAME_TO_CODE[f]
    if f in _STATE_NAMES:
        return "US"
    if f in _PROV_NAMES:
        return "CA"
    return None


def country_name(code: str | None) -> str:
    return COUNTRIES.get(code or "", ("", ""))[0]


def region_of(code: str | None) -> str:
    return COUNTRIES.get(code or "", ("", "Other"))[1]


def parse_place(s: str) -> dict:
    """Parse free-text locations like 'Wilmington, NC', 'Doha, Qatar', 'Luxembourg (LU)',
    'Salt Lake City, Utah', 'Montréal, Quebec, Canada'."""
    s = re.sub(r"\s+", " ", s or "").strip(" ,")
    m = re.match(r"^(.*?)\s*\(([A-Z]{2})\)$", s)  # "Luxembourg (LU)"
    if m and m.group(2) in COUNTRIES:
        return {"city": m.group(1) if _fold(m.group(1)) != _fold(country_name(m.group(2))) else "",
                "region": "", "country_code": m.group(2)}
    parts = [p.strip() for p in s.split(",") if p.strip()]
    out = {"city": "", "region": "", "country_code": None}
    if not parts:
        return out
    last = parts[-1]
    if len(last) == 2 and last.upper() in US_STATES and last.isupper():
        out.update(city=", ".join(parts[:-1]), region=US_STATES[last.upper()], country_code="US")
    elif len(last) == 2 and last.upper() in CA_PROVINCES and last.isupper():
        out.update(city=", ".join(parts[:-1]), region=CA_PROVINCES[last.upper()], country_code="CA")
    elif _fold(last) in _STATE_NAMES:
        out.update(city=", ".join(parts[:-1]), region=last, country_code="US")
    elif _fold(last) in _PROV_NAMES:
        out.update(city=", ".join(parts[:-1]), region=last, country_code="CA")
    elif country_code(last):
        cc = country_code(last)
        rest = parts[:-1]
        if rest and (_fold(rest[-1]) in _STATE_NAMES or _fold(rest[-1]) in _PROV_NAMES):
            out.update(region=rest[-1], city=", ".join(rest[:-1]), country_code=cc)
        else:
            out.update(city=", ".join(rest), country_code=cc)
    else:
        out.update(city=s)
    return out
