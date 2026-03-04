To keep the new job scraping module seamlessly integrated with your current dashboard, the new developer needs to produce data that directly matches your underlying SQLite database schema (`jobs.db`). The dashboard backend does not use an ingestion API endpoint; instead, it reads directly from several tables in the SQLite database.

At a minimum, the new developer MUST populate the `results` and `runs` tables to ensure jobs appear correctly in the dashboard interface and metrics.

Here is the exact schema and data structures the new developer needs to conform to:

### 1. The `results` Table (The Core Jobs List)

This table powers the main Job listings on the dashboard. Every passed job must be inserted here. 

| Field | Type | Description |
| :--- | :--- | :--- |
| **`id`** | `INTEGER` | Primary key, autoincrements. |
| **`url`** | `TEXT` | **(Required)** The canonical URL of the job posting. |
| **`title`** | `TEXT` | **(Required)** The job title (e.g., "Senior Software Engineer"). |
| **`board`** | `TEXT` | The job board tracking system. The dashboard expects one of: `greenhouse`, `lever`, `ashby`, `workday`, `bamboohr`, `icims`, `smartrecruiters`, `jobvite`, `simplyhired`, `linkedin`, or `unknown`. |
| **`seniority`** | `TEXT` | The seniority extracted. Expected values: `junior`, `mid`, `senior`, `staff`, `principal`, `lead`, `manager`, `director`, or `unknown`. |
| **`experience_years`** | `INTEGER` | Required years of experience parsed from the posting (e.g., `5`). |
| **`salary_k`** | `INTEGER` | Maximum or median expected salary in thousands (e.g., `150`). |
| **`score`** | `INTEGER` | An integer rating/score assigned to the job match quality. |
| **`decision`** | `TEXT` | Usually the LLM or filter logic's final string description/reasoning. |
| **`snippet`** | `TEXT` | A short summary snippet to display in the UI cards. |
| **`query`** | `TEXT` | The original search query that found the job. |
| **`jd_text`** | `TEXT` | The full, parsed text of the job description. |
| **`filter_verdicts`** | `TEXT` | A **JSON-encoded array** of dictionaries auditing the filter pipeline. Each object must look like: `{"stage": "string", "passed": boolean, "reason": "string"}`. |
| **`run_id`** | `TEXT` | **(Required)** A unique string linking to the `runs` table (e.g., `uuid4`). |
| **`created_at`** | `TEXT` | **(Required)** ISO 8601 formatted UTC timestamp of when it was stored. |

### 2. The `runs` Table (Dashboard Runs & Metrics)

The dashboard heavily relies on "Runs" to track operations, calculate uniqueness, and build health charts on the overview page. The scraper must track its own lifecycle here.

| Field | Type | Description |
| :--- | :--- | :--- |
| **`run_id`** | `TEXT` | Primary key. Matches the `run_id` inserted in `results`. |
| **`started_at`** | `TEXT` | **(Required)** ISO 8601 formatted UTC timestamp representing when the pipeline began. |
| **`completed_at`** | `TEXT` | ISO 8601 formatted UTC timestamp representing completion time. |
| **`elapsed`** | `REAL` | Total runtime in seconds (e.g., `12.5`). |
| **`raw_count`** | `INTEGER` | Number of raw jobs found before deduplication. |
| **`dedup_count`** | `INTEGER` | Number of jobs dropped due to duplication. |
| **`filtered_count`** | `INTEGER` | Number of jobs dropped via filters (e.g., LLM, title matching). |
| **`error_count`** | `INTEGER` | Total number of errors encountered. |
| **`errors`** | `TEXT` | A **JSON-encoded array** of strings detailing any logged exception messages. |
| **`status`** | `TEXT` | Expected values are: `'running'`, `'complete'`, or `'failed'`. |

---

### Additional Tables for Full Consistency (Optional but Recommended)

To ensure the "Rejected Jobs" panel and deduplication stats accurately reflect the new pipeline's footprint, the developer should populate these tables as well:

**3. `rejected` Table**
Tracks jobs that failed the filtering stages. Allows the user to manually approve them later from the dashboard.
* **Fields needed:** `url`, `title`, `board`, `snippet`, `rejection_stage` (e.g., 'llm_eval'), `rejection_reason`, `filter_verdicts` (JSON array), `run_id`, `created_at`.

**4. `seen_urls` Table**
Tracks history for database deduplication ratios and global duplicate tracking.
* **Fields needed:** `url` (PK), `first_seen` (ISO text), `last_seen` (ISO text). 

### Actionable Advice for the Developer

Tell the new developer that there is no HTTP POST ingestion API. Instead, they should build their pipeline, and at the persistence layer, establish a standard SQLite connection to `jobs.db` and insert rows closely matching the above parameters to achieve 1:1 parity with the existing SearXNG logic. All array fields (`filter_verdicts`, `errors`) must be valid JSON-serialized strings.
