from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from data_platform.database.connection import Base

class DataSource(Base):
    __tablename__ = "data_source"

    source_id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    source_type = Column(String, default="file_store", nullable=False)
    connection_ref = Column(String, nullable=False)
    scan_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationship to data_assets
    assets = relationship("DataAsset", back_populates="source", cascade="all, delete")

class DataAsset(Base):
    __tablename__ = "data_asset"

    asset_id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("data_source.source_id"), nullable=False)
    asset_name = Column(String, nullable=False)
    location_ref = Column(String, nullable=False)
    format = Column(String, default="csv")
    is_active = Column(Boolean, default=True)
    last_seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Unique constraint per source and path
    __table_args__ = (UniqueConstraint("source_id", "location_ref", name="uq_source_location"),)

    # Relationships
    source = relationship("DataSource", back_populates="assets")
    snapshots = relationship("SchemaSnapshot", back_populates="asset", cascade="all, delete")
    owners = relationship("AssetOwner", back_populates="asset", cascade="all, delete")

class DataOwner(Base):
    __tablename__ = "data_owner"

    owner_id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)

    owned_assets = relationship("AssetOwner", back_populates="owner", cascade="all, delete")

class AssetOwner(Base):
    __tablename__ = "asset_owner"

    asset_id = Column(Integer, ForeignKey("data_asset.asset_id"), primary_key=True)
    owner_id = Column(Integer, ForeignKey("data_owner.owner_id"), primary_key=True)
    ownership_type = Column(String, default="business")

    # Relationships
    asset = relationship("DataAsset", back_populates="owners")
    owner = relationship("DataOwner", back_populates="owned_assets")

class ScanRun(Base):
    __tablename__ = "scan_run"

    scan_run_id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False)  # e.g., 'running', 'completed', 'failed'

class SchemaSnapshot(Base):
    __tablename__ = "schema_snapshot"

    schema_id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("data_asset.asset_id"), nullable=False)
    detected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    schema_hash = Column(String, nullable=False)
    inference_method = Column(String, default="pandas")

    # Relationships
    asset = relationship("DataAsset", back_populates="snapshots")
    fields = relationship("SchemaField", back_populates="snapshot", cascade="all, delete")

class SchemaField(Base):
    __tablename__ = "schema_field"

    field_id = Column(Integer, primary_key=True)
    schema_id = Column(Integer, ForeignKey("schema_snapshot.schema_id"), nullable=False)
    field_name = Column(String, nullable=False)
    data_type = Column(String, nullable=False)
    nullable = Column(Boolean, default=True)
    ordinal_position = Column(Integer, nullable=False)

    # Relationships
    snapshot = relationship("SchemaSnapshot", back_populates="fields")

class DataQualityResult(Base):
    __tablename__ = "data_quality_result"

    result_id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("data_asset.asset_id"), nullable=False)
    scan_run_id = Column(Integer, ForeignKey("scan_run.scan_run_id"), nullable=False)
    evaluated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    score = Column(Float, nullable=False)  # Example: 95.5
    rank = Column(String, nullable=False)  # Example: 'A', 'B', 'C'
    total_rows = Column(Integer, nullable=False)
    failed_rows = Column(Integer, nullable=False)
    duplicate_rows = Column(Integer, default=0)             # NEW: duplicate row count
    detailed_results_json = Column(String, nullable=True)   # JSON dump of the GX results

    # Relationships
    asset = relationship("DataAsset")
    scan_run = relationship("ScanRun")

class AssetRevision(Base):
    """Records who edited a dataset and when — triggered on every file save."""
    __tablename__ = "asset_revision"

    revision_id  = Column(Integer, primary_key=True)
    asset_id     = Column(Integer, ForeignKey("data_asset.asset_id"), nullable=True)
    scan_run_id  = Column(Integer, ForeignKey("scan_run.scan_run_id"), nullable=True)
    edited_by    = Column(String, nullable=False)
    edit_note    = Column(String, nullable=True)
    file_path    = Column(String, nullable=True)   # Which file triggered the run
    edited_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    asset = relationship("DataAsset")
    scan_run = relationship("ScanRun")
