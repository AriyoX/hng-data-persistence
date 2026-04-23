import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy

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

DEFAULT_PAGE = 1
DEFAULT_LIMIT = 10
MAX_LIMIT = 50


def uuid7() -> str:
    """Generate a UUID version 7 (time-ordered, millisecond precision)."""
    timestamp_ms = int(time.time() * 1000)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF
    high = (timestamp_ms << 16) | (0x7 << 12) | rand_a
    low = (0b10 << 62) | rand_b
    return str(uuid.UUID(int=(high << 64) | low))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Profile(db.Model):
    __tablename__ = "profiles"

    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True, index=True)
    gender = db.Column(db.String(20))
    gender_probability = db.Column(db.Float)
    sample_size = db.Column(db.Integer)
    age = db.Column(db.Integer, index=True)
    age_group = db.Column(db.String(20), index=True)
    country_id = db.Column(db.String(2), index=True)
    country_name = db.Column(db.String(100))
    country_probability = db.Column(db.Float)
    created_at = db.Column(db.String(30), nullable=False, index=True)

    def to_dict(self, summary: bool = False) -> Dict[str, Any]:
        if summary:
            return {
                "id": self.id,
                "name": self.name,
                "gender": self.gender,
                "age": self.age,
                "age_group": self.age_group,
                "country_id": self.country_id,
            }
        return {
            "id": self.id,
            "name": self.name,
            "gender": self.gender,
            "gender_probability": self.gender_probability,
            "sample_size": self.sample_size,
            "age": self.age,
            "age_group": self.age_group,
            "country_id": self.country_id,
            "country_probability": self.country_probability,
            "created_at": self.created_at,
        }


def classify_age_group(age: int) -> str:
    if age <= 12:
        return "child"
    if age <= 19:
        return "teenager"
    if age <= 59:
        return "adult"
    return "senior"


def error_response(message: str, status_code: int):
    return jsonify({"status": "error", "message": message}), status_code


def fetch_external(url: str, api_name: str) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[Dict[str, str], int]]]:
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json(), None
    except (requests.exceptions.RequestException, ValueError):
        return None, ({"status": "502", "message": f"{api_name} returned an invalid response"}, 502)


def parse_optional_int(name: str) -> Tuple[Optional[int], Optional[Tuple[Any, int]]]:
    raw = request.args.get(name)
    if raw is None:
        return None, None
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, error_response("Invalid query parameters", 422)


def parse_optional_float(name: str) -> Tuple[Optional[float], Optional[Tuple[Any, int]]]:
    raw = request.args.get(name)
    if raw is None:
        return None, None
    try:
        return float(raw), None
    except (TypeError, ValueError):
        return None, error_response("Invalid query parameters", 422)


def parse_pagination() -> Tuple[Optional[int], Optional[int], Optional[Tuple[Any, int]]]:
    try:
        page = int(request.args.get("page", DEFAULT_PAGE))
        limit = int(request.args.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        return None, None, error_response("Invalid query parameters", 422)

    if page < 1 or limit < 1:
        return None, None, error_response("Invalid query parameters", 422)

    # Hard cap to keep payloads predictable and performant.
    limit = min(limit, MAX_LIMIT)
    return page, limit, None


def parse_sorting(sortable: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[Tuple[Any, int]]]:
    sort_by = request.args.get("sort_by")
    order = request.args.get("order") or request.args.get("sort_order") or request.args.get("direction")
    sort = request.args.get("sort")

    # Accept alternate sort styles:
    # - sort=created_at
    # - sort=-created_at
    # - sort=created_at:desc
    if sort and not sort_by:
        token = sort.strip()
        if ":" in token:
            field, direction = token.split(":", 1)
            sort_by = field.strip()
            if not order:
                order = direction.strip()
        elif token.startswith("-"):
            sort_by = token[1:].strip()
            if not order:
                order = "desc"
        else:
            sort_by = token

    sort_by = (sort_by or "created_at").strip()
    order = (order or "asc").strip().lower()

    aliases = {
        "ascending": "asc",
        "descending": "desc",
        "1": "asc",
        "-1": "desc",
    }
    order = aliases.get(order, order)

    if sort_by not in sortable:
        return None, None, error_response("Invalid query parameters", 422)
    if order not in ("asc", "desc"):
        return None, None, error_response("Invalid query parameters", 422)

    return sort_by, order, None


def build_pagination(page: int, limit: int, total: int) -> Dict[str, Any]:
    total_pages = (total + limit - 1) // limit if total > 0 else 0
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1 and total_pages > 0,
    }


def paginated_success(data: list, total: int, page: int, limit: int):
    pagination = build_pagination(page, limit, total)
    return jsonify(
        {
            "status": "success",
            "count": len(data),
            "total": total,
            "page": page,
            "limit": limit,
            "pagination": pagination,
            "data": data,
        }
    ), 200


# Country name -> ISO-2 lookup for natural language query parsing
COUNTRY_NAME_TO_ID = {
    "nigeria": "NG",
    "ghana": "GH",
    "kenya": "KE",
    "ethiopia": "ET",
    "egypt": "EG",
    "tanzania": "TZ",
    "uganda": "UG",
    "angola": "AO",
    "mozambique": "MZ",
    "madagascar": "MG",
    "cameroon": "CM",
    "ivory coast": "CI",
    "cote d'ivoire": "CI",
    "niger": "NE",
    "mali": "ML",
    "burkina faso": "BF",
    "malawi": "MW",
    "zambia": "ZM",
    "senegal": "SN",
    "zimbabwe": "ZW",
    "guinea": "GN",
    "rwanda": "RW",
    "benin": "BJ",
    "burundi": "BI",
    "somalia": "SO",
    "togo": "TG",
    "sierra leone": "SL",
    "libya": "LY",
    "liberia": "LR",
    "mauritania": "MR",
    "eritrea": "ER",
    "gambia": "GM",
    "botswana": "BW",
    "namibia": "NA",
    "gabon": "GA",
    "lesotho": "LS",
    "guinea-bissau": "GW",
    "equatorial guinea": "GQ",
    "mauritius": "MU",
    "eswatini": "SZ",
    "djibouti": "DJ",
    "comoros": "KM",
    "cape verde": "CV",
    "sao tome": "ST",
    "seychelles": "SC",
    "south africa": "ZA",
    "south sudan": "SS",
    "democratic republic of congo": "CD",
    "congo": "CG",
    "central african republic": "CF",
    "chad": "TD",
    "sudan": "SD",
    "morocco": "MA",
    "algeria": "DZ",
    "tunisia": "TN",
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "france": "FR",
    "germany": "DE",
    "india": "IN",
    "china": "CN",
    "brazil": "BR",
    "canada": "CA",
    "australia": "AU",
    "japan": "JP",
    "mexico": "MX",
    "italy": "IT",
    "spain": "ES",
    "netherlands": "NL",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "poland": "PL",
    "portugal": "PT",
    "russia": "RU",
    "turkey": "TR",
    "indonesia": "ID",
    "pakistan": "PK",
    "bangladesh": "BD",
    "philippines": "PH",
    "vietnam": "VN",
    "thailand": "TH",
    "argentina": "AR",
    "colombia": "CO",
    "peru": "PE",
    "venezuela": "VE",
    "chile": "CL",
    "ecuador": "EC",
}

# ISO-2 -> country name (used when creating / seeding profiles)
COUNTRY_ID_TO_NAME = {
    "NG": "Nigeria",
    "GH": "Ghana",
    "KE": "Kenya",
    "ET": "Ethiopia",
    "EG": "Egypt",
    "TZ": "Tanzania",
    "UG": "Uganda",
    "AO": "Angola",
    "MZ": "Mozambique",
    "MG": "Madagascar",
    "CM": "Cameroon",
    "CI": "Côte d'Ivoire",
    "NE": "Niger",
    "ML": "Mali",
    "BF": "Burkina Faso",
    "MW": "Malawi",
    "ZM": "Zambia",
    "SN": "Senegal",
    "ZW": "Zimbabwe",
    "GN": "Guinea",
    "RW": "Rwanda",
    "BJ": "Benin",
    "BI": "Burundi",
    "SO": "Somalia",
    "TG": "Togo",
    "SL": "Sierra Leone",
    "LY": "Libya",
    "LR": "Liberia",
    "MR": "Mauritania",
    "ER": "Eritrea",
    "GM": "Gambia",
    "BW": "Botswana",
    "NA": "Namibia",
    "GA": "Gabon",
    "LS": "Lesotho",
    "GW": "Guinea-Bissau",
    "GQ": "Equatorial Guinea",
    "MU": "Mauritius",
    "SZ": "Eswatini",
    "DJ": "Djibouti",
    "KM": "Comoros",
    "CV": "Cape Verde",
    "ST": "São Tomé",
    "SC": "Seychelles",
    "ZA": "South Africa",
    "SS": "South Sudan",
    "CD": "DR Congo",
    "CG": "Congo",
    "CF": "Central African Republic",
    "TD": "Chad",
    "SD": "Sudan",
    "MA": "Morocco",
    "DZ": "Algeria",
    "TN": "Tunisia",
    "US": "United States",
    "GB": "United Kingdom",
    "FR": "France",
    "DE": "Germany",
    "IN": "India",
    "CN": "China",
    "BR": "Brazil",
    "CA": "Canada",
    "AU": "Australia",
    "JP": "Japan",
    "MX": "Mexico",
    "IT": "Italy",
    "ES": "Spain",
    "NL": "Netherlands",
    "SE": "Sweden",
    "NO": "Norway",
    "DK": "Denmark",
    "FI": "Finland",
    "PL": "Poland",
    "PT": "Portugal",
    "RU": "Russia",
    "TR": "Turkey",
    "ID": "Indonesia",
    "PK": "Pakistan",
    "BD": "Bangladesh",
    "PH": "Philippines",
    "VN": "Vietnam",
    "TH": "Thailand",
    "AR": "Argentina",
    "CO": "Colombia",
    "PE": "Peru",
    "VE": "Venezuela",
    "CL": "Chile",
    "EC": "Ecuador",
}


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response


@app.route("/api/profiles", methods=["OPTIONS"])
@app.route("/api/profiles/<profile_id>", methods=["OPTIONS"])
@app.route("/api/profiles/search", methods=["OPTIONS"])
def handle_options(profile_id=None):  # noqa: ARG001
    return "", 204


@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "Profile Intelligence Service is running"})


@app.route("/api/profiles", methods=["POST"])
def create_profile():
    body = request.get_json(silent=True)
    if not body or "name" not in body:
        return error_response("Missing or empty name", 400)

    name = body["name"]
    if not isinstance(name, str):
        return error_response("Invalid type", 422)

    name = name.strip()
    if not name:
        return error_response("Missing or empty name", 400)

    normalized_name = name.lower()

    existing = Profile.query.filter(db.func.lower(Profile.name) == normalized_name).first()
    if existing:
        return jsonify(
            {
                "status": "success",
                "message": "Profile already exists",
                "data": existing.to_dict(),
            }
        ), 200

    genderize_data, err = fetch_external(f"https://api.genderize.io?name={normalized_name}", "Genderize")
    if err:
        return jsonify(err[0]), err[1]

    agify_data, err = fetch_external(f"https://api.agify.io?name={normalized_name}", "Agify")
    if err:
        return jsonify(err[0]), err[1]

    nationalize_data, err = fetch_external(f"https://api.nationalize.io?name={normalized_name}", "Nationalize")
    if err:
        return jsonify(err[0]), err[1]

    gender = (genderize_data or {}).get("gender")
    g_count = (genderize_data or {}).get("count", 0)
    if gender is None or g_count == 0:
        return jsonify({"status": "error", "message": "Genderize returned an invalid response"}), 502

    age = (agify_data or {}).get("age")
    if age is None:
        return jsonify({"status": "error", "message": "Agify returned an invalid response"}), 502

    countries = (nationalize_data or {}).get("country", [])
    if not countries:
        return jsonify({"status": "error", "message": "Nationalize returned an invalid response"}), 502

    top_country = max(countries, key=lambda c: c.get("probability", 0))
    country_id = top_country.get("country_id")
    if not country_id:
        return jsonify({"status": "error", "message": "Nationalize returned an invalid response"}), 502

    profile = Profile(
        id=uuid7(),
        name=normalized_name,
        gender=gender,
        gender_probability=(genderize_data or {}).get("probability", 0),
        sample_size=g_count,
        age=age,
        age_group=classify_age_group(age),
        country_id=country_id,
        country_name=COUNTRY_ID_TO_NAME.get(country_id, country_id),
        country_probability=top_country.get("probability", 0),
        created_at=utc_now_iso(),
    )
    db.session.add(profile)
    db.session.commit()

    return jsonify({"status": "success", "data": profile.to_dict()}), 201


@app.route("/api/profiles", methods=["GET"])
def list_profiles():
    page, limit, pagination_error = parse_pagination()
    if pagination_error:
        return pagination_error

    min_age, err = parse_optional_int("min_age")
    if err:
        return err
    max_age, err = parse_optional_int("max_age")
    if err:
        return err
    min_gender_prob, err = parse_optional_float("min_gender_probability")
    if err:
        return err
    min_country_prob, err = parse_optional_float("min_country_probability")
    if err:
        return err

    if min_age is not None and max_age is not None and min_age > max_age:
        return error_response("Invalid query parameters", 422)

    if min_gender_prob is not None and not (0 <= min_gender_prob <= 1):
        return error_response("Invalid query parameters", 422)
    if min_country_prob is not None and not (0 <= min_country_prob <= 1):
        return error_response("Invalid query parameters", 422)

    sortable = {
        "age": Profile.age,
        "created_at": Profile.created_at,
        "gender_probability": Profile.gender_probability,
    }
    sort_by, order, sort_error = parse_sorting(sortable)
    if sort_error:
        return sort_error

    query = Profile.query

    gender = request.args.get("gender")
    age_group = request.args.get("age_group")
    country_id = request.args.get("country_id")

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

    total = query.count()
    sort_col = sortable[sort_by]
    primary = sort_col.desc() if order == "desc" else sort_col.asc()
    secondary = Profile.id.desc() if order == "desc" else Profile.id.asc()

    profiles = query.order_by(primary, secondary).offset((page - 1) * limit).limit(limit).all()

    return paginated_success([p.to_dict() for p in profiles], total, page, limit)


@app.route("/api/profiles/search", methods=["GET"])
def search_profiles():
    q_raw = request.args.get("q", "").strip()
    if not q_raw:
        return error_response("Missing or empty parameter", 400)

    page, limit, pagination_error = parse_pagination()
    if pagination_error:
        return pagination_error

    filters = _parse_nl_query(q_raw)
    if filters is None:
        return error_response("Unable to interpret query", 422)

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

    total = query.count()
    profiles = query.order_by(Profile.created_at.asc(), Profile.id.asc()).offset((page - 1) * limit).limit(limit).all()

    return paginated_success([p.to_dict() for p in profiles], total, page, limit)


def _parse_nl_query(text: str) -> Optional[Dict[str, Any]]:
    """
    Rule-based natural language -> filter dict.
    Returns None if the query cannot be interpreted at all.
    """
    t = text.lower().strip()
    filters: Dict[str, Any] = {}
    matched_something = False

    has_male = bool(re.search(r"\b(male|males|man|men)\b", t))
    has_female = bool(re.search(r"\b(female|females|woman|women)\b", t))

    if has_male and not has_female:
        filters["gender"] = "male"
        matched_something = True
    elif has_female and not has_male:
        filters["gender"] = "female"
        matched_something = True
    elif has_male and has_female:
        matched_something = True

    if re.search(r"\b(teenager|teenagers|teen|teens|teenage)\b", t):
        filters["age_group"] = "teenager"
        matched_something = True
    elif re.search(r"\b(adult|adults)\b", t):
        filters["age_group"] = "adult"
        matched_something = True
    elif re.search(r"\b(child|children|kid|kids)\b", t):
        filters["age_group"] = "child"
        matched_something = True
    elif re.search(r"\b(senior|seniors|elderly)\b", t):
        filters["age_group"] = "senior"
        matched_something = True
    elif re.search(r"\byoung\b", t):
        filters["min_age"] = 16
        filters["max_age"] = 24
        matched_something = True

    m = re.search(r"\b(?:above|over|older than|greater than)\s+(\d+)\b", t)
    if m:
        filters["min_age"] = int(m.group(1))
        matched_something = True

    m = re.search(r"\b(?:below|under|younger than|less than)\s+(\d+)\b", t)
    if m:
        filters["max_age"] = int(m.group(1))
        matched_something = True

    m = re.search(r"\bbetween\s+(\d+)\s+and\s+(\d+)\b", t)
    if m:
        filters["min_age"] = int(m.group(1))
        filters["max_age"] = int(m.group(2))
        matched_something = True

    country_match = re.search(
        r"\b(?:from|in)\s+([a-z][a-z\s'-]+?)(?:\s*$|\s+(?:above|below|over|under|between|and|who|with|aged|age))",
        t,
    )
    if not country_match:
        country_match = re.search(r"\b(?:from|in)\s+([a-z][a-z\s'-]+)$", t)

    if country_match:
        country_phrase = country_match.group(1).strip()
        cid = COUNTRY_NAME_TO_ID.get(country_phrase)
        if not cid:
            cid = COUNTRY_NAME_TO_ID.get(country_phrase.rstrip("s"))
        if not cid:
            for cname, code in COUNTRY_NAME_TO_ID.items():
                if cname in t:
                    cid = code
                    break
        if cid:
            filters["country_id"] = cid
            matched_something = True
        else:
            return None

    if not matched_something:
        return None

    return filters


@app.route("/api/profiles/<profile_id>", methods=["GET"])
def get_profile(profile_id):
    profile = db.session.get(Profile, profile_id)
    if not profile:
        return error_response("Profile not found", 404)
    return jsonify({"status": "success", "data": profile.to_dict()}), 200


@app.route("/api/profiles/<profile_id>", methods=["DELETE"])
def delete_profile(profile_id):
    profile = db.session.get(Profile, profile_id)
    if not profile:
        return error_response("Profile not found", 404)

    db.session.delete(profile)
    db.session.commit()
    return "", 204


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)