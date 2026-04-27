from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# ── Asset & Source ───────────────────────────────────────────────────────────
class DataSourceBase(BaseModel):
    name: str
    source_type: str

class DataAssetBase(BaseModel):
    asset_name: str
    location_ref: str
    format: str

# ── Quality ──────────────────────────────────────────────────────────────────
class QualityResultSchema(BaseModel):
    result_id: int
    asset_id: int
    score: float
    rank: str
    total_rows: int
    failed_rows: int
    duplicate_rows: int
    evaluated_at: datetime

    class Config:
        from_attributes = True

class AssetQualitySummary(BaseModel):
    asset_id: int
    asset_name: str
    format: str
    source_name: str
    source_type: str
    score: float
    rank: str
    total_rows: int
    duplicate_rows: int
    evaluated_at: datetime

class QualityDrilldownResponse(BaseModel):
    asset_id: int
    asset_name: str
    score: float
    rank: str
    evaluated_at: datetime
    duplicate_rows: int
    outliers: dict
    failed_expectations: list
    total_failed_count: int
    parsing_error: bool

# ── System Info ──────────────────────────────────────────────────────────────
class ScanRunSchema(BaseModel):
    scan_run_id: int
    status: str
    started_at: datetime
    ended_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class DataViewerResponse(BaseModel):
    columns: list[str]
    rows: list[dict]
    raw_text: Optional[str] = None

class DataEditRequest(BaseModel):
    edited_by: str
    edit_note: str
    rows: Optional[list[dict]] = None
    raw_text: Optional[str] = None

class MetricKPIs(BaseModel):
    total_assets: int
    avg_quality_score: float
    rank_a_count: int
    below_gate_count: int  # active assets whose latest quality rank is not "A" (UI: Needs Review)

# ── Audit ────────────────────────────────────────────────────────────────────
class AuditLogSchema(BaseModel):
    revision_id: int
    asset_id: Optional[int] = None
    edited_by: str
    edit_note: Optional[str] = None
    file_path: Optional[str] = None
    edited_at: datetime

    class Config:
        from_attributes = True
