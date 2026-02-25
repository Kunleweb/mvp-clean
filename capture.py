import os
from pathlib import Path
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from database import SessionLocal
from models import DataSource, DataAsset

def register_source_if_not_exists(name: str = "Local CSV Folder", connection_ref: str = "./data"):
    """
    Registers the primary data source folder if it does not already exist in the DB.
    """
    db = SessionLocal()
    try:
        # Check if source already exists
        source = db.query(DataSource).filter_by(connection_ref=connection_ref).first()
        
        if not source:
            source = DataSource(
                name=name,
                source_type="file_store",
                connection_ref=connection_ref,
                scan_enabled=True
            )
            db.add(source)
            db.commit()
            db.refresh(source)
            print(f"Registered new source '{name}' at '{connection_ref}' with ID {source.source_id}")
        else:
            print(f"Source '{name}' already exists with ID {source.source_id}")
            
        return source
    except Exception as e:
        db.rollback()
        print(f"Error registering source: {e}")
        raise
    finally:
        db.close()

def scan_sources():
    """
    Scans all enabled data sources for CSV files and registers them as data assets.
    """
    db = SessionLocal()
    try:
        # Query all enabled sources
        sources = db.query(DataSource).filter_by(scan_enabled=True).all()
        
        if not sources:
            print("No enabled data sources found.")
            return

        print(f"Scanning {len(sources)} enabled source(s)...")
        
        for source in sources:
            folder_path = Path(source.connection_ref)
            
            if not folder_path.exists() or not folder_path.is_dir():
                print(f"Warning: Source path '{folder_path}' does not exist or is not a directory. Skipping...")
                continue
                
            # Recursively scan using pathlib
            csv_count = 0
            for file_path in folder_path.rglob("*.csv"):
                # Register the asset
                asset_name = file_path.name
                location_ref = str(file_path.absolute())
                
                # Check if asset already exists
                existing_asset = db.query(DataAsset).filter_by(
                    source_id=source.source_id, 
                    location_ref=location_ref
                ).first()
                
                if existing_asset:
                    # Update last_seen_at
                    existing_asset.last_seen_at = datetime.utcnow()
                else:
                    # Create new asset
                    new_asset = DataAsset(
                        source_id=source.source_id,
                        asset_name=asset_name,
                        location_ref=location_ref,
                        format="csv"
                    )
                    db.add(new_asset)
                    print(f"Discovered new CSV file: {asset_name} at {location_ref}")
                
                csv_count += 1
                
            print(f"Finished scanning source '{source.name}'. Found {csv_count} CSV files.")
            
        # Commit all new assets and updates at the end
        db.commit()
        
    except Exception as e:
        db.rollback()
        print(f"Error scanning sources: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    # Test registering the source and scanning
    register_source_if_not_exists()
    scan_sources()

