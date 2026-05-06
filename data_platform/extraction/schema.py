import hashlib
import pandas as pd
import os
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy import desc
from sqlalchemy.orm import Session
from data_platform.database.models import DataAsset, SchemaSnapshot, SchemaField, DataSource
from data_platform.extraction.quality import evaluate_quality
from data_platform.transformation.tidier import align

def calculate_file_hash(file_path: str) -> str:
    """Calculate MD5 hash of a file."""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def extract_schema_metadata(asset: DataAsset, nrows: int = 1000, fetch_fresh: bool = True, skip_ade: bool = False) -> Tuple[List[Dict[str, Any]], Optional[pd.DataFrame]]:
    """
    Load data from file or REST API and Extract Schema.
    """
    try:
        source = asset.source
        
        if source.source_type == "file_store":
            file_path = asset.location_ref
            if file_path.lower().endswith('.csv'):
                df = pd.read_csv(file_path, nrows=nrows)
            elif file_path.lower().endswith('.json'):
                try:
                    df = pd.read_json(file_path)
                except ValueError:
                    df = pd.read_json(file_path, lines=True)
                if len(df) > nrows:
                    df = df.head(nrows)
            elif file_path.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg')):
                from data_platform.extraction.document_parser import LandingAIADEClient, InvoiceSchema, UtilityBillSchema, GenericDocumentSchema
                
                client = LandingAIADEClient()
                
                # Choose schema based on filename hint
                filename_low = asset.asset_name.lower()
                if "bill" in filename_low:
                    schema = UtilityBillSchema
                elif "invoice" in filename_low:
                    schema = InvoiceSchema
                else:
                    schema = GenericDocumentSchema

                if skip_ade:
                    # Look for existing extracted CSV
                    base = os.path.basename(file_path).rsplit('.', 1)[0]
                    mvp_dir = Path(__file__).resolve().parent.parent.parent
                    csv_path = mvp_dir / "data" / "extracted" / f"{base}_extracted.csv"
                    if csv_path.exists():
                        print(f"[{asset.asset_name}] Loading existing extraction: {csv_path.name}")
                        df = pd.read_csv(csv_path)
                    else:
                        print(f"[{asset.asset_name}] No cached extraction found, must re-process.")
                        df = client.extract_structured_data(file_path, schema)
                else:
                    df = client.extract_structured_data(file_path, schema)
            else:
                print(f"Unsupported file format for {file_path}")
                return [], None
        
        else:
            return [], None

        df = align(df)
        schema_fields = []
        for index, col_name in enumerate(df.columns):
            dtype_str = str(df[col_name].dtype)
            is_nullable = bool(df[col_name].isnull().any())
            schema_fields.append({
                "field_name": col_name,
                "data_type": dtype_str,
                "nullable": is_nullable,
                "ordinal_position": index + 1
            })
        return schema_fields, df
    except Exception as e:
        print(f"Error extracting schema from {asset.location_ref}: {e}")
        return [], None

def generate_schema_hash(schema_fields: List[Dict[str, Any]]) -> str:
    if not schema_fields:
        return ""
    sorted_fields = sorted([(f["field_name"], f["data_type"], f["nullable"]) for f in schema_fields])
    schema_str = str(sorted_fields)
    return hashlib.md5(schema_str.encode('utf-8')).hexdigest()

def process_schema_for_asset(db: Session, asset: DataAsset, scan_run_id: int, fetch_fresh: bool = True) -> bool:
    is_doc = asset.location_ref.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg'))
    source_hash = None
    if is_doc:
        source_hash = calculate_file_hash(asset.location_ref)
        
    latest_snapshot = db.query(SchemaSnapshot).filter_by(asset_id=asset.asset_id).order_by(desc(SchemaSnapshot.detected_at)).first()
        
    if is_doc and latest_snapshot and latest_snapshot.schema_hash == source_hash:
        base = os.path.basename(asset.location_ref).rsplit('.', 1)[0]
        mvp_dir = Path(__file__).resolve().parent.parent.parent
        csv_path = mvp_dir / "data" / "extracted" / f"{base}_extracted.csv"
        
        if csv_path.exists():
            print(f"[{asset.asset_name}] Source unchanged. Skipping expensive ADE extraction.")
            schema_fields, df_sample = extract_schema_metadata(asset, fetch_fresh=fetch_fresh, skip_ade=True)
            if schema_fields and df_sample is not None:
                evaluate_quality(db, asset, df_sample, schema_fields, scan_run_id)
                return False

    schema_fields, df_sample = extract_schema_metadata(asset, fetch_fresh=fetch_fresh)
    if not schema_fields or df_sample is None:
        print(f"[{asset.asset_name}] No fields extracted or error occurred.")
        return False
        
    current_hash = source_hash if is_doc else generate_schema_hash(schema_fields)
    
    if latest_snapshot and latest_snapshot.schema_hash == current_hash:
        print(f"[{asset.asset_name}] Schema unchanged (Hash matches). Skipping Schema DB insert.")
        evaluate_quality(db, asset, df_sample, schema_fields, scan_run_id)
        return False
        
    print(f"[{asset.asset_name}] Schema change detected or new file.")
    if latest_snapshot:
        baseline_fields = [{"field_name": f.field_name, "data_type": f.data_type, "nullable": f.nullable, "ordinal_position": f.ordinal_position} for f in latest_snapshot.fields]
        evaluate_quality(db, asset, df_sample, baseline_fields, scan_run_id)
    else:
        evaluate_quality(db, asset, df_sample, schema_fields, scan_run_id)

    print(f"[{asset.asset_name}] Saving new schema.")
    inf_method = "landingai-ade" if is_doc else "pandas"
    new_snapshot = SchemaSnapshot(asset_id=asset.asset_id, schema_hash=current_hash, inference_method=inf_method)
    db.add(new_snapshot)
    db.flush()
    
    for field_info in schema_fields:
        field = SchemaField(schema_id=new_snapshot.schema_id, field_name=field_info["field_name"], data_type=field_info["data_type"], nullable=field_info["nullable"], ordinal_position=field_info["ordinal_position"])
        db.add(field)
    db.commit()
    return True

def extract_schemas_for_all_assets(db: Session, scan_run_id: int, fetch_fresh: bool = True):
    try:
        assets = db.query(DataAsset).filter_by(is_active=True).all()
        print(f"Found {len(assets)} active assets to process...")
        for asset in assets:
            process_schema_for_asset(db, asset, scan_run_id, fetch_fresh=fetch_fresh)
    except Exception as e:
        print(f"Error during schema extraction: {e}")
        db.rollback()
