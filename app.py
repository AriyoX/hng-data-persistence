import os
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

    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True, index=True)
    gender = db.Column(db.String(20))
    gender_probability = db.Column(db.Float)
    sample_size = db.Column(db.Integer)
    age = db.Column(db.Integer)
    age_group = db.Column(db.String(20))
    country_id = db.Column(db.String(10))
    country_probability = db.Column(db.Float)
    created_at = db.Column(db.String(30), nullable=False)

    def to_dict(self, summary=False):
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
        return None, ({"status": "error", "message": f"{api_name} returned an invalid response"}, 502)
    except requests.exceptions.RequestException:
        return None, ({"status": "error", "message": f"{api_name} returned an invalid response"}, 502)


# CORS 
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response


@app.route("/api/profiles", methods=["OPTIONS"])
@app.route("/api/profiles/<profile_id>", methods=["OPTIONS"])
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
        return jsonify({"status": "error", "message": "name must be a string"}), 422

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
        country_probability=country_probability,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.session.add(profile)
    db.session.commit()

    return jsonify({"status": "success", "data": profile.to_dict()}), 201


@app.route("/api/profiles", methods=["GET"])
def list_profiles():
    gender = request.args.get("gender")
    country_id = request.args.get("country_id")
    age_group = request.args.get("age_group")

    query = Profile.query

    if gender:
        query = query.filter(db.func.lower(Profile.gender) == gender.lower())
    if country_id:
        query = query.filter(db.func.lower(Profile.country_id) == country_id.lower())
    if age_group:
        query = query.filter(db.func.lower(Profile.age_group) == age_group.lower())

    profiles = query.all()

    return jsonify({
        "status": "success",
        "count": len(profiles),
        "data": [p.to_dict(summary=True) for p in profiles]
    }), 200


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
