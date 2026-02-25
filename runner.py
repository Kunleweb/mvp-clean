from datetime import datetime
from database import Base, engine, SessionLocal
from models import ScanRun
from capture import register_source_if_not_exists, scan_sources
from schema_extractor import extract_schemas_for_all_assets

def init_db():
    """Initializes the SQLite Database and creates tables if they don't exist."""
    print("--- Initializing Database ---")
    Base.metadata.create_all(engine)

def execute_pipeline():
    """
    Step 13: Orchestrate Full Flow
    Runs the entire metadata collection pipeline.
    """
    db = SessionLocal()
    
    # 1. Create scan_run
    print("\n--- Starting New Scan Run ---")
    run = ScanRun(status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    
    try:
        # 2. Register source (Capture Stage)
        register_source_if_not_exists()
        
        # 3. Run capture stage (Find CSVs)
        scan_sources()
        
        # 4. For each discovered asset, run schema extraction
        extract_schemas_for_all_assets()
        
        # 5. Mark scan_run complete
        run.status = "completed"
        run.ended_at = datetime.utcnow()
        db.commit()
        print(f"\n--- Pipeline Completed Successfully (Run ID: {run.scan_run_id}) ---")
        
    except Exception as e:
        # Mark as failed on error
        run.status = "failed"
        run.ended_at = datetime.utcnow()
        db.commit()
        print(f"\n--- Pipeline Failed (Run ID: {run.scan_run_id}): {e} ---")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
    execute_pipeline()

