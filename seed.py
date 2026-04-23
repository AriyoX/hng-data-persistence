import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from app import app, db, Profile, classify_age_group, uuid7, COUNTRY_ID_TO_NAME

def seed(filepath: str = "seed_data.json"):
    if not os.path.exists(filepath):
        print(f"[seed] File not found: {filepath}")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = next((v for v in data.values() if isinstance(v, list)), [])
    else:
        print("[seed] Unexpected JSON format — expected an array or an object wrapping one.")
        sys.exit(1)

    print(f"[seed] Loaded {len(records)} records from {filepath}")

    inserted = 0
    skipped  = 0

    with app.app_context():
        db.create_all()

        with db.engine.connect() as conn:
            result = conn.execute(db.text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'profiles' AND column_name = 'country_name'
            """))
            if result.fetchone() is None:
                conn.execute(db.text("ALTER TABLE profiles ADD COLUMN country_name VARCHAR(100)"))
                conn.commit()
                print("[seed] Migrated: added country_name column")

        for row in records:
            name = (row.get("name") or "").strip().lower()
            if not name:
                skipped += 1
                continue

            if Profile.query.filter(db.func.lower(Profile.name) == name).first():
                skipped += 1
                continue

            country_id = (row.get("country_id") or "").strip().upper()
            country_name = row.get("country_name") or COUNTRY_ID_TO_NAME.get(country_id, country_id)

            age = row.get("age")
            if age is None:
                skipped += 1
                continue

            age_group = row.get("age_group") or classify_age_group(int(age))

            created_at = row.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            profile = Profile(
                id                 = uuid7(),
                name               = name,
                gender             = (row.get("gender") or "").lower(),
                gender_probability = float(row.get("gender_probability") or 0),
                sample_size        = int(row.get("sample_size") or 0),
                age                = int(age),
                age_group          = age_group,
                country_id         = country_id,
                country_name       = country_name,
                country_probability= float(row.get("country_probability") or 0),
                created_at         = created_at,
            )
            db.session.add(profile)
            inserted += 1

            if inserted % 200 == 0:
                db.session.commit()
                print(f"  ... committed {inserted} so far")

        db.session.commit()

    print(f"[seed] Done. Inserted: {inserted}, Skipped (existing/invalid): {skipped}")


if __name__ == "__main__":
    filepath = sys.argv[1] if len(sys.argv) > 1 else "seed_data.json"
    seed(filepath)