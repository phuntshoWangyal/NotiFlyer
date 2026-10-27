# NotiFlyer — Design Document

> Draft for cross-checking. Items marked **[BUILT]** exist and have been run, **[PLANNED]** are decided but not built, and **[OPEN]** are unresolved questions.

---

## 1. Overview

NotiFlyer is an automated deal tracker for Canadian retail flyers. The user keeps a watchlist of products they buy regularly (e.g. jasmine rice, protein powder, creatine). The app checks flyer data **every day**, filters to real sale listings, and alerts the user **once per deal per week**. A deal already seen in the current flyer week is ignored (a user can't finish a whole jar of protein powder in a week), but when the next week starts the seen list resets, so the same deal can alert again (the user may have used up the previous purchase by then). Users can also record purchases to track how much money they have saved.

**Name:** NotiFlyer
**Default location:** Fredericton, NB (postal code `E3B1X9`). Postal code should become a user setting.

### Goals
- Remove the manual work of checking multiple store flyers each week
- Notify at most once per deal per week (no repeat alerts within the same week; the same deal can alert again in a later week)
- Cover multiple stores in one place (Walmart, Atlantic Superstore, No Frills, Sobeys, Shoppers Drug Mart, etc.), so the user can see when another store has a better deal
- Track cumulative savings from deals the user actually bought
- Serve as a full-stack portfolio/resume project

### Non-goals (for now)
- Scraping store websites directly (ToS and fragility concerns)
- Auto-purchasing anything
- Multi-user accounts at scale (single-user first)

---

## 2. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Frontend | JavaScript + React **[PLANNED]** | Watchlist management, deal viewing, savings dashboard |
| Backend | Python (Flask) **[PLANNED]** | REST API wrapping the existing script logic |
| Core logic | Python + `requests` **[BUILT]** | Flipp fetching, parsing, filtering |
| Database | SQLite **[BUILT]** (`deals.db`) | May migrate to PostgreSQL/RDS if Lambda is used (see §9) |
| Hosting | AWS **[PLANNED]** | EC2 vs. Lambda undecided |
| Notifications | Email and/or SMS **[PLANNED]** | Provider undecided |

---

## 3. Architecture

```
React (frontend)  <-->  Flask (REST API)  <-->  SQLite / DB
                              |
                    Flipp search API (via requests)
                              |
                       Email / SMS alerts
                              |
                         AWS (hosting + scheduler)
```

- React never touches the database or Flipp directly; it only calls Flask endpoints over HTTP.
- A scheduled job runs the deal-check routine independently of the web UI.
- The "I bought this" link in alerts points to a Flask endpoint, so Flask must be reachable from the internet (hence AWS).

### Current file structure **[BUILT]**
```
automation projects/
├── database.py      # setup_database, is_deal_seen, save_deal
└── search_flipp.py  # search_flipp(), watch_list, main loop
```

---

## 4. Data Source: Flipp Search API

**Endpoint (found via browser DevTools, unofficial):**
`GET https://cdn-gateflipp.flippback.com/bf/flipp/items/search`

**Query params:** `locale=en-ca`, `postal_code=<code>`, `q=<search term>`
(`sid` is empty and not required.)

**Request notes**
- Send a browser-like `User-Agent` header (defensive; not strictly required so far)
- Rate limiting is real: back-to-back requests returned **HTTP 429**. A `time.sleep(2)` between searches fixed it
- This is an unofficial endpoint and may change or break without notice. Keep requests infrequent (daily/weekly)

**Response structure (relevant parts)**
| Key | Contents | Use |
|---|---|---|
| `items` | Flyer listings (`item_type: "flyer"`) | **The deals we track** |
| `ecom_items` | Regular online product listings (`item_type: "ecom"`) | Ignored for now; not sale-flagged |

**Fields on a flyer item:** `flyer_item_id`, `name`, `merchant_name`, `current_price`, `original_price`, `sale_story`, `valid_from`, `valid_to`.

**Data quirks observed**
- `original_price` is often `null` (e.g. No Frills, Sobeys, Shoppers) even though the item is a real sale. Being in the flyer list is itself the "this is a deal" signal
- `current_price` can be `None` for percentage-off deals (e.g. "Up to 20% off*"), so price comparisons must handle `None`
- `sale_story` is sometimes `null`; fall back to a generic label ("flyer special")
- The same product sometimes appears twice in one response (e.g. Walmart rice, whey protein)

---

## 5. Data Model

### `seen_deals` **[BUILT, needs `week_start` column]**
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `flyer_item_id` | TEXT | Flipp's ID; combined with `week_start` it forms the dedup key |
| `name` | TEXT | |
| `merchant_name` | TEXT | |
| `current_price` | REAL | Can be NULL |
| `date_seen` | TEXT | ISO date string |
| `week_start` | TEXT | **[PLANNED]** ISO date of the Thursday that starts the flyer week the deal was seen in |

Old rows are kept (not deleted when a new week starts), so they remain available for history, price trends, and savings features.

**Migration note:** `CREATE TABLE IF NOT EXISTS` won't add a column to an existing table. Since `deals.db` currently holds only test data, delete the file and let `setup_database()` recreate it.

### Planned additions **[PLANNED]**
- `watchlist` — `id`, `query`, `target_price` (optional), `created_at`
- `purchases` — `id`, `flyer_item_id` (FK-ish), `price_paid`, `regular_price`, `saved_amount`, `date_bought`
- `settings` — postal code, notification channel/address, check frequency
- Optional later: a `price_history` table (item, store, price, date) to power trend charts

**[OPEN]** Add a `UNIQUE` constraint on `flyer_item_id` so duplicates are impossible at the DB level, not just in application logic.

---

## 6. Core Logic

### Weekly dedup rule **[PLANNED]**

- The check runs **daily**
- A deal is "already seen" only if the same `flyer_item_id` was saved **in the current flyer week**
- When a new week starts, the same deal counts as new again and can alert again
- Weeks run **Thursday to Wednesday**, matching the observed flyer validity (`valid_from` dates were Thursdays). Some stores may start flyers on a different day, so the start day is a single constant (`WEEK_START_DAY = 3`, Monday = 0)
- Calendar-week logic is used rather than Flipp's `valid_from`/`valid_to`, since those aren't reliably present on every item

```python
WEEK_START_DAY = 3  # Thursday

def get_week_start():
    today = datetime.date.today()
    days_since = (today.weekday() - WEEK_START_DAY) % 7
    return str(today - datetime.timedelta(days=days_since))
```

- `is_deal_seen(flyer_item_id)` checks `WHERE flyer_item_id = ? AND week_start = ?` with the current week start
- `save_deal(...)` stores `get_week_start()` with each new row
- The main loop itself doesn't change; the week logic lives inside the two database functions

### Deal check loop **[BUILT, will use weekly rule once DB functions are updated]**
```
for each query in watchlist:
    GET flyer search for query
    for each item in response["items"]:
        if is_deal_seen(item.flyer_item_id): continue   # seen this week
        print / notify the deal
        save_deal(flyer_item_id, name, merchant_name, current_price)  # tagged with this week
    sleep 2s   # avoid 429
```

**Verified behaviour (before weekly rule):** first run printed all deals; second run printed none (all already seen).

**To test the weekly rule:** run twice in the same week (second run prints nothing), then temporarily make `get_week_start()` return a different date and run again (everything should print as new).

### Known issues / to verify
1. **Duplicate lines within a single run.** Some items printed twice in the first run. Need to confirm whether they share the same `flyer_item_id` (which would suggest a logic bug, since the second should be skipped after the first is saved) or have different IDs (genuinely separate Flipp rows). **[OPEN: not yet checked]**
2. **`setup_database()` must run before first use.** Either call it at startup (safe thanks to `CREATE TABLE IF NOT EXISTS`) or in `main`
3. **Hardcoded query in the `url` string** was a leftover bug; the base URL should contain no query string, since `params` supplies everything
4. **Expired deals.** `valid_to` is available but not yet used. Deals should be ignored or flagged once expired
5. **No error handling yet** for non-200 responses, empty bodies, or network failures (a 429 currently crashes on `.json()`)

---

## 7. Notifications **[PLANNED]**

- The deal check runs daily; send an alert when a deal for a watchlist item is found that hasn't already been seen **in the current flyer week**
- Channels: email first (`smtplib` or a provider), SMS later (e.g. Twilio)
- Each alert includes: store, product, sale price, original price/discount if known, validity dates, and an **"I bought this"** link
- Secrets (SMTP password, API keys) live in a `.env` file, never in the repo

---

## 8. Savings Tracking **[PLANNED]**

**Decision:** track *realized* savings only, meaning deals the user confirms they bought.

Flow:
1. User clicks **"Did you buy this?"** link in the alert (a URL like `/bought?deal=<flyer_item_id>`)
2. Flask looks up the deal
   - If `original_price` exists: saved = `original_price - price_paid`, recorded immediately
   - If `original_price` is `null`: show a small form asking "What do you usually pay for this?", then compute savings
3. Running total is stored and shown on the dashboard

**Why not auto-estimate the regular price:** a price history built only from flyer data would be biased toward sale prices, and matching flyer items to `ecom_items` is unreliable (different brands and sizes). Asking the user is simpler and more accurate.

**[OPEN]** For percentage-off deals with `current_price = None`, the user will need to enter the price paid as well.

---

## 9. Frontend (React) **[PLANNED]**

Features:
- Add / remove / edit watchlist items (optional target price per item)
- View active deals, with filter by store and price
- "Mark as bought" action and a **savings total** display
- Settings: postal code, notification channel and address, check frequency
- Optional: per-item price history chart

Pages (suggested): Watchlist · Deals · Savings · Settings

---

## 10. Backend API (Flask) **[PLANNED]**

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/watchlist` | List watchlist items |
| POST | `/watchlist` | Add an item |
| DELETE | `/watchlist/<id>` | Remove an item |
| GET | `/deals` | Current/seen deals |
| POST | `/bought` | Record a purchase (price paid, optional regular price) |
| GET | `/savings` | Total saved to date |
| GET/PUT | `/settings` | User settings |

The existing `search_flipp` logic is refactored into callable functions that both the scheduler and the API can use.

---

## 11. Deployment (AWS) **[PLANNED]**

Two candidate setups. **[OPEN: not decided]**

| Option | Backend | Scheduler | DB | Frontend |
|---|---|---|---|---|
| A: EC2 | Flask on one instance | cron on the instance | SQLite works as-is | S3 (+ CloudFront) |
| B: Serverless | Flask/Lambda | EventBridge schedule | Needs RDS (e.g. PostgreSQL), since Lambda's filesystem is ephemeral | S3 (+ CloudFront) |

Notes: the scheduler should trigger the deal check **once a day**; set a billing alert; keep secrets out of the repo; Option A is simpler, Option B is more "cloud-native."

---

## 12. Build Order

1. **Core Python logic** (in progress): SQLite seen-deals ✅, switch dedup to the weekly rule (add `week_start` column, update `is_deal_seen`/`save_deal`), fix known issues in §6, add error handling and expiry handling
2. Refactor into modules/functions reusable by an API
3. Flask API + watchlist/purchase tables
4. Notifications (email, then SMS) with "I bought this" links
5. React frontend
6. AWS deployment + scheduling

---

## 13. Risks & Considerations

- **Unofficial API:** the Flipp endpoint isn't a documented public API and could change or be restricted. Keep request volume low and fail gracefully
- **Terms of service:** use is personal and low-frequency; revisit before making the app public or multi-user
- **Data quality:** missing prices, duplicate rows, and percentage-off deals all need explicit handling
- **Secrets:** `.gitignore` the `.env` file and `deals.db`

---

## 14. Resume / Portfolio Notes

- Stack line: Python, Flask, React, SQLite/SQL, REST APIs, AWS
- Keep claims aligned with what is actually built; label unfinished parts "in progress" until they work
- Strong interview talking points: rate-limit handling, reverse-engineering an API via DevTools, parameterized SQL queries, dedup design, deployment trade-offs (EC2 vs. Lambda)
