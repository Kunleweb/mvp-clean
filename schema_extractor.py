import hashlib
import pandas as pd
from typing import List, Dict, Any
from sqlalchemy import desc
from database import SessionLocal
from models import DataAsset, SchemaSnapshot, SchemaField

def extract_schema_metadata(file_path: str, nrows: int = 1000) -> List[Dict[str, Any]]:
    """
    Step 8 & 9: Load CSV with Sampling & Extract Schema.
    Reads up to 'nrows' from a CSV file and extracts schema details for each column.
    """
    try:
        # Load the CSV
        df = pd.read_csv(file_path, nrows=nrows)
        
        schema_fields = []
        for index, col_name in enumerate(df.columns):
            # Extract metadata
            dtype_str = str(df[col_name].dtype)
            is_nullable = bool(df[col_name].isnull().any())
            
            schema_fields.append({
                "field_name": col_name,
                "data_type": dtype_str,
                "nullable": is_nullable,
                "ordinal_position": index + 1
            })
            
        return schema_fields
        
    except Exception as e:
        print(f"Error extracting schema from {file_path}: {e}")
        return []

def generate_schema_hash(schema_fields: List[Dict[str, Any]]) -> str:
    """
    Step 10: Generate Schema Hash.
    Creates a deterministic MD5 hash string based on the column structures.
    """
    if not schema_fields:
        return ""
        
    # Create sorted structure
    # (column_name, data_type, nullable)
    sorted_fields = sorted([
        (f["field_name"], f["data_type"], f["nullable"]) 
        for f in schema_fields
    ])
    
    # Convert to string representation
    schema_str = str(sorted_fields)
    
    # Hash using md5
    schema_hash = hashlib.md5(schema_str.encode('utf-8')).hexdigest()
    return schema_hash

def process_schema_for_asset(db, asset) -> bool:
    """
    Step 11: Check for Existing Schema Version and Insert if necessary.
    Returns True if a new schema was inserted, False otherwise.
    """
    # 1. Extract schema from file
    schema_fields = extract_schema_metadata(asset.location_ref)
    if not schema_fields:
        print(f"[{asset.asset_name}] No fields extracted or error occurred.")
        return False
        
    # 2. Generate Hash
    current_hash = generate_schema_hash(schema_fields)
    
    # 3. Query latest schema_snapshot for this asset
    latest_snapshot = db.query(SchemaSnapshot) \
        .filter_by(asset_id=asset.asset_id) \
        .order_by(desc(SchemaSnapshot.detected_at)) \
        .first()
        
    # 4. Compare hash
    if latest_snapshot and latest_snapshot.schema_hash == current_hash:
        print(f"[{asset.asset_name}] Schema unchanged (Hash matches). Skipping.")
        return False
        
    # 5. Insert new Schema Snapshot
    print(f"[{asset.asset_name}] Schema change detected or new file. Saving new schema.")
    new_snapshot = SchemaSnapshot(
        asset_id=asset.asset_id,
        schema_hash=current_hash,
        inference_method="pandas"
    )
    db.add(new_snapshot)
    db.flush() # get schema_id
    
    # 6. Insert Schema Fields
    for field_info in schema_fields:
        field = SchemaField(
            schema_id=new_snapshot.schema_id,
            field_name=field_info["field_name"],
            data_type=field_info["data_type"],
            nullable=field_info["nullable"],
            ordinal_position=field_info["ordinal_position"]
        )
        db.add(field)
        
    db.commit()
    return True

def extract_schemas_for_all_assets():
    """
    Loops through all known data assets and processes their schemas.
    """
    db = SessionLocal()
    try:
        assets = db.query(DataAsset).all()
        print(f"Found {len(assets)} assets to process...")
        for asset in assets:
            process_schema_for_asset(db, asset)
    finally:
        db.close()

if __name__ == "__main__":
    print("--- Starting Schema Extraction Stage ---")
    extract_schemas_for_all_assets()

