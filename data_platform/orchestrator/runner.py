import time
import os
import threading
from datetime import datetime, timezone
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from data_platform.database.connection import Base, engine, SessionLocal
from data_platform.database.models import ScanRun, DataAsset, AssetOwner, AssetRevision
from data_platform.ingestion.scanner import (
    register_source_if_not_exists, scan_sources,
    prompt_api_refresh, prompt_for_ownership
)
from data_platform.extraction.schema import extract_schemas_for_all_assets
from data_platform.config import DATA_SOURCE_PATH

# ── Shared state ──────────────────────────────────────────────────────────────
# The watchdog thread writes to these; the main thread reads them.
_trigger_lock   = threading.Lock()
_triggered_file = None    # Path of the file that was saved (for audit prompt)
_pipeline_event = threading.Event()
# ─────────────────────────────────────────────────────────────────────────────


def init_db():
    """Initializes the SQLite Database and creates tables if they don't exist."""
    print("--- Initializing Database ---")
    Base.metadata.create_all(engine)


def run_governance(db):
    """
    Prompts for ownership of ANY active asset that has no owner yet.
    Called from the MAIN THREAD after every pipeline run.
    """
    unowned = db.query(DataAsset).filter(
        DataAsset.is_active == True,
        ~DataAsset.asset_id.in_(db.query(AssetOwner.asset_id))
    ).all()

    if not unowned:
        return

    print(f"\n[Governance] {len(unowned)} dataset(s) have no owner assigned:")
    for asset in unowned:
        print(f"  → {asset.asset_name}")
        prompt_for_ownership(db, asset.asset_id, asset.asset_name)


def prompt_edit_author(file_path: str, db, scan_run_id: int):
    """
    Asks who made the edit and saves an AssetRevision record.
    Called from the MAIN THREAD before running the watchdog-triggered pipeline.
    """
    print(f"\n[Edit Audit] File saved: {file_path}")
    editor = input("  Who made this edit? (Name — press Enter to skip): ").strip()
    if not editor:
        print("  Skipping edit audit.")
        return

    note = input("  Edit note (optional — press Enter to skip): ").strip()

    rev = AssetRevision(
        scan_run_id=scan_run_id,
        edited_by=editor,
        edit_note=note or None,
        file_path=file_path,
    )
    db.add(rev)
    db.commit()
    print(f"  ✓ Recorded edit by '{editor}'.")


def execute_pipeline(fetch_fresh: bool = True, triggered_file: str = None):
    """
    Runs the full metadata pipeline.  Always calls run_governance() at the end.
    If triggered_file is given (watchdog run), also calls prompt_edit_author().
    Both stages run on the MAIN THREAD where input() works.
    """
    db = SessionLocal()

    print("\n--- Starting New Scan Run ---")
    run = ScanRun(status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        # ── Edit author prompt (watchdog runs only) ───────────────────────────
        if triggered_file:
            prompt_edit_author(triggered_file, db, run.scan_run_id)

        register_source_if_not_exists(db)
        scan_sources(db)
        extract_schemas_for_all_assets(db, run.scan_run_id, fetch_fresh=fetch_fresh)

        run.status = "completed"
        run.ended_at = datetime.utcnow()
        db.commit()
        print(f"\n--- Pipeline Completed Successfully (Run ID: {run.scan_run_id}) ---")

    except Exception as e:
        run.status = "failed"
        run.ended_at = datetime.now(timezone.utc)
        db.commit()
        print(f"\n--- Pipeline Failed (Run ID: {run.scan_run_id}): {e} ---")
        raise
    finally:
        # Always ask governance after any pipeline run
        run_governance(db)
        db.close()


class FileChangeHandler(FileSystemEventHandler):
    """
    Reacts ONLY to on_modified (file saves).
    Sets a shared event and records the triggering file path.
    Does NOT run the pipeline directly — that's the main thread's job.
    """
    def on_modified(self, event):
        global _triggered_file
        if event.is_directory:
            return
        src = event.src_path
        if not src.lower().endswith(('.csv', '.json')):
            return
        # Normalize path for Windows and check for excluded directories
        norm_path = os.path.normpath(src).lower()
        if any(p in norm_path for p in ["api_cache", "extracted"]):
            print(f"[Watchdog] Ignoring change in excluded directory: {src}")
            return

        print(f"[Watchdog] Triggered by file save: {src}")
        with _trigger_lock:
            _triggered_file = src  # last saved file wins if multiple fire quickly

        _pipeline_event.set()   # wake up the main thread


def run_continuously():
    """
    Main entry point.
    1. Startup prompts  (API cache, governance)
    2. Initial scan
    3. Watchdog loop   — one run per save, with edit-author and governance prompts
    """
    init_db()

    # ── Startup prompts ───────────────────────────────────────────────────────
    fetch_fresh = prompt_api_refresh()
    # ─────────────────────────────────────────────────────────────────────────

    print("\n[Watchdog] Performing initial scan...")
    execute_pipeline(fetch_fresh=fetch_fresh)

    # ── Start watchdog ────────────────────────────────────────────────────────
    event_handler = FileChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, path=DATA_SOURCE_PATH, recursive=True)

    print(f"\n[Watchdog] Watching '{DATA_SOURCE_PATH}' — triggers on file SAVE only.")
    print("[Watchdog] Press Ctrl+C to stop.\n")

    observer.start()
    try:
        while True:
            global _triggered_file  # declare before any read or write

            fired = _pipeline_event.wait(timeout=30)
            if not fired:
                continue

            # Debounce: clear → settle → clear again
            _pipeline_event.clear()
            time.sleep(1.5)
            _pipeline_event.clear()

            with _trigger_lock:
                saved_file = _triggered_file
                _triggered_file = None

            # ── Per-run prompts & Execution ──────────────────────────────────
            fetch_fresh = prompt_api_refresh()
            execute_pipeline(fetch_fresh=fetch_fresh, triggered_file=saved_file)

            # NOTE: We do NOT clear the event here anymore.
            # If a file was saved WHILE the pipeline was running, the event
            # is now SET, and the next loop iteration will pick it up immediately.

    except KeyboardInterrupt:
        print("\n[Watchdog] Stopping observer...")
        observer.stop()
    observer.join()
