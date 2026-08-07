# Weather Atlas — PMA Weather Records API

**PM Accelerator AI Engineer Technical Assessment — Backend Tech Assessment #2**

Candidate: **Rida Boubakr**

A backend-first weather application that resolves a user-entered location, retrieves a useful daily weather snapshot for a date range, and persists both the request and retrieved data. It exposes RESTful CRUD operations, traveler-oriented nearby places, and database exports through FastAPI. A lightweight bonus Weather Explorer at `/dashboard` consumes those same APIs and demonstrates how the backend can support a coherent product experience.

## Requirement coverage

| Assessment requirement | Implementation |
|---|---|
| Real weather API | Open-Meteo daily forecast data |
| Location input and validation | Open-Meteo Geocoding for city, town, or postal-code lookup; provider fuzzy matching and canonical location storage |
| Date range | ISO dates, coherent-order checks, maximum 16 days, and provider-window validation |
| Persistence and CRUD | SQLite with SQLAlchemy; request records and normalized daily weather rows |
| Useful output | Mean/min/max and apparent temperature, precipitation, probability, humidity, wind, weather code/description, timezone, coordinates, and retrieval time |
| Additional API | Wikimedia geosearch returns nearby notable Wikipedia places from stored coordinates |
| Data export | Downloadable JSON and flattened CSV exports |
| Error handling | Structured validation, not-found, timeout, upstream-status, and malformed-payload errors |

### Bonus product enhancements

These features are intentionally labeled as post-assessment polish, not mandatory DOCX requirements:

- **Weather Explorer:** responsive vanilla HTML/CSS/JavaScript dashboard; no frontend toolchain or duplicated backend logic.
- **Weather-aware outing planner:** explainable 0–100 suitability score that combines stored daily weather with nearby Wikimedia places. It is deterministic and is not presented as AI/ML.
- **Deliberate location selection:** ranked geocoding candidates show region, country, coordinates, and timezone so an ambiguous place can be selected by provider ID.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Project, candidate, and assessment identification |
| `GET` | `/health` | Health check |
| `GET` | `/about` | Candidate and PM Accelerator information |
| `GET` | `/dashboard` | Optional reviewer-facing Weather Explorer |
| `GET` | `/locations/search` | Search ranked location candidates |
| `POST` | `/weather` | Resolve, retrieve, and persist a weather request |
| `GET` | `/weather` | List stored requests |
| `GET` | `/weather/{id}` | Read one stored request and its daily snapshot |
| `PATCH` | `/weather/{id}` | Change request fields and atomically refresh weather data |
| `DELETE` | `/weather/{id}` | Delete a record and its daily rows |
| `GET` | `/weather/{id}/nearby` | Retrieve nearby notable places from Wikimedia |
| `GET` | `/weather/{id}/outing-plan` | Score outing days and combine the best with nearby places |
| `GET` | `/weather/export?format=json\|csv` | Export all stored records |

Open the [Weather Explorer](http://127.0.0.1:8000/dashboard) for the product demo or [Swagger documentation](http://127.0.0.1:8000/docs) for direct REST evaluation.

## Technology and design

- FastAPI and Pydantic provide a typed REST/OpenAPI boundary and consistent validation.
- SQLAlchemy and SQLite provide portable SQL persistence without external setup.
- `httpx` provides async external API calls with configurable timeouts.
- A parent `weather_records` table stores resolved request metadata; child `weather_days` rows store queryable daily observations/forecasts.
- External providers are isolated in small client modules and replaced with fakes or mock transports in tests.
- The outing score is a pure service over persisted rows, so it adds no migration and is independently unit-tested.

Project structure:

```text
app/
  api/routes.py             REST routes and export serialization
  services/open_meteo.py    geocoding, date-window checks, weather parsing
  services/wikimedia.py     nearby-place integration
  services/outing_planner.py deterministic, explainable suitability scoring
  services/records.py       CRUD orchestration and transaction boundaries
  config.py                 environment-backed settings
  database.py               engine/session setup
  models.py                 SQLAlchemy models
  schemas.py                request/response models
  errors.py                 safe application errors
  main.py                   FastAPI application factory
  static/                   no-build Weather Explorer HTML/CSS/JavaScript
tests/                      mocked API and persistence tests
```

## External APIs

- [Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api) resolves textual locations and postal codes. Inputs of three or more characters use the provider's fuzzy matching. The first provider-ranked result is selected, and the API reports whether the selected name was exact or fuzzy.
- [Open-Meteo Forecast API](https://open-meteo.com/en/docs) supplies real daily weather values. This project accepts at most 16 inclusive days, from 92 days before the server date through 15 days after it.
- [MediaWiki Geosearch API](https://www.mediawiki.org/wiki/API:Geosearch) finds geotagged English Wikipedia articles within a configurable radius of a stored location.

These public endpoints require no API keys. Base URLs and timeouts remain configurable for testing or self-hosted alternatives.

## Fresh setup

Python 3.11 or newer is recommended.

PowerShell:

```powershell
git clone <repository-url>
cd <repository-folder>
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

macOS/Linux:

```bash
git clone <repository-url>
cd <repository-folder>
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

The application creates `weather.db` and its schema deterministically on startup. No migration command or secret is needed for this assessment.

## Example requests

Swagger is the fastest way to evaluate the application. For PowerShell, this creates a request using dates that remain valid whenever the command is run:

```powershell
$today = (Get-Date).ToString('yyyy-MM-dd')
$tomorrow = (Get-Date).AddDays(1).ToString('yyyy-MM-dd')
$body = @{ location = 'Casablanca'; start_date = $today; end_date = $tomorrow } | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/weather -ContentType 'application/json' -Body $body
Invoke-RestMethod http://127.0.0.1:8000/weather
Invoke-RestMethod http://127.0.0.1:8000/weather/1
Invoke-RestMethod http://127.0.0.1:8000/weather/1/nearby?radius_m=10000`&limit=5
Invoke-RestMethod http://127.0.0.1:8000/weather/1/outing-plan
```

Search an ambiguous location before creating a record:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/locations/search?query=Casablanca'
```

The dashboard sends the selected candidate's `location_id` together with the visible location text. Omitting `location_id` preserves the original provider-ranked behavior and REST contract.

Update a request. The application re-resolves and re-fetches instead of permitting manual edits to trusted weather values:

```powershell
Invoke-RestMethod -Method Patch -Uri http://127.0.0.1:8000/weather/1 `
  -ContentType 'application/json' -Body '{"location":"Rabat"}'
```

Delete it:

```powershell
Invoke-RestMethod -Method Delete -Uri http://127.0.0.1:8000/weather/1
```

## Validation and errors

Locations are whitespace-normalized, resolved against a real geocoder, and stored as both original and canonical values. Unresolved locations return `422`. Dates must be valid ISO dates, `end_date` cannot precede `start_date`, the inclusive range cannot exceed 16 days, and dates outside the configured provider window return a detailed `422` response.

External timeouts return `504`; network failures, upstream 4xx/5xx responses, or unexpected provider payloads return safe `502` responses. Missing records return `404`. Errors use this shape:

```json
{
  "error": {
    "code": "location_not_found",
    "message": "Could not resolve location 'Atlantis'. Try a city, town, or postal code."
  }
}
```

## Exports

Open either URL after records exist:

- [JSON export](http://127.0.0.1:8000/weather/export?format=json)
- [CSV export](http://127.0.0.1:8000/weather/export?format=csv)

Both responses use an appropriate media type and a timestamped attachment filename. JSON preserves nested records and daily rows; CSV emits one row per weather day.

## Tests

```powershell
python -m pytest -q
```

The suite uses an isolated SQLite database and no live internet calls. It covers health/metadata, CREATE, validation, invalid location, list/get/missing reads, UPDATE/refetch, DELETE/missing delete, persistence across restart, safe provider failures and malformed data, JSON/CSV export, and Wikimedia integration.

Bonus coverage includes candidate search/selection, deterministic outing ranking and missing-data penalties, planner provider failures, and dashboard/static asset delivery. The dashboard JavaScript is also syntax-checked separately during final QA.

## Outing score

Every candidate day starts at 100. The service applies visible penalties for:

- forecast precipitation amount and maximum probability;
- WMO weather-condition severity;
- apparent temperature outside the 16–30°C comfort band;
- wind above 20 km/h;
- missing measurements.

The highest score wins; equal scores favor the earlier date. The endpoint returns the per-factor penalty breakdown and plain-language reasons, making the recommendation reproducible and explainable.

## PM Accelerator

The assessment asks the app to identify the candidate and include information about PM Accelerator. Product Manager Accelerator describes itself as supporting product-management professionals across career stages, from entry-level candidates to product leaders, through learning and career-development programs. See the [Product Manager Accelerator LinkedIn page](https://www.linkedin.com/school/pmaccelerator/) referenced by the assessment.

## Tradeoffs

- The focused input contract supports city/town names and postal codes rather than raw coordinates or browser geolocation.
- Location-only API clients still receive the first Open-Meteo ranked match. The bonus dashboard can deliberately choose another candidate through the additive `location_id` field.
- Forecast requests are intentionally capped at 16 days and a rolling provider window. A separate historical archive integration would be the next extension for old dates.
- Authentication and row-level security are omitted because the assessment explicitly says they are unnecessary.
- Docker and CI were intentionally deferred in favor of complete mandatory behavior, tests, and documentation.
- Nearby places come from geotagged English Wikipedia articles; relevance depends on Wikimedia coverage rather than a commercial places database.

## Two-minute evaluation flow

1. Open `/dashboard`, type Casablanca, and deliberately select the Morocco candidate.
2. Create a two- or three-day forecast and show the persisted resolved location.
3. Point out the best outing day, visible scoring factors, and daily cards.
4. Show nearby Wikimedia places and the saved SQLite record.
5. Open `/docs` briefly to show the underlying REST API, then mention tests and JSON/CSV export.
