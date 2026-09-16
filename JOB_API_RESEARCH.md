# Job API source catalog

Research date: 2026-09-15. Initial catalog of eight alternatives to Remotive.
Documentation research only: no job-feed requests, registrations, or collectors
were enabled. Published limits below are not measured throughput. Unknown means
not established from the cited official documentation, never unlimited.
Public API access does not imply an unrestricted license to republish job data.

## Coverage and limits

| Source | Access / coverage | Published request limits | Return size / pagination | Initial assessment |
| --- | --- | --- | --- | --- |
| Jobicy | No key; remote jobs across employers | Automated polling no more than hourly; a few checks/day normally sufficient | `count` 1-200, default 200; latest listings; no pagination documented | Simplest next broad feed; actual unique yield unmeasured |
| Greenhouse Job Board | No authentication for GET; one employer board per token | Numeric public GET quota not specified in reviewed docs | All posts for board; `content=true` includes descriptions; no jobs pagination documented | Strong expansion path through known employer boards |
| Lever Postings v0 | Public published jobs; one company site; global/EU hosts | Public GET quota not specified; documented 2/sec limit concerns application POST, not collection | `skip` + `limit`; numeric maximum/default not specified | Good employer-board adapter; needs pagination and site inventory |
| Ashby Job Postings | Public board endpoint; one employer board | Numeric quota not specified in public posting guide | All currently published postings; no pagination documented | Good employer-board adapter; optional structured compensation |
| SmartRecruiters Posting | Unauthenticated public postings; company identifier required | Customer API docs give 10 requests/sec and 8 concurrent per API user; anonymous/public scope needs confirmation | `limit` max 100, `offset`, `totalFound`; detail request may be needed | Useful but potentially more requests per job |
| USAJOBS Search | API key + registered email; US federal jobs | Reviewed rate guide gives result limits, not a numeric requests/time quota | Default 25, max 500/page; max 10,000/query | Broad federal coverage; applicant eligibility needs separate checks |
| Adzuna Search | Registered app ID/key; country-specific aggregated search | Default 25/min, 250/day, 1,000/week, 2,500/month, all apply | Page in path; `results_per_page`; example 20, maximum not verified | Promising broad search; snippets, quota accounting and terms require care |
| Arbeitnow | Free/no key; Europe, especially Germany; separate UK endpoint | Numeric quota not established from accessible official documentation | Exact page size/pagination not verified; linked Postman docs did not render | Geographic supplement; verify response metadata before implementation |

## Request shapes and evidence

Examples describe requests, not commands executed during research. Credentials
must come from environment configuration and must never enter request logs.

### Jobicy

`GET https://jobicy.com/api/v2/remote-jobs?count=200`

Optional `geo`, `industry`, `tag` (3-50 characters). Taxonomy discovery uses the
same endpoint with `get=locations` or `get=industries`; those calls also need tracking.
Response jobs are in `jobs`. Preserve canonical listing links and source attribution.
Count is a response ceiling, not a promise of 200 new jobs per poll.
Evidence: [official repository and fair-use guidance](https://github.com/Jobicy/remote-jobs-api).

### Greenhouse Job Board

`GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`

Response: `jobs`, `meta.total`. Use job-post `id` for identity; `internal_job_id`
identifies the underlying job and can be null for prospect posts. Discover board
tokens from employers' published careers pages. This API is not a global search
across all Greenhouse employers. Do not reuse Harvest API limits or credentials.
Evidence: [official Job Board API](https://docs.greenhouse.io/job-board.html).

### Lever

`GET https://api.lever.co/v0/postings/{site}?mode=json&skip=0&limit=100`

100 is a proposed page size, not a documented maximum. EU host:
`api.eu.lever.co`. Supports location, commitment and team filters. Returns a JSON
list with descriptions and hosted/application URLs. Only published jobs are public.
Evidence: [official Postings API](https://github.com/lever/postings-api).

### Ashby

`GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true`

Board name comes from the published `jobs.ashbyhq.com/{board}` URL. Response has
`apiVersion` and `jobs`, with descriptions, locations and optional compensation.
Respect `isListed` when displaying/discovering public listings; do not expose
unlisted postings. The authenticated `jobPosting.list` API is a different surface.
Evidence: [public Job Postings guide](https://developers.ashbyhq.com/docs/public-job-posting-api).

### SmartRecruiters

`GET https://api.smartrecruiters.com/v1/companies/{company}/postings?destination=PUBLIC&limit=100&offset=0`

Filters include `q`, location, department and `releasedAfter`. List response:
`content`, `offset`, `limit`, `totalFound`. Fetch details by posting ID only where
needed; list entries may omit full descriptions. Keep public access distinct from
authenticated internal postings and the partner publications feed.
Evidence: [list reference](https://developers.smartrecruiters.com/reference/v1listpostings),
[endpoint details](https://developers.smartrecruiters.com/docs/endpoints),
[authentication](https://developers.smartrecruiters.com/docs/authentication),
[throttling scope and headers](https://developers.smartrecruiters.com/docs/customer-overview).

### USAJOBS

`GET https://data.usajobs.gov/api/search?Keyword=software&ResultsPerPage=500&Page=1`

Headers: `Host: data.usajobs.gov`, `User-Agent: <registered email>`,
`Authorization-Key: <secret>`. Search defaults to public announcements; status
jobs require an additional search. Check each listing's hiring eligibility rather
than assuming a keyword match means an applicant can apply. Partition oversized
queries meaningfully; do not silently stop at the 10,000-result ceiling.
Evidence: [authentication](https://developer.usajobs.gov/guides/authentication),
[search tutorial](https://developer.usajobs.gov/tutorials/search-jobs),
[result limits](https://developer.usajobs.gov/guides/rate-limiting).

### Adzuna

`GET https://api.adzuna.com/v1/api/jobs/us/search/1?app_id=<id>&app_key=<secret>&results_per_page=20&what=software`

Country and page are path components. Filters include `where`, salary and contract
type. Response descriptions are snippets, not full job descriptions. Preserve
redirect URLs and distinguish predicted salaries. Personal research is a listed
permitted use; broader ongoing commercial/organizational uses may require consent
or licensing. Attribution obligations apply to published data. Verify approved
account quotas and page maximum before enabling.
Evidence: [search examples](https://developer.adzuna.com/docs/search),
[default quotas and usage terms](https://developer.adzuna.com/docs/terms_of_service).

### Arbeitnow

`GET https://www.arbeitnow.com/api/job-board-api`

Optional documented `visa_sponsorship=true|false`. UK counterpart:
`https://www.arbeitnow.co.uk/api/job-board-api`. Official article describes a
multi-source ATS feed, remote flag, and separate paid tailored access. Do not
assume third-party directories' page caps, rate limits or extra query parameters.
Backlink to Arbeitnow is required by its API terms.
Evidence: [provider article](https://www.arbeitnow.com/blog/job-board-api),
[linked Postman documentation, rendering unresolved](https://documenter.getpostman.com/view/18545278/UVJbJdKh),
[API terms](https://www.arbeitnow.com/terms).

## Proposed collection approach (our policy, not provider limits)

1. Add Jobicy as the next broad-feed adapter, initially four checks/day. Its larger
   response ceiling is useful, but measure new eligible jobs rather than raw volume.
2. Add Greenhouse, then Ashby/Lever, using an explicit inventory of employer career
   boards. Start with 10-20 relevant employers and twice-daily board refreshes.
   Board discovery is necessary work; these APIs do not search every employer.
3. Evaluate Adzuna and USAJOBS after credentials and geographic/eligibility fit are
   settled. Keep Arbeitnow as a geography-dependent supplement.
4. For unknown read quotas, start serially, at most one provider request every
   five seconds, with bounded daily request/page budgets and backoff on 429/503.
   This is a conservative starting policy, not a guarantee of provider acceptance.
   Do not automatically follow unlimited pages or perform immediate error retries.

## Required scaling work in this repository

- Separate board refresh cadence from provider/account/IP request budgets. The
  current single interval shared by adapter type would serialize all employer
  boards behind one refresh interval; it cannot represent Adzuna's four windows.
- Reserve and ledger every page, detail, taxonomy and retry request. Link each to
  its ingestion run; stop/defer when the budget is exhausted. Bound page counts and
  handle partial runs explicitly instead of reporting an incomplete crawl as full.
- Record sanitized query/page identity and response count/total metadata. Current
  attempt records save a base endpoint, but not enough to audit individual pages.
- Separate provider job identity from collector-instance identity and retain
  provenance. Expect overlap between aggregators and direct employer boards.
- Track last complete board refresh and updates/closures; disappearance from a
  limited latest-results feed does not prove a job closed.
- Measure unique jobs/day, eligible jobs/day, requests per new eligible job, latency,
  stale rate, duplicate rate and API spend. More polls do not create more inventory.
- Keep the same database/request budgets through VPS deployment. No automatic
  response cache is proposed; diagnostic snapshots remain opt-in.

## Follow-up research

Verify numeric public GET quotas where unpublished, Adzuna maximum page size,
Arbeitnow pagination, and anonymous SmartRecruiters throttling scope. Confirm
current terms before each adapter is enabled. Candidate future research includes
Reed, Jooble, The Muse, Findwork and national public employment feeds; these are
not yet verified or recommended integrations in this catalog.
