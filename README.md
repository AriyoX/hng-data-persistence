# Profile Intelligence Service — HNG Stage 2

Enriches names using Genderize, Agify, and Nationalize APIs, stores results in a database, and exposes a queryable REST API with filtering, sorting, pagination, and natural language search.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/profiles | Create a profile |
| GET | /api/profiles | List profiles (filterable, sortable, paginated) |
| GET | /api/profiles/search | Natural language search |
| GET | /api/profiles/{id} | Get profile by ID |
| DELETE | /api/profiles/{id} | Delete profile |

### POST /api/profiles
```json
{ "name": "ella" }
```
Returns 201 on creation, 200 if name already exists (idempotent).

### GET /api/profiles
Supports filtering, sorting, and pagination.

**Filters:**

| Param | Example |
|-------|---------|
| `gender` | `male` or `female` |
| `age_group` | `child`, `teenager`, `adult`, `senior` |
| `country_id` | `NG`, `KE`, `GH` (ISO-2) |
| `min_age` | `25` |
| `max_age` | `40` |
| `min_gender_probability` | `0.9` |
| `min_country_probability` | `0.1` |

All filters are combinable and must all match.

**Sorting:**

| Param | Values |
|-------|--------|
| `sort_by` | `age`, `created_at`, `gender_probability` |
| `order` | `asc` (default), `desc` |

**Pagination:**

| Param | Default | Max |
|-------|---------|-----|
| `page` | `1` | — |
| `limit` | `10` | `50` |

**Response shape:**
```json
{
  "status": "success",
  "page": 1,
  "limit": 10,
  "total": 2026,
  "data": [ ... ]
}
```

Examples:
```bash
# Basic filter
curl "http://localhost:5000/api/profiles?gender=male&country_id=NG&min_age=25"

# Sort and paginate
curl "http://localhost:5000/api/profiles?sort_by=age&order=desc&page=2&limit=20"

# Combined
curl "http://localhost:5000/api/profiles?age_group=teenager&min_gender_probability=0.9"
```

### GET /api/profiles/search
Natural language query — rule-based, no AI/LLMs.

```bash
curl "http://localhost:5000/api/profiles/search?q=young+males+from+nigeria"
curl "http://localhost:5000/api/profiles/search?q=adult+females+from+kenya&page=1&limit=5"
```

**Example mappings:**

| Query | Filters applied |
|-------|-----------------|
| `young males from nigeria` | gender=male, min_age=16, max_age=24, country_id=NG |
| `females above 30` | gender=female, min_age=30 |
| `people from angola` | country_id=AO |
| `adult males from kenya` | gender=male, age_group=adult, country_id=KE |
| `male and female teenagers above 17` | age_group=teenager, min_age=17 |

Queries that can't be interpreted return:
```json
{ "status": "error", "message": "Unable to interpret query" }
```

Pagination (`page`, `limit`) applies here too.

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

Seed the database:
```bash
python seed.py seed_profiles.json
```
Re-running is safe — existing records are skipped.

Test it:
```bash
# Create a profile
curl -X POST http://localhost:5000/api/profiles \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"ella\"}"

# List profiles (with filters)
curl "http://localhost:5000/api/profiles?gender=female&age_group=adult"

# Natural language search
curl "http://localhost:5000/api/profiles/search?q=young+males+from+nigeria"

# Sort by age descending
curl "http://localhost:5000/api/profiles?sort_by=age&order=desc"

# Get by ID
curl http://localhost:5000/api/profiles/<id>

# Delete
curl -X DELETE http://localhost:5000/api/profiles/<id>
```