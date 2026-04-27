import pandas as pd
from data_platform.database.connection import SessionLocal
from data_platform.database import models
from data_platform.extraction.quality import evaluate_quality
from data_platform.extraction.schema import extract_schema_metadata
import os
import json

def test_type_logic():
    db = SessionLocal()
    file_path = "scratch/test_types.csv"
    
    try:
        # 1. Create a dummy asset
        source = db.query(models.DataSource).filter_by(name="Test Source").first()
        if not source:
            source = models.DataSource(name="Test Source", connection_ref="local")
            db.add(source)
            db.commit()
            db.refresh(source)
            
        asset = models.DataAsset(
            source_id=source.source_id,
            asset_name="test_types.csv",
            location_ref=file_path,
            format="csv"
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        
        scan_run = models.ScanRun(status="testing_types")
        db.add(scan_run)
        db.commit()
        db.refresh(scan_run)
        
        # 2. Extract schema
        print(f"--- Step 1: Extracting Schema from {file_path} ---")
        # We manually simulate the field mapping to trigger the rules
        # user_id matches .*id.* -> int64
        # user_name matches .*name.* -> string
        # price matches .*price.* -> float64
        
        schema_fields, df = extract_schema_metadata(asset)
        print("Inferred Schema Fields:")
        for field in schema_fields:
            print(f"Field: {field['field_name']}, Type: {field['data_type']}")
            
        # 3. Evaluate Quality
        print(f"\n--- Step 2: Evaluating Quality ---")
        evaluate_quality(db, asset, df, schema_fields, scan_run.scan_run_id)
        
        # 4. Check results in DB
        result = db.query(models.DataQualityResult).filter_by(asset_id=asset.asset_id).first()
        print(f"\n--- Results in Database ---")
        print(f"Score: {result.score}%")
        
        extras = json.loads(result.detailed_results_json)
        print("\nFailed Rules:")
        for fail in extras.get("failed_expectations", []):
            # Check for type or expectation_type
            etype = fail.get("expectation_config", {}).get("type") or fail.get("expectation_config", {}).get("expectation_type")
            col = fail.get("expectation_config", {}).get("kwargs", {}).get("column")
            print(f"- {col}: {etype}")
            
    finally:
        db.close()

if __name__ == "__main__":
    test_type_logic()
