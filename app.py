import os
import re
import time
import uuid
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

app = Flask(__name__)

# Load environment variables from .env for local Neon database usage.
load_dotenv()

# Database config
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///profiles.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# UUID v7 
def uuid7() -> str:
    """Generate a UUID version 7 (time-ordered, millisecond precision)."""
    timestamp_ms = int(time.time() * 1000)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF
    high = (timestamp_ms << 16) | (0x7 << 12) | rand_a
    low = (0b10 << 62) | rand_b
    return str(uuid.UUID(int=(high << 64) | low))


# Model
class Profile(db.Model):
    __tablename__ = "profiles"

    id                  = db.Column(db.String(36),  primary_key=True)
    name                = db.Column(db.String(255), nullable=False, unique=True, index=True)
    gender              = db.Column(db.String(20))
    gender_probability  = db.Column(db.Float)
    sample_size         = db.Column(db.Integer)
    age                 = db.Column(db.Integer,     index=True)
    age_group           = db.Column(db.String(20),  index=True)
    country_id          = db.Column(db.String(2),   index=True)
    country_name        = db.Column(db.String(100))
    country_probability = db.Column(db.Float)
    created_at          = db.Column(db.String(30),  nullable=False)

    def to_dict(self, summary=False):
        if summary:
            return {
                "id":         self.id,
                "name":       self.name,
                "gender":     self.gender,
                "age":        self.age,
                "age_group":  self.age_group,
                "country_id": self.country_id,
            }
        return {
            "id":                  self.id,
            "name":                self.name,
            "gender":              self.gender,
            "gender_probability":  self.gender_probability,
            "sample_size":         self.sample_size,         
            "age":                 self.age,
            "age_group":           self.age_group,
            "country_id":          self.country_id,
            "country_probability": self.country_probability,
            "created_at":          self.created_at,
        }


# Helpers
def classify_age_group(age: int) -> str:
    if age <= 12:
        return "child"
    elif age <= 19:
        return "teenager"
    elif age <= 59:
        return "adult"
    return "senior"


def fetch_external(url: str, api_name: str):
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json(), None
    except requests.exceptions.Timeout:
        return None, ({"status": "502", "message": f"{api_name} returned an invalid response"}, 502)
    except requests.exceptions.RequestException:
        return None, ({"status": "502", "message": f"{api_name} returned an invalid response"}, 502)


# Country name -> ISO-2 lookup for natural language query parsing
COUNTRY_NAME_TO_ID = {
    "nigeria": "NG", "ghana": "GH", "kenya": "KE", "ethiopia": "ET",
    "egypt": "EG", "tanzania": "TZ", "uganda": "UG", "angola": "AO",
    "mozambique": "MZ", "madagascar": "MG", "cameroon": "CM", "ivory coast": "CI",
    "cote d'ivoire": "CI", "niger": "NE", "mali": "ML", "burkina faso": "BF",
    "malawi": "MW", "zambia": "ZM", "senegal": "SN", "zimbabwe": "ZW",
    "guinea": "GN", "rwanda": "RW", "benin": "BJ", "burundi": "BI",
    "somalia": "SO", "togo": "TG", "sierra leone": "SL", "libya": "LY",
    "liberia": "LR", "mauritania": "MR", "eritrea": "ER", "gambia": "GM",
    "botswana": "BW", "namibia": "NA", "gabon": "GA", "lesotho": "LS",
    "guinea-bissau": "GW", "equatorial guinea": "GQ", "mauritius": "MU",
    "eswatini": "SZ", "djibouti": "DJ", "comoros": "KM", "cape verde": "CV",
    "sao tome": "ST", "seychelles": "SC", "south africa": "ZA",
    "south sudan": "SS", "democratic republic of congo": "CD", "congo": "CG",
    "central african republic": "CF", "chad": "TD", "sudan": "SD",
    "morocco": "MA", "algeria": "DZ", "tunisia": "TN",
    "united states": "US", "usa": "US", "united kingdom": "GB", "uk": "GB",
    "france": "FR", "germany": "DE", "india": "IN", "china": "CN",
    "brazil": "BR", "canada": "CA", "australia": "AU", "japan": "JP",
    "mexico": "MX", "italy": "IT", "spain": "ES", "netherlands": "NL",
    "sweden": "SE", "norway": "NO", "denmark": "DK", "finland": "FI",
    "poland": "PL", "portugal": "PT", "russia": "RU", "turkey": "TR",
    "indonesia": "ID", "pakistan": "PK", "bangladesh": "BD",
    "philippines": "PH", "vietnam": "VN", "thailand": "TH",
    "argentina": "AR", "colombia": "CO", "peru": "PE", "venezuela": "VE",
    "chile": "CL", "ecuador": "EC",
}

# ISO-2 -> country name (used when creating / seeding profiles)
COUNTRY_ID_TO_NAME = {
    "NG": "Nigeria", "GH": "Ghana", "KE": "Kenya", "ET": "Ethiopia",
    "EG": "Egypt", "TZ": "Tanzania", "UG": "Uganda", "AO": "Angola",
    "MZ": "Mozambique", "MG": "Madagascar", "CM": "Cameroon", "CI": "Côte d'Ivoire",
    "NE": "Niger", "ML": "Mali", "BF": "Burkina Faso", "MW": "Malawi",
    "ZM": "Zambia", "SN": "Senegal", "ZW": "Zimbabwe", "GN": "Guinea",
    "RW": "Rwanda", "BJ": "Benin", "BI": "Burundi", "SO": "Somalia",
    "TG": "Togo", "SL": "Sierra Leone", "LY": "Libya", "LR": "Liberia",
    "MR": "Mauritania", "ER": "Eritrea", "GM": "Gambia", "BW": "Botswana",
    "NA": "Namibia", "GA": "Gabon", "LS": "Lesotho", "GW": "Guinea-Bissau",
    "GQ": "Equatorial Guinea", "MU": "Mauritius", "SZ": "Eswatini",
    "DJ": "Djibouti", "KM": "Comoros", "CV": "Cape Verde", "ST": "São Tomé",
    "SC": "Seychelles", "ZA": "South Africa", "SS": "South Sudan",
    "CD": "DR Congo", "CG": "Congo", "CF": "Central African Republic",
    "TD": "Chad", "SD": "Sudan", "MA": "Morocco", "DZ": "Algeria",
    "TN": "Tunisia", "US": "United States", "GB": "United Kingdom",
    "FR": "France", "DE": "Germany", "IN": "India", "CN": "China",
    "BR": "Brazil", "CA": "Canada", "AU": "Australia", "JP": "Japan",
    "MX": "Mexico", "IT": "Italy", "ES": "Spain", "NL": "Netherlands",
    "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
    "PL": "Poland", "PT": "Portugal", "RU": "Russia", "TR": "Turkey",
    "ID": "Indonesia", "PK": "Pakistan", "BD": "Bangladesh",
    "PH": "Philippines", "VN": "Vietnam", "TH": "Thailand",
    "AR": "Argentina", "CO": "Colombia", "PE": "Peru",
    "VE": "Venezuela", "CL": "Chile", "EC": "Ecuador",
}


# CORS
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response


@app.route("/api/profiles", methods=["OPTIONS"])
@app.route("/api/profiles/<profile_id>", methods=["OPTIONS"])
@app.route("/api/profiles/search", methods=["OPTIONS"])
def handle_options(profile_id=None):
    return "", 204


# Routes
@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "Profile Intelligence Service is running"})


@app.route("/api/profiles", methods=["POST"])
def create_profile():
    body = request.get_json(silent=True)

    if not body or "name" not in body:
        return jsonify({"status": "error", "message": "Missing or empty name"}), 400

    name = body["name"]

    if not isinstance(name, str):
        return jsonify({"status": "error", "message": "Invalid type"}), 422

    name = name.strip()
    if not name:
        return jsonify({"status": "error", "message": "Missing or empty name"}), 400

    # Idempotency, return existing profile
    existing = Profile.query.filter(
        db.func.lower(Profile.name) == name.lower()
    ).first()
    if existing:
        return jsonify({
            "status": "success",
            "message": "Profile already exists",
            "data": existing.to_dict()
        }), 200

    # Call all three external APIs
    genderize_data, err = fetch_external(
        f"https://api.genderize.io?name={name}", "Genderize"
    )
    if err:
        return jsonify(err[0]), err[1]

    agify_data, err = fetch_external(
        f"https://api.agify.io?name={name}", "Agify"
    )
    if err:
        return jsonify(err[0]), err[1]

    nationalize_data, err = fetch_external(
        f"https://api.nationalize.io?name={name}", "Nationalize"
    )
    if err:
        return jsonify(err[0]), err[1]

    # Validate Genderize
    gender = genderize_data.get("gender")
    g_count = genderize_data.get("count", 0)
    if gender is None or g_count == 0:
        return jsonify({"status": "error", "message": "Genderize returned an invalid response"}), 502

    gender_probability = genderize_data.get("probability", 0)
    sample_size = g_count

    # Validate Agify
    age = agify_data.get("age")
    if age is None:
        return jsonify({"status": "error", "message": "Agify returned an invalid response"}), 502

    age_group = classify_age_group(age)

    # Validate Nationalize
    countries = nationalize_data.get("country", [])
    if not countries:
        return jsonify({"status": "error", "message": "Nationalize returned an invalid response"}), 502

    top_country = max(countries, key=lambda c: c.get("probability", 0))
    country_id = top_country.get("country_id")
    country_probability = top_country.get("probability", 0)

    if not country_id:
        return jsonify({"status": "error", "message": "Nationalize returned an invalid response"}), 502

    country_name = COUNTRY_ID_TO_NAME.get(country_id, country_id)

    # Persist
    profile = Profile(
        id=uuid7(),
        name=name.lower(),
        gender=gender,
        gender_probability=gender_probability,
        sample_size=sample_size,
        age=age,
        age_group=age_group,
        country_id=country_id,
        country_name=country_name,
        country_probability=country_probability,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.session.add(profile)
    db.session.commit()

    return jsonify({"status": "success", "data": profile.to_dict()}), 201


@app.route("/api/profiles", methods=["GET"])
def list_profiles():
    # Pagination params
    try:
        page  = int(request.args.get("page",  1))
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid query parameters"}), 422

    if page < 1 or limit < 1:
        return jsonify({"status": "error", "message": "Invalid query parameters"}), 422

    limit = min(limit, 50)

    # Filter params
    gender               = request.args.get("gender")
    age_group            = request.args.get("age_group")
    country_id           = request.args.get("country_id")
    min_age_raw          = request.args.get("min_age")
    max_age_raw          = request.args.get("max_age")
    min_gender_prob_raw  = request.args.get("min_gender_probability")
    min_country_prob_raw = request.args.get("min_country_probability")

    # Validate numeric filters
    try:
        min_age          = int(min_age_raw)            if min_age_raw          is not None else None
        max_age          = int(max_age_raw)            if max_age_raw          is not None else None
        min_gender_prob  = float(min_gender_prob_raw)  if min_gender_prob_raw  is not None else None
        min_country_prob = float(min_country_prob_raw) if min_country_prob_raw is not None else None
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid query parameters"}), 422

    # Sorting params
    SORTABLE = {
        "age":                Profile.age,
        "created_at":         Profile.created_at,
        "gender_probability": Profile.gender_probability,
    }

    sort_by = request.args.get("sort_by", "created_at")
    order   = request.args.get("order",   "asc").lower()

    if sort_by not in SORTABLE:
        return jsonify({"status": "error", "message": "Invalid query parameters"}), 422
    if order not in ("asc", "desc"):
        return jsonify({"status": "error", "message": "Invalid query parameters"}), 422

    sort_col  = SORTABLE[sort_by]
    sort_expr = sort_col.desc() if order == "desc" else sort_col.asc()

    # Build query
    query = Profile.query

    if gender:
        query = query.filter(db.func.lower(Profile.gender) == gender.lower())
    if age_group:
        query = query.filter(db.func.lower(Profile.age_group) == age_group.lower())
    if country_id:
        query = query.filter(db.func.upper(Profile.country_id) == country_id.upper())
    if min_age is not None:
        query = query.filter(Profile.age >= min_age)
    if max_age is not None:
        query = query.filter(Profile.age <= max_age)
    if min_gender_prob is not None:
        query = query.filter(Profile.gender_probability >= min_gender_prob)
    if min_country_prob is not None:
        query = query.filter(Profile.country_probability >= min_country_prob)

    total    = query.count()
    profiles = query.order_by(sort_expr).offset((page - 1) * limit).limit(limit).all()

    return jsonify({
        "status": "success",
        "count":  total,
        "data":   [p.to_dict(summary=True) for p in profiles],
    }), 200


@app.route("/api/profiles/search", methods=["GET"])
def search_profiles():
    q_raw = request.args.get("q", "").strip()
    if not q_raw:
        return jsonify({"status": "error", "message": "Missing or empty parameter"}), 400

    # Pagination params
    try:
        page  = int(request.args.get("page",  1))
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid query parameters"}), 422

    if page < 1 or limit < 1:
        return jsonify({"status": "error", "message": "Invalid query parameters"}), 422

    limit = min(limit, 50)

    # Parse the natural language query into filters
    filters = _parse_nl_query(q_raw)
    if filters is None:
        return jsonify({"status": "error", "message": "Unable to interpret query"}), 200

    # Build query from parsed filters
    query = Profile.query

    if "gender" in filters:
        query = query.filter(db.func.lower(Profile.gender) == filters["gender"])
    if "age_group" in filters:
        query = query.filter(db.func.lower(Profile.age_group) == filters["age_group"])
    if "country_id" in filters:
        query = query.filter(db.func.upper(Profile.country_id) == filters["country_id"].upper())
    if "min_age" in filters:
        query = query.filter(Profile.age >= filters["min_age"])
    if "max_age" in filters:
        query = query.filter(Profile.age <= filters["max_age"])

    total    = query.count()
    profiles = query.order_by(Profile.created_at.asc()).offset((page - 1) * limit).limit(limit).all()

    return jsonify({
        "status": "success",
        "page":   page,
        "limit":  limit,
        "total":  total,
        "data":   [p.to_dict() for p in profiles],
    }), 200


def _parse_nl_query(text: str) -> dict | None:
    """
    Rule-based natural language -> filter dict.
    Returns None if the query cannot be interpreted at all.

    Supported patterns:
      - Gender:     male/males/man/men, female/females/woman/women
      - Age groups: teenager/teens, adult/adults, child/children, senior/elderly
      - "young":    treated as min_age=16, max_age=24 (not a stored age_group)
      - above/over/older than X  -> min_age
      - below/under/younger than X -> max_age
      - between X and Y          -> min_age + max_age
      - "from <country>" / "in <country>" -> country_id via name lookup
    """
    t = text.lower().strip()
    filters = {}
    matched_something = False

    # Gender detection
    has_male   = bool(re.search(r'\b(male|males|man|men)\b', t))
    has_female = bool(re.search(r'\b(female|females|woman|women)\b', t))

    if has_male and not has_female:
        filters["gender"] = "male"
        matched_something = True
    elif has_female and not has_male:
        filters["gender"] = "female"
        matched_something = True
    elif has_male and has_female:
        # Both genders mentioned — no gender filter, but still a valid signal
        matched_something = True

    # Age group keywords
    if re.search(r'\b(teenager|teenagers|teen|teens|teenage)\b', t):
        filters["age_group"] = "teenager"
        matched_something = True
    elif re.search(r'\b(adult|adults)\b', t):
        filters["age_group"] = "adult"
        matched_something = True
    elif re.search(r'\b(child|children|kid|kids)\b', t):
        filters["age_group"] = "child"
        matched_something = True
    elif re.search(r'\b(senior|seniors|elderly)\b', t):
        filters["age_group"] = "senior"
        matched_something = True
    elif re.search(r'\byoung\b', t):
        # "young" is a parsing alias only — maps to age range, not a stored age_group
        filters["min_age"] = 16
        filters["max_age"] = 24
        matched_something = True

    # Numeric age constraints
    m = re.search(r'\b(?:above|over|older than|greater than)\s+(\d+)\b', t)
    if m:
        filters["min_age"] = int(m.group(1))
        matched_something = True

    m = re.search(r'\b(?:below|under|younger than|less than)\s+(\d+)\b', t)
    if m:
        filters["max_age"] = int(m.group(1))
        matched_something = True

    m = re.search(r'\bbetween\s+(\d+)\s+and\s+(\d+)\b', t)
    if m:
        filters["min_age"] = int(m.group(1))
        filters["max_age"] = int(m.group(2))
        matched_something = True

    # Country extraction — match "from <country>" or "in <country>"
    country_match = re.search(
        r'\b(?:from|in)\s+([a-z][a-z\s\'-]+?)(?:\s*$|\s+(?:above|below|over|under|between|and|who|with|aged|age))',
        t
    )
    if not country_match:
        country_match = re.search(r'\b(?:from|in)\s+([a-z][a-z\s\'-]+)$', t)

    if country_match:
        country_phrase = country_match.group(1).strip()
        cid = COUNTRY_NAME_TO_ID.get(country_phrase)
        if not cid:
            # Handle demonyms like "nigerians" -> "nigeria"
            cid = COUNTRY_NAME_TO_ID.get(country_phrase.rstrip("s"))
        if not cid:
            # Fallback: scan for any known country name substring in the full query
            for cname, code in COUNTRY_NAME_TO_ID.items():
                if cname in t:
                    cid = code
                    break
        if cid:
            filters["country_id"] = cid
            matched_something = True
        else:
            # Country was mentioned but couldn't be resolved — cannot interpret
            return None

    if not matched_something:
        return None

    return filters


@app.route("/api/profiles/<profile_id>", methods=["GET"])
def get_profile(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"status": "error", "message": "Profile not found"}), 404

    return jsonify({"status": "success", "data": profile.to_dict()}), 200


@app.route("/api/profiles/<profile_id>", methods=["DELETE"])
def delete_profile(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"status": "error", "message": "Profile not found"}), 404

    db.session.delete(profile)
    db.session.commit()
    return "", 204


# Init DB & run
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)