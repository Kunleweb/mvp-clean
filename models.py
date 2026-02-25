from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base, engine

class DataSource(Base):
    __tablename__ = "data_source"

    source_id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    source_type = Column(String, default="file_store", nullable=False)
    connection_ref = Column(String, nullable=False)
    scan_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship to data_assets
    assets = relationship("DataAsset", back_populates="source", cascade="all, delete")

class DataAsset(Base):
    __tablename__ = "data_asset"

    asset_id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("data_source.source_id"), nullable=False)
    asset_name = Column(String, nullable=False)
    location_ref = Column(String, nullable=False)
    format = Column(String, default="csv")
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Unique constraint per source and path
    __table_args__ = (UniqueConstraint("source_id", "location_ref", name="uq_source_location"),)

    # Relationships
    source = relationship("DataSource", back_populates="assets")
    snapshots = relationship("SchemaSnapshot", back_populates="asset", cascade="all, delete")

class ScanRun(Base):
    __tablename__ = "scan_run"

    scan_run_id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False)  # e.g., 'running', 'completed', 'failed'

class SchemaSnapshot(Base):
    __tablename__ = "schema_snapshot"

    schema_id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("data_asset.asset_id"), nullable=False)
    detected_at = Column(DateTime, default=datetime.utcnow)
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

if __name__ == "__main__":
    # Create the metadata repository
    print("Creating database and tables...")
    Base.metadata.create_all(engine)
    print("Database `metadata.db` created successfully!")

