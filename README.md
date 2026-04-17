# Profile Intelligence Service — HNG Stage 1

Enriches names using Genderize, Agify, and Nationalize APIs, stores results in a database, and exposes a clean REST API.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/profiles | Create a profile |
| GET | /api/profiles | List all profiles (filterable) |
| GET | /api/profiles/{id} | Get profile by ID |
| DELETE | /api/profiles/{id} | Delete profile |

### POST /api/profiles
```json
{ "name": "ella" }
```
Returns 201 on creation, 200 if name already exists (idempotent).

### GET /api/profiles
Optional filters: `?gender=male&country_id=NG&age_group=adult`

### DELETE /api/profiles/{id}
Returns 204 No Content.

---

## Run Locally

```bash
git clone <your-repo>
cd <repo>

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

python app.py
# → http://localhost:5000
```

Test it:
```bash
# Create a profile
curl -X POST http://localhost:5000/api/profiles \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"ella\"}"

# List profiles
curl http://localhost:5000/api/profiles

# Filter
curl "http://localhost:5000/api/profiles?gender=female"

# Get by ID
curl http://localhost:5000/api/profiles/<id>

# Delete
curl -X DELETE http://localhost:5000/api/profiles/<id>
```

