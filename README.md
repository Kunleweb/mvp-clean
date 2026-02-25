# Metadata Platform MVP

This is a Minimum Viable Product (MVP) for a larger Data Platform, focusing on metadata extraction and schema drift detection for local CSV files. 

It is designed to run completely locally, using Python, Pandas, and a SQLite database without requiring any heavy third-party servers.

---

## Architecture & File Structure

Here is a breakdown of how each file connects and what it is responsible for within the data pipeline.

### 1. `database.py` (The Connection Layer)
**Purpose:** Sets up the connection to the SQLite database.
* **What it does:** It creates a local file named `metadata.db` in your folder. It uses `SQLAlchemy` to create an `engine` (the connection manager) and a `SessionLocal` factory (to allow other scripts to talk to the database). 
* **Connection:** Every other file imports `SessionLocal` from here whenever it needs to query or save data.

### 2. `models.py` (The Database Schema)
**Purpose:** Defines the structure of the database tables (as Python classes).
* **What it does:** It maps Python objects to SQL tables. 
    * `DataSource`: Represents a folder we are tracking (e.g., `./data`).
    * `DataAsset`: Represents an individual file discovered inside a source (e.g., `customers.csv`).
    * `ScanRun`: Tracks every execution of the pipeline (when it started/ended, did it fail/succeed).
    * `SchemaSnapshot`: Represents a captured version of a file's column layout (including a unique MD5 hash signature).
    * `SchemaField`: Represents an individual column inside a snapshot (e.g., the `id` column, `int64`, non-nullable).
* **Connection:** Imported by `database.py` to create the tables, and by `capture.py`/`schema_extractor.py` to save records.

### 3. `capture.py` (The Discovery Stage)
**Purpose:** Finds data sources and registers new tracked files.
* **What it does:** 
    1. Ensures the target folder (`./data`) is registered in the `data_source` table.
    2. Uses Python's `pathlib` to recursively scan that folder for anything ending in `.csv`.
    3. If it finds a new CSV, it registers it into the `data_asset` table. If it already knows about the CSV, it just updates its `last_seen_at` timestamp.
* **Connection:** Called by `runner.py` at the start of a pipeline run.

### 4. `schema_extractor.py` (The Analysis & Hash Stage)
**Purpose:** Reads the CSV files to understand their schema and detects if the schema has changed.
* **What it does:**
    1. Uses `pandas.read_csv(nrows=1000)` to efficiently read just the first 1,000 rows of an asset.
    2. Extracts the column names, datatypes (e.g., int, float, string), and whether the column has null/empty values.
    3. Creates a **predictable MD5 Hash** out of that schema structure. 
    4. Compares that hash against the most recent hash stored in the database for that file.
    5. **If the hash is new or different**: It saves a new `SchemaSnapshot` and inserts all the new `SchemaField` columns into the database.
    6. **If the hash is exactly the same**: It skips saving, realizing the structure hasn't changed (Drift Detection).
* **Connection:** Called by `runner.py` after the capture stage is finished.

### 5. `runner.py` (The Orchestrator)
**Purpose:** The main entry point that wires all the steps together into a single execution flow.
* **What it does:** 
    1. Initializes the database tables (if they don't exist yet).
    2. Creates a new `ScanRun` record in the database marking the status as "running".
    3. Calls `capture.py` -> `scan_sources()`.
    4. Calls `schema_extractor.py` -> `extract_schemas_for_all_assets()`.
    5. Marks the `ScanRun` record as "completed".
* **Connection:** This is the ONLY file you need to manually run.

### 6. `/data` (The Dummy Source)
**Purpose:** A test folder mimicking an external file store, S3 bucket, or SFTP server. Contains the `.csv` files that the MVP is meant to scan.

---

## How to Test the MVP

To see the MVP in action, especially the **Schema Drift Detection**, follow these steps:

### Scenario 1: Initial Run
1. Open your terminal in the `mvp` folder.
2. Run the application: 
   ```bash
   python runner.py
   ```
3. **What to expect:** You will see the DB initialize, the `data` folder registered, and it will say `Schema change detected or new file. Saving new schema` for every CSV file, because it has never seen them before.

### Scenario 2: Unchanged Run (No Drift)
1. Without changing any CSV files, run the application again:
   ```bash
   python runner.py
   ```
2. **What to expect:** It will quickly scan the files, calculate their MD5 hashes, realize the hashes perfectly match what is already in the database, and output `Schema unchanged (Hash matches). Skipping.` This proves it isn't wasting database space on identical schemas.

### Scenario 3: Schema Drift Detected
1. Open one of the CSV files, for example `customers.csv`.
2. Add a brand new column (e.g., add `,phone_number` to the header, and `,555-1234` to the data row).
3. Save the file.
4. Run the application again:
   ```bash
   python runner.py
   ```
5. **What to expect:** 
   - For the untouched files, it will say `Schema unchanged. Skipping.`
   - For `customers.csv`, it will say `Schema change detected`. It will generate a brand new MD5 hash reflecting the new `phone_number` column and insert a completely new `SchemaSnapshot` into the database, preserving the historical version of the schema as well!

### Scenario 4: Discovering New Files
1. Create a brand new `.csv` file inside the `data` folder (e.g., `employees.csv` with some dummy columns).
2. Run `python runner.py`.
3. **What to expect:** The scanner in `capture.py` will find this new file, register it in `data_asset`, and the schema extractor will immediately profile it.

## Viewing the Results
Because this uses SQLite, the entire database is stored in the `metadata.db` local file. 
You can view the tables, assets, and historical schema snapshots at any time by dragging the `metadata.db` file into [DB Browser for SQLite](https://sqlitebrowser.org/) or by clicking on it using a SQLite extension in VS Code.
