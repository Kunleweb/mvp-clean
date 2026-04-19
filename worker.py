import os
import time
import ssl
import boto3
from pathlib import Path
from datetime import datetime, timezone
from celery import Celery

from data_platform.config import CELERY_BROKER_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AWS_S3_BUCKET
from data_platform.database.connection import SessionLocal
from data_platform.database.models import DataSource, DataAsset, ScanRun, SchemaSnapshot, SchemaField

from data_platform.extraction.schema import extract_schema_metadata, generate_schema_hash, calculate_file_hash
from data_platform.extraction.quality import evaluate_quality

# Initialize Celery app
celery_app = Celery(
    "data_platform_worker",
    broker=CELERY_BROKER_URL,
    backend=CELERY_BROKER_URL  # We use Redis to store the task results/status too
)

# Initialize Boto3 S3 client
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION
    )
else:
    s3_client = None

# Optional configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Prevent tasks from holding up the worker for hours if LandingAI hangs
    task_soft_time_limit=300, 
    task_time_limit=360
)

# ==========================================
# ASYNC TASKS
# ==========================================

@celery_app.task(bind=True, name="process_uploaded_file")
def process_uploaded_file(self, s3_path: str, filename: str):
    """
    Downloads file from S3, triggers Schema Extraction (and LandingAI for docs),
    runs Great Expectations validations, and saves the results to PostgreSQL.
    """
    self.update_state(state='PROGRESS', meta={'status': 'Starting pipeline...'})
    
    db = SessionLocal()
    scan_run = ScanRun(status="running")
    db.add(scan_run)
    db.commit()
    db.refresh(scan_run)
    
    local_path = None
    
    try:
        self.update_state(state='PROGRESS', meta={'status': f'Downloading {filename} from S3...'})
        local_dir = Path("/tmp/data_platform")
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / filename
        
        if s3_client and AWS_S3_BUCKET:
            s3_client.download_file(AWS_S3_BUCKET, s3_path, str(local_path))
        else:
            raise Exception("S3 Client not configured")
            
        is_doc = filename.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg'))
        
        final_filename = filename
        final_s3_path = s3_path
        source_name = "API Uploads"
        
        if is_doc:
            self.update_state(state='PROGRESS', meta={'status': 'Forwarding to LandingAI ADE for Extraction...'})
            from data_platform.extraction.document_parser import LandingAIADEClient, GenericDocumentSchema, InvoiceSchema, UtilityBillSchema
            client = LandingAIADEClient()
            schema = GenericDocumentSchema
            if "bill" in filename.lower(): schema = UtilityBillSchema
            elif "invoice" in filename.lower(): schema = InvoiceSchema
            
            df_sample = client.extract_structured_data(str(local_path), schema)
            
            self.update_state(state='PROGRESS', meta={'status': 'Uploading extracted tabular data to AWS S3...'})
            import io
            buffer = io.BytesIO()
            buffer.write(df_sample.to_csv(index=False).encode('utf-8'))
            buffer.seek(0)
            
            base_name, _ = os.path.splitext(s3_path) # e.g. uploads/documents/uuid_file
            new_s3_key = f"{base_name}_extracted.csv"
            
            s3_client.put_object(
                Bucket=AWS_S3_BUCKET,
                Key=new_s3_key,
                Body=buffer.read(),
                ContentType="text/csv"
            )
            
            mvp_dir = Path(__file__).resolve().parent
            base_filename = os.path.basename(filename).rsplit('.', 1)[0]
            md_file = mvp_dir / "data" / "extracted" / f"{base_filename}_parsed.md"
            if md_file.exists():
                new_s3_md_key = f"{base_name}_parsed.md"
                with open(md_file, "r", encoding="utf-8") as f:
                    s3_client.put_object(Bucket=AWS_S3_BUCKET, Key=new_s3_md_key, Body=f.read().encode('utf-8'), ContentType="text/markdown")
            
            final_filename = f"{base_filename}_extracted.csv"
            final_s3_path = new_s3_key
            source_name = "LandingAI" # this natively triggers UI separation logic
            
            local_path = mvp_dir / "data" / "extracted" / final_filename

        self.update_state(state='PROGRESS', meta={'status': 'Registering Asset...'})
        source = db.query(DataSource).filter_by(name=source_name).first()
        if not source:
            source = DataSource(name=source_name, source_type="LandingAI" if is_doc else "s3", connection_ref=AWS_S3_BUCKET)
            db.add(source)
            db.commit()
            db.refresh(source)
            
        ext = final_filename.split('.')[-1].lower() if '.' in final_filename else ''
        asset = db.query(DataAsset).filter_by(source_id=source.source_id, location_ref=final_s3_path).first()
        if not asset:
            # We enforce that DataAsset natively registers as the final extracted .csv format
            asset = DataAsset(source_id=source.source_id, asset_name=final_filename, location_ref=final_s3_path, format=ext)
            db.add(asset)
            db.commit()
            db.refresh(asset)
            
        if is_doc:
            md_filename = f"{base_filename}_parsed.md"
            md_s3_key = f"{base_name}_parsed.md"
            md_asset = db.query(DataAsset).filter_by(source_id=source.source_id, location_ref=md_s3_key).first()
            if not md_asset:
                md_asset = DataAsset(source_id=source.source_id, asset_name=md_filename, location_ref=md_s3_key, format="md")
                db.add(md_asset)
                db.commit()
                db.refresh(md_asset)
                
                from data_platform.database.models import DataQualityResult
                md_quality = DataQualityResult(
                    asset_id=md_asset.asset_id,
                    scan_run_id=scan_run.scan_run_id,
                    score=100.0,
                    rank="A",
                    total_rows=1,
                    failed_rows=0,
                    duplicate_rows=0
                )
                db.add(md_quality)
                db.commit()
            
        original_location_ref = asset.location_ref
        original_source_type = asset.source.source_type
        
        asset.location_ref = str(local_path)
        asset.source.source_type = "file_store"
        
        self.update_state(state='PROGRESS', meta={'status': 'Extracting Schema...'})
        schema_fields, df_eval = extract_schema_metadata(asset, fetch_fresh=True, skip_ade=False)
        
        if schema_fields and df_eval is not None:
            self.update_state(state='PROGRESS', meta={'status': 'Running Great Expectations Quality Rules...'})
            
            evaluate_quality(db, asset, df_eval, schema_fields, scan_run.scan_run_id)
            
            self.update_state(state='PROGRESS', meta={'status': 'Saving metadata and relationships to PostgreSQL...'})
            current_hash = calculate_file_hash(str(local_path)) if is_doc else generate_schema_hash(schema_fields)
            inf_method = "landingai-ade" if is_doc else "pandas"
            
            new_snapshot = SchemaSnapshot(asset_id=asset.asset_id, schema_hash=current_hash, inference_method=inf_method)
            db.add(new_snapshot)
            db.flush()
            
            for field_info in schema_fields:
                field = SchemaField(schema_id=new_snapshot.schema_id, field_name=field_info["field_name"], data_type=field_info["data_type"], nullable=field_info["nullable"], ordinal_position=field_info["ordinal_position"])
                db.add(field)
            db.commit()
        else:
            raise Exception("Failed to extract schema or parse data.")
            
        # Restore Asset metadata
        asset.location_ref = original_location_ref
        asset.source.source_type = original_source_type
        db.commit()
        
        if local_path and local_path.exists():
            os.remove(local_path)
            
        scan_run.status = "completed"
        scan_run.ended_at = datetime.now(timezone.utc)
        db.commit()
        
        return {
            "status": "Completed", 
            "message": f"Successfully processed {filename} and stored metrics in PostgreSQL.",
            "s3_path": s3_path
        }
    except Exception as e:
        db.rollback()
        scan_run.status = "failed"
        scan_run.ended_at = datetime.now(timezone.utc)
        db.commit()
        if local_path and local_path.exists():
            os.remove(local_path)
        raise e
    finally:
        db.close()
