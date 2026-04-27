# CLEAN Framework: Technical Specification
### Data Observability, Governance, and Automated Extraction

The CLEAN Framework is a specialized system for managing the lifecycle of diverse data assets. It automates the transition from unstructured document formats to validated, governed datasets through a distributed pipeline.

---

## System Architecture

The framework is built on a decoupled architecture using FastAPI for API routing, Celery for task orchestration, and AWS S3 as the primary data lake.

![Architecture](img/1.png)
 
---

## Component Deep Dive

### 1. Ingestion Gateway (`api.py`)
The FastAPI application serves as the entry point for all data and management operations.
*   **File Streaming**: Handles multi-part uploads and streams files directly to AWS S3. It enforces size limits (1MB default) and organizes files by extension into specific S3 prefixes (`uploads/csv/`, `uploads/documents/`, etc.).
*   **External Integration**: Includes adapters for external APIs (e.g., Alpha Vantage). These adapters fetch JSON data, serialize it, and store it in S3 before triggering the processing pipeline.
*   **Job Tracking**: Communicates with the Redis backend via `AsyncResult` to provide real-time status updates to the frontend for background tasks.
*   **Data Explorer API**: Provides endpoints to read raw S3 data, convert it to JSON for the frontend grid, and overwrite S3 objects when manual edits are committed.

### 2. Orchestration Engine (`worker.py`)
A distributed Celery worker that manages the "CLEAN" lifecycle for every ingested file.
*   **State Management**: Updates task metadata at every stage (Downloading, Extracting, Validating) to provide granular feedback in the UI.
*   **Pipeline Routing**: Detects file types. If a document (PDF/Image) is detected, it routes the file to the LandingAI client. If structured (CSV/JSON), it skips directly to alignment.
*   **Transactional Commits**: Records a `ScanRun` for every execution, ensuring that failures are logged and system state remains consistent.

### 3. Extraction & Alignment (`data_platform/extraction/`)
*   **LandingAI ADE Client**: A REST wrapper for LandingAI's vision models. It uses Pydantic schemas (e.g., `InvoiceSchema`, `UtilityBillSchema`) to extract key-value pairs and tabular data from unstructured sources. It also captures raw text as Markdown for full-text search capabilities.
*   **Schema Hashing (`schema.py`)**: Generates an MD5 hash of the field names, types, and nullability. If a file hash (for documents) or a schema hash (for data) matches a previous snapshot, the system avoids redundant, expensive extraction steps.
*   **ALIGN Layer (`tidier.py`)**: A pandas-based transformation module. It performs:
    *   **Date Normalization**: Heuristic-based conversion of string dates to ISO-8601.
    *   **Column Aliasing**: Maps legacy or API-specific field names (e.g., `1. open`) to standardized internal names (`open_price`) using `column_alias.json`.
    *   **Value Mapping**: Semantic normalization using dictionaries to map inconsistent values (e.g., `UK` -> `GB`).

### 4. Validation Engine (`quality.py`)
Powered by **Great Expectations (GX)**, this component performs rigorous data quality checks.
*   **Dynamic Suite Generation**: Instead of static files, the engine generates an expectation suite in memory based on the inferred schema. It automatically adds expectations for column existence, type compliance, and non-null constraints.
*   **Statistical Analysis**: Implements Z-score detection to identify numeric outliers where |z| > 3.
*   **Heuristic Null Detection**: Uses regular expressions to identify "hidden" nulls like whitespace-only strings or placeholders (e.g., "n/a", "null").
*   **Quality Gating**: Assigns a rank (A-D) based on the success ratio and can be configured to "warn" or "reject" assets that fall below a specific threshold.

### 5. Governance & Audit (`models.py`)
The metadata layer is stored in PostgreSQL and tracked via SQLAlchemy models.
*   **Asset Revisioning**: The `AssetRevision` table records every manual override. It stores the editor's name, the reason for the change, and a reference to the specific S3 version created.
*   **Schema Evolution**: The `SchemaSnapshot` and `SchemaField` tables store a versioned history of every asset's structure, allowing the system to detect and report schema drift.

### 6. Frontend Dashboard (`clean-frontend/`)
A Next.js 14 application built with a focus on live observability.
*   **Live Status Polling**: Uses a recursive polling mechanism to track Celery job IDs and update progress bars in real-time.
*   **Interactive Grid**: A custom-built data grid that allows users to edit cells directly. It handles the serialization of edits back to the API.
*   **Visual Analytics**: Uses **Recharts** to visualize quality trends over time and asset health distributions.

---

## Detailed Data Flow

1.  **Ingest**: User uploads `invoice.pdf` via the Dashboard.
2.  **Land**: FastAPI saves the file to `s3://bucket/uploads/documents/` and triggers a Celery task.
3.  **Extract**: Celery downloads the file; LandingAI parses it into a structured CSV.
4.  **Align**: The ALIGN layer renames extracted columns (e.g., `Total Amount` -> `total_amount`) and tidies the data.
5.  **Validate**: Great Expectations runs a suite of 10+ rules. It finds a duplicate row and 2 missing values.
6.  **Persist**: The quality score (80%) and rank (B) are saved to PostgreSQL. The extracted CSV is saved back to S3.
7.  **Govern**: The user sees the rank B, opens the Data Explorer, fixes the missing values, and saves with the note "Manual correction of extraction error."

---

## Data Quality Scoring

The quality scoring model is designed to be transparent and configurable. The composite score is computed as follows:

```
Base Score    = (Passing GX Expectations / Total GX Expectations) × 100
Outlier Penalty = min(outlier_count × 2, 20)          # capped at 20 points
Hidden Null Penalty = min(hidden_null_count × 1, 10)  # capped at 10 points

Final Score = max(Base Score - Outlier Penalty - Hidden Null Penalty, 0)
```


## Technical Stack

*   **Backend**: Python 3.12, FastAPI, Celery, SQLAlchemy, Pandas, Great Expectations.
*   **Frontend**: Next.js 14, TypeScript, TailwindCSS, Recharts, Lucide-React.
*   **Infrastructure**: AWS S3, Redis (Broker), PostgreSQL (Metadata).
*   **Intelligence**: LandingAI ADE (Computer Vision).

---

## Installation and Setup

### Prerequisites

Ensure the following are available on your system before proceeding:

- Python 3.12+
- Node.js 18+ and npm
- Redis Server (running on `localhost:6379`)
- PostgreSQL 15+ database
- AWS account with S3 bucket and IAM credentials (S3 read/write permissions)
- LandingAI API Key (for document extraction)

### Environment Configuration

Copy the example environment file and populate all required values:

```bash
cd mvp
cp .env.example .env
```

The `.env` file requires the following variables:

```env
# AWS Configuration
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key
AWS_DEFAULT_REGION=eu-west-2
S3_BUCKET_NAME=your_bucket_name

# LandingAI Configuration
VISION_AGENT_API_KEY=your_landing_ai_key

# Database Configuration
DATABASE_URL=postgresql://*** 


# External APIs (optional)
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_key 
```

### Backend Setup

```bash
# Navigate to the backend directory
cd mvp

# Install Python dependencies
pip install -r requirements.txt

# Initialise the PostgreSQL database (runs SQLAlchemy migrations)
python -c "from models import Base, engine; Base.metadata.create_all(engine)"

# Start the FastAPI server
python api.py
# API available at http://localhost:8000
# Interactive docs at http://localhost:8000/docs
```

### Worker Setup

The Celery worker must be started in a separate terminal process:

```bash
cd mvp

# Start Celery worker with info-level logging
celery -A worker worker --loglevel=info

# For production, use concurrency flag:
celery -A worker worker --loglevel=info --concurrency=4
```

### Frontend Setup

```bash
cd mvp/clean-frontend

# Install Node dependencies
npm install

# Start the Next.js development server
npm run dev
# Dashboard available at http://localhost:3000

# For production build:
npm run build && npm start
```

---

## Containerized Deployment (Docker)

The CLEAN Framework includes a `docker-compose.yml` configuration for spinning up the core backend infrastructure (API, Worker, and Redis) without manual dependency installation.

### 1. Build and Start Containers
```bash
cd mvp
docker-compose up --build
```
This will:
- Pull and start a **Redis** instance for task brokering.
- Build the **FastAPI** image and start the server on port `8001`.
- Build and start the **Celery Worker** with the necessary environment.

### 2. Accessing the Services
- **API**: `http://localhost:8001`
- **Documentation**: `http://localhost:8001/docs`

> [!NOTE]
> The frontend application currently runs outside of the Docker compose environment. Follow the **Frontend Setup** instructions above to start the dashboard.

---

## Design Decisions

**Why Celery over FastAPI background tasks?**
FastAPI's built-in `BackgroundTasks` runs in the same process as the API server. For compute-heavy operations like AI document extraction, this would block the API under load. Celery workers are fully decoupled and can be scaled independently across multiple machines.

**Why Great Expectations over custom validation?**
Great Expectations provides a rich, standardised vocabulary for data quality rules that aligns directly with industry practice. Its expectation result format includes machine-readable pass/fail metadata that integrates cleanly with the scoring model. Writing equivalent custom validation logic would replicate significant functionality without the ecosystem benefits.

**Why S3 as the data lake rather than direct PostgreSQL storage?**
Raw and processed files can be arbitrarily large and diverse in format. S3 provides cost-effective object storage with versioning, lifecycle policies, and direct streaming support. PostgreSQL is reserved for structured metadata and quality scores only, keeping the database schema stable and query performance predictable.

**Why dynamic expectation suites rather than static files?**
Static expectation files require manual maintenance as schemas evolve. Dynamic generation from inferred schemas ensures validation rules always reflect the current asset structure, reducing operational overhead and eliminating the risk of stale validation configurations.