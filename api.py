import os
import uuid
import boto3
import io
import pandas as pd
import boto3
from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from botocore.exceptions import ClientError
from data_platform.config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AWS_S3_BUCKET
import json
from datetime import datetime
from data_platform.ingest_adapters.alpha_vantage import AlphaVantageAdapter
from celery.result import AsyncResult
from worker import process_uploaded_file, celery_app
from fastapi import Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from data_platform.database.connection import SessionLocal
from data_platform.database import models, schemas
from typing import List, Optional

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Data Platform API",
    description="API for ingesting files and external data to the data lake.",
    version="1.0.0",
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1, # This hides the schemas at the bottom
        "docExpansion": "list",         # Keeps the endpoints collapsed by default for a clean look
        "filter": True                  # Adds a nice search bar in case you add many endpoints later
    }
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
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

MAX_FILE_SIZE = 1024 * 1024  # 1MB

@app.post("/upload", tags=["Ingestion"])
async def upload_file(file: UploadFile = File(...)):
    """
    **Upload a local file** (CSV, JSON, PDF, Image) directly to AWS S3.
    """
    if not s3_client:
        raise HTTPException(status_code=500, detail="S3 client is not configured properly.")
        
    if not AWS_S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 bucket name is not configured.")

    # Validate file size by reading
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {int(MAX_FILE_SIZE/(1024*1024))}MB.")
        
    # Determine the S3 prefix based on file extension
    filename = file.filename
    ext = filename.split('.')[-1].lower() if '.' in filename else ''
    
    if ext in ['csv']:
        prefix = 'uploads/csv/'
    elif ext in ['json']:
        prefix = 'uploads/json/'
    elif ext in ['pdf', 'png', 'jpg', 'jpeg']:
        prefix = 'uploads/documents/'
    else:
        prefix = 'uploads/other/'
        
    # Generate unique filename to avoid overwrites
    unique_filename = f"{uuid.uuid4()}_{filename}"
    s3_key = f"{prefix}{unique_filename}"
    
    try:
        content_type = file.content_type or "application/octet-stream"
        
        s3_client.put_object(
            Bucket=AWS_S3_BUCKET,
            Key=s3_key,
            Body=contents,
            ContentType=content_type
        )
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload to S3: {str(e)}")
        
    # Trigger the background processing task asynchronously
    task = process_uploaded_file.delay(s3_path=s3_key, filename=filename)
        
    return {
        "message": "File uploaded successfully to S3 and queued for background processing",
        "job_id": task.id,
        "filename": filename,
        "s3_path": s3_key,
        "size_bytes": len(contents)
    }

@app.get("/status/{job_id}", tags=["Jobs"])
async def get_job_status(job_id: str):
    """
    **Check the status of a background processing job**
    Returns the current state (e.g., PENDING, PROGRESS, SUCCESS) 
    and any detailed meta status messages from the worker.
    """
    task_result = AsyncResult(job_id, app=celery_app)
    
    response = {
        "job_id": job_id,
        "state": task_result.state,
    }
    
    if task_result.state == 'PENDING':
        response['status'] = 'Waiting in queue...'
    elif task_result.state != 'FAILURE':
        response['status'] = task_result.info.get('status', '') if isinstance(task_result.info, dict) else str(task_result.info)
    else:
        # Something went wrong
        response['status'] = str(task_result.info)
        
    # If done, return the final result
    if task_result.state == 'SUCCESS':
        response['result'] = task_result.result
        
    return response

@app.post("/ingest/api/{source}", tags=["Ingestion"])
async def ingest_from_api(
    source: str, 
    symbol: str = None
):
    """
    **Trigger an API ingestion** (e.g., source = 'alpha-vantage').
    Downloads the data and streams it directly into S3 as a JSON file.
    """
    if not s3_client:
        raise HTTPException(status_code=500, detail="S3 client is not configured properly.")
        
    if not AWS_S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 bucket name is not configured.")

    if source == "alpha-vantage":
        adapter = AlphaVantageAdapter()
        data = await adapter.fetch_data(symbol=symbol)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown API Source: '{source}'")
        
    json_data = json.dumps(data)
    
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    s3_key = f"api-ingest/{adapter.source_name}/{symbol or 'data'}_{timestamp}.json"
    
    try:
        s3_client.put_object(
            Bucket=AWS_S3_BUCKET,
            Key=s3_key,
            Body=json_data.encode('utf-8'),
            ContentType="application/json"
        )
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload API data to S3: {str(e)}")
        
    filename = f"{symbol or 'data'}_{timestamp}.json"
    task = process_uploaded_file.delay(s3_path=s3_key, filename=filename)
    
    return {
        "message": f"Successfully ingested data from {source} and queued for background processing",
        "job_id": task.id,
        "s3_path": s3_key,
        "size_bytes": len(json_data.encode('utf-8'))
    }

# ── Database Dependency ─────────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ── Dashboard API Endpoints ─────────────────────────────────────────────────

def _latest_quality_result_ids_subquery(db: Session):
    """
    One quality result_id per active asset: latest evaluated_at, tie-break max(result_id).
    """
    inner = (
        db.query(
            models.DataQualityResult.asset_id.label("aid"),
            func.max(models.DataQualityResult.evaluated_at).label("max_ev"),
        )
        .join(
            models.DataAsset,
            models.DataAsset.asset_id == models.DataQualityResult.asset_id,
        )
        .filter(models.DataAsset.is_active.is_(True))
        .group_by(models.DataQualityResult.asset_id)
        .subquery()
    )
    return (
        db.query(func.max(models.DataQualityResult.result_id).label("latest_rid"))
        .select_from(models.DataQualityResult)
        .join(
            inner,
            and_(
                models.DataQualityResult.asset_id == inner.c.aid,
                models.DataQualityResult.evaluated_at == inner.c.max_ev,
            ),
        )
        .group_by(models.DataQualityResult.asset_id)
        .subquery()
    )


@app.get("/api/kpis", tags=["Dashboard"], response_model=schemas.MetricKPIs)
async def get_kpis(response: Response, db: Session = Depends(get_db)):
    """
    **Get top-level KPIs** for the dashboard header.
    Includes total assets, average quality score, and rank counts.
    """
    total_assets = db.query(models.DataAsset).filter(models.DataAsset.is_active.is_(True)).count()

    subquery = _latest_quality_result_ids_subquery(db)

    # Average score (latest evaluation per active asset only)
    avg_score = (
        db.query(func.avg(models.DataQualityResult.score))
        .filter(models.DataQualityResult.result_id.in_(subquery))
        .scalar()
        or 0.0
    )

    # Rank A count (latest row per asset is rank A)
    rank_a = (
        db.query(models.DataQualityResult)
        .filter(
            models.DataQualityResult.result_id.in_(subquery),
            models.DataQualityResult.rank == "A",
        )
        .count()
    )

    # "Needs Review" in UI: active assets whose latest run is not rank A (includes B/C/D and ungraded)
    below_gate = (
        db.query(models.DataQualityResult)
        .filter(
            models.DataQualityResult.result_id.in_(subquery),
            models.DataQualityResult.rank != "A",
        )
        .count()
    )

    response.headers["Cache-Control"] = "no-store"
    return {
        "total_assets": total_assets,
        "avg_quality_score": round(float(avg_score), 1),
        "rank_a_count": rank_a,
        "below_gate_count": below_gate,
    }

@app.get("/api/assets/quality", tags=["Dashboard"], response_model=List[schemas.AssetQualitySummary])
async def get_latest_quality(
    response: Response,
    rank: Optional[str] = None,
    source_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """
    **Get the latest quality result for all active assets.**
    Supports filtering by rank and source, plus pagination.
    """
    subquery = _latest_quality_result_ids_subquery(db)

    query = db.query(
        models.DataAsset.asset_id,
        models.DataAsset.asset_name,
        models.DataAsset.format,
        models.DataSource.name.label("source_name"),
        models.DataSource.source_type,
        models.DataQualityResult.score,
        models.DataQualityResult.rank,
        models.DataQualityResult.total_rows,
        models.DataQualityResult.duplicate_rows,
        models.DataQualityResult.evaluated_at
    ).join(models.DataQualityResult, models.DataAsset.asset_id == models.DataQualityResult.asset_id)\
     .join(models.DataSource, models.DataAsset.source_id == models.DataSource.source_id)\
     .filter(models.DataQualityResult.result_id.in_(subquery))

    if rank:
        query = query.filter(models.DataQualityResult.rank == rank)
    if source_id:
        query = query.filter(models.DataAsset.source_id == source_id)

    response.headers["Cache-Control"] = "no-store"
    return query.order_by(models.DataQualityResult.score.asc()).offset(offset).limit(limit).all()

@app.get("/api/assets/{asset_id}/quality/drilldown", tags=["Dashboard"], response_model=schemas.QualityDrilldownResponse)
async def get_quality_drilldown(asset_id: int, db: Session = Depends(get_db)):
    """
    **Get granular data quality results** for a specific asset, parsed from Great Expectations.
    Returns outliers, duplicate counts, and specific expectation failures.
    """
    asset = db.query(models.DataAsset).filter(models.DataAsset.asset_id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    latest_result = db.query(models.DataQualityResult)\
        .filter(models.DataQualityResult.asset_id == asset_id)\
        .order_by(models.DataQualityResult.evaluated_at.desc())\
        .first()

    if not latest_result:
        raise HTTPException(status_code=404, detail="No quality evaluations found for this asset")

    # Safely parse the JSON blob
    parsing_error = False
    try:
        details = json.loads(latest_result.detailed_results_json) if latest_result.detailed_results_json else {}
    except:
        details = {}
        parsing_error = True

    return {
        "asset_id": asset.asset_id,
        "asset_name": asset.asset_name,
        "score": latest_result.score,
        "rank": latest_result.rank,
        "evaluated_at": latest_result.evaluated_at,
        "duplicate_rows": latest_result.duplicate_rows,
        "outliers": details.get("outliers", {}),
        "failed_expectations": details.get("failed_expectations", []),
        "total_failed_count": details.get("total_failed_count", latest_result.failed_rows),
        "parsing_error": parsing_error
    }

@app.get("/api/assets/{asset_id}/history", tags=["Dashboard"], response_model=List[schemas.QualityResultSchema])
async def get_asset_history(
    asset_id: int,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """
    **Get historical quality scores** for a specific asset.
    Used for trend line charts.
    """
    return db.query(models.DataQualityResult)\
             .filter(models.DataQualityResult.asset_id == asset_id)\
             .order_by(models.DataQualityResult.evaluated_at.asc())\
             .limit(limit).all()

@app.get("/api/runs/latest", tags=["Monitoring"], response_model=schemas.ScanRunSchema)
async def get_latest_run(db: Session = Depends(get_db)):
    """
    **Get the latest pipeline scan run** status and timestamps.
    """
    run = db.query(models.ScanRun).order_by(models.ScanRun.scan_run_id.desc()).first()
    if not run:
        raise HTTPException(status_code=404, detail="No scan runs found.")
    return run

@app.get("/api/audit-logs", tags=["Monitoring"], response_model=List[schemas.AuditLogSchema])
async def get_audit_logs(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    # Explicitly select columns to avoid model/DB mismatch issues during transition
    """
    rows = db.query(
        models.AssetRevision.revision_id,
        models.AssetRevision.asset_id,
        models.AssetRevision.edited_by,
        models.AssetRevision.edit_note,
        models.AssetRevision.file_path,
        models.AssetRevision.edited_at
    ).order_by(models.AssetRevision.edited_at.desc())\
     .offset(offset).limit(limit).all()
    
    return [
        {
            "revision_id": r.revision_id,
            "asset_id": r.asset_id,
            "edited_by": r.edited_by,
            "edit_note": r.edit_note,
            "file_path": r.file_path,
            "edited_at": r.edited_at
        } for r in rows
    ]

@app.get("/api/documents/extracted/{filename}", tags=["Documents"])
async def get_extracted_content(filename: str):
    """
    **Read raw extracted document data** from the landing zone.
    """
    file_path = f"data/extracted/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Extracted file not found.")
    
    try:
        with open(file_path, "r") as f:
            content = f.read()
        return {"filename": filename, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")

@app.get("/api/assets/{asset_id}/data", tags=["Data Explorer"], response_model=schemas.DataViewerResponse)
async def preview_asset_data(asset_id: int, limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    """
    **Preview the raw dataset rows** directly from S3.
    """
    if not s3_client:
        raise HTTPException(status_code=500, detail="S3 client not configured.")
        
    asset = db.query(models.DataAsset).filter(models.DataAsset.asset_id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found.")
        
    try:
        response = s3_client.get_object(Bucket=AWS_S3_BUCKET, Key=asset.location_ref)
        content = response['Body'].read()
        
        if str(asset.location_ref).endswith('.json'):
            df = pd.read_json(io.BytesIO(content))
        elif str(asset.location_ref).endswith('.md'):
            # Return empty structure for MD, raw_text will be populated below
            return {
                "columns": [],
                "rows": [],
                "raw_text": content.decode('utf-8', errors='replace')
            }
        else:
            # Assume CSV by default
            df = pd.read_csv(io.BytesIO(content))
            
        # Handle pagination
        df_page = df.iloc[offset:offset+limit]
        
        # Replace NaN/NaT with None so JSON serialization works
        df_page = df_page.where(pd.notnull(df_page), None)
        
        return {
            "columns": df_page.columns.tolist(),
            "rows": df_page.to_dict(orient="records"),
            "raw_text": content.decode('utf-8', errors='replace')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read data from S3: {str(e)}")

@app.put("/api/assets/{asset_id}/data", tags=["Data Explorer"])
async def update_asset_data(
    asset_id: int, 
    payload: schemas.DataEditRequest, 
    db: Session = Depends(get_db)
):
    """
    **Overwrite the raw dataset** in S3 with user edits, logging to Governance, and triggering the validation pipeline.
    """
    if not s3_client:
        raise HTTPException(status_code=500, detail="S3 client not configured.")
        
    asset = db.query(models.DataAsset).filter(models.DataAsset.asset_id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found.")
        
    buffer = io.BytesIO()
    if payload.raw_text is not None:
        buffer.write(payload.raw_text.encode('utf-8', errors='replace'))
    else:
        df = pd.DataFrame(payload.rows)
        # Natively strip out any aggressive artifact columns (e.g., Unnamed: 3) generated by the UI JSON conversion
        # AND strip empty strings ("") which Pandas dynamically interprets back into 'Unnamed: X' upon reloading
        df = df.rename(columns=lambda x: str(x).strip())
        df = df.loc[:, [col for col in df.columns if col and not str(col).startswith('Unnamed')]]

        if str(asset.location_ref).endswith('.json'):
            buffer.write(df.to_json(orient='records').encode('utf-8'))
        else:
            buffer.write(df.to_csv(index=False).encode('utf-8'))
    buffer.seek(0)
    
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    base_name, ext = os.path.splitext(asset.location_ref)
    new_s3_key = f"{base_name}_rev{timestamp}{ext}"
    
    try:
        s3_client.put_object(
            Bucket=AWS_S3_BUCKET,
            Key=new_s3_key,
            Body=buffer.read(),
            ContentType="application/json" if ext == '.json' else "text/csv"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save data to S3: {str(e)}")
        
    old_key = asset.location_ref
    asset.location_ref = new_s3_key
    
    revision = models.AssetRevision(
        edited_by=payload.edited_by,
        edit_note=payload.edit_note,
        file_path=new_s3_key
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    
    filename = new_s3_key.split('/')[-1]
    task = process_uploaded_file.delay(s3_path=new_s3_key, filename=filename)
    
    return {
         "message": "Data overwritten successfully, governance log recorded.",
         "job_id": task.id
    }

@app.delete("/api/assets/{asset_id}", tags=["Data Explorer"])
async def delete_asset(
    asset_id: int, 
    payload: schemas.DataEditRequest, 
    db: Session = Depends(get_db)
):
    """
    **Soft-delete an asset** and log the governance justification.
    """
    print(f"[GOVERNANCE] Attempting to delete asset {asset_id} by {payload.edited_by}")
    asset = db.query(models.DataAsset).filter(models.DataAsset.asset_id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found.")
        
    asset.is_active = False
    
    print(f"[GOVERNANCE] Creating revision record for asset {asset_id}")
    try:
        revision = models.AssetRevision(
            asset_id=asset_id,
            edited_by=payload.edited_by,
            edit_note=f"DELETION: {payload.edit_note}",
            file_path=asset.location_ref
        )
        db.add(revision)
        db.commit()
        print(f"[GOVERNANCE] Successfully committed deletion for {asset_id}")
    except Exception as e:
        db.rollback()
        print(f"[GOVERNANCE] ERROR during deletion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Governance Log Failure: {str(e)}")
    
    return {"message": f"Asset {asset_id} successfully deactivated and logged to governance."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
