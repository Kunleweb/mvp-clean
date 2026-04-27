import pandas as pd
from data_platform.database.connection import SessionLocal
from data_platform.database import models
from data_platform.extraction.quality import evaluate_quality
from data_platform.extraction.schema import extract_schema_metadata
import os

def test_quality_logic():
    db = SessionLocal()
    file_path = "scratch/test_nulls.csv"
    
    try:
        # 1. Create a dummy asset for testing
        source = db.query(models.DataSource).filter_by(name="Test Source").first()
        if not source:
            source = models.DataSource(name="Test Source", connection_ref="local")
            db.add(source)
            db.commit()
            db.refresh(source)
            
        asset = models.DataAsset(
            source_id=source.source_id,
            asset_name="test_nulls.csv",
            location_ref=file_path,
            format="csv"
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        
        scan_run = models.ScanRun(status="testing")
        db.add(scan_run)
        db.commit()
        db.refresh(scan_run)
        
        # 2. Extract schema (will detect nulls)
        print(f"--- Step 1: Extracting Schema from {file_path} ---")
        schema_fields, df = extract_schema_metadata(asset)
        for field in schema_fields:
            print(f"Field: {field['field_name']}, Nullable: {field['nullable']}")
            
        # 3. Evaluate Quality
        print(f"\n--- Step 2: Evaluating Quality (New Logic) ---")
        evaluate_quality(db, asset, df, schema_fields, scan_run.scan_run_id)
        
        # 4. Check results in DB
        result = db.query(models.DataQualityResult).filter_by(asset_id=asset.asset_id).first()
        print(f"\n--- Results in Database ---")
        print(f"Score: {result.score}%")
        print(f"Rank: {result.rank}")
        print(f"Failed Expectations: {result.failed_rows}")
        
    finally:
        # Cleanup
        db.close()

if __name__ == "__main__":
    test_quality_logic()
