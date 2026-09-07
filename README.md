# Job Application Tracker

<p align="left">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/Google_Cloud-Functions-4285F4?style=flat&logo=googlecloud&logoColor=white" alt="Google Cloud Functions" />
  <img src="https://img.shields.io/badge/Gemini_API-886FBF?style=flat" alt="Gemini API" />
  <img src="https://github.com/Abdullahifrh/job-tracker/actions/workflows/deploy.yml/badge.svg" alt="CI/CD Status" />
</p>

An automation that watches Gmail for job-application activity, uses an LLM to turn each relevant email into structured data and keeps a Google Sheet up to date automatically. No manual data entry for status changes needed.

## What it does

1. Scans Gmail on a schedule (every 2 hours) for likely application-related mail, in both directions: replies received and open applications/emails sent.
2. Passes each candidate email to an LLM, which classifies it (applied / interview scheduled / interviewed / offer / rejected / not relevant) and pulls out company, role, location and salary (but only at the offer stage).
3. Matches the result against existing rows in a Google Sheet by normalized company name, updates the row in place if found, or creates a new one if not. Manually-added rows are never overwritten, only filled in where blank.
4. Runs unattended as a scheduled, serverless Cloud Function, with structured logging, retry-with-backoff on transient API failures and an email alert to yourself if a run fails outright.

## Sample output

Purely for illustration purposes (only a portion of the actual columns shown): the values below use the same fake company names as the test suite (`tests/test_extractor.py`, `tests/fixtures/`), not real data:

| Company | Job Title | Status | Last Updated |
|---|---|---|---|
| Acme Corp | Data Engineer | Applied | 2026-08-14 |
| Globex | Backend Engineer | Interview Scheduled | 2026-08-20 |
| Bluepeak Systems | Data Engineer | Offer | 2026-08-29 |
| Solace Dynamics | Backend Engineer | Rejected | 2026-08-22 |

## Architecture

```
Cloud Scheduler (every 2h)
        │  HTTP trigger, authenticated via a dedicated invoker service account
        ▼
Cloud Function (Python, gen2)
        │
        ├─► Gmail API: search for new messages since last run
        │        (skip message IDs already recorded as processed)
        │
        ├─► For each new message:
        │        decode MIME body → LLM structured extraction call
        │        → {company, role, status, location, salary, confidence}
        │
        ├─► Google Sheets API:
        │        normalize company name, match or create a row
        │        update status only on forward progress; rejection always applies
        │        ambiguous matches are skipped and logged, never guessed
        │
        ├─► Periodic sweep: applications stuck on "applied" past a time
        │        threshold with no reply get flipped to "no reply" —
        │        this can only be detected by absence, not by any single email
        │
        └─► On unrecoverable failure: log the error and email yourself
```

## Tech stack

- **Language:** Python
- **APIs:** Gmail API, Google Sheets API, Gemini API (or Claude, interchangeable; but I prefer to use Gemini API)
- **Cloud:** Google Cloud Functions, Cloud Scheduler, Secret Manager, IAM
- **Auth:** OAuth2 (installed-app flow locally, secret-backed environment variable in the cloud), Workload Identity Federation for CI/CD
- **CI/CD:** GitHub Actions, testing then deploying on every push to main
- **Testing:** pytest, fully offline — every external call is mocked and a network-blocking fixture enforces this automatically

## Implementation Details

- OAuth2 installed-app flow with a single credential-loading path shared between local execution (file-based token) and cloud execution (secret-backed environment variable).
- Idempotent, direction-aware email ingestion — Gmail's own `labelIds` and the `Auto-Submitted` header are used to distinguish sent vs. received mail and detect autoresponders, rather than inferring either from message text.
- Normalized-entity matching for the Sheets upsert layer, with forward-progress status ranking and blank-only field updates so manually maintained rows are never overwritten.
- Deployed as a scheduled, serverless Cloud Function with IAM-scoped service accounts, Secret Manager-backed credentials and Workload Identity Federation for keyless CI/CD.
- Retry-with-backoff on all external API calls, structured logging and failure alerting for unattended operation.

## Known Limitations

- The keyword pre-filter is intentionally broad; the LLM extraction step is the actual classifier.
- Ambiguous company/role matches are skipped and logged rather than resolved automatically.
- OAuth refresh tokens can be invalidated independently of this code; authentication failures should be checked here first.