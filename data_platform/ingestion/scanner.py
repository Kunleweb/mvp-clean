import os
import json
import queue
import requests
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from data_platform.database.models import DataSource, DataAsset, DataOwner, AssetOwner
from data_platform.config import DATA_SOURCE_PATH, DATA_SOURCE_NAME, RAPIDAPI_KEY, ALPHA_VANTAGE_HOST

API_CACHE_DIR = Path(DATA_SOURCE_PATH) / "api_cache"

# Thread-safe queue: background watchdog thread puts new asset IDs here,
# main thread drains it and calls prompt_for_ownership safely.
_governance_queue: queue.Queue = queue.Queue()

def register_source_if_not_exists(db: Session, name: str = DATA_SOURCE_NAME, connection_ref: str = DATA_SOURCE_PATH):
    """
    Registers the primary data source folder if it does not already exist in the DB.
    """
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

def register_asset(db: Session, source: DataSource, asset_name: str, location_ref: str, file_format: str) -> int:
    """
    Registers or updates a data asset. When a brand-new asset is found,
    its ID is pushed onto _governance_queue so the main thread can prompt
    for ownership details (input() cannot be called from watchdog's thread).
    """
    existing_asset = db.query(DataAsset).filter_by(
        source_id=source.source_id, 
        location_ref=location_ref
    ).first()
    
    if existing_asset:
        was_inactive = not existing_asset.is_active
        existing_asset.last_seen_at = datetime.now(timezone.utc)
        existing_asset.is_active = True
        db.commit()
        if was_inactive:
            print(f"[!] Reactivated previously deleted dataset: {asset_name}")
            # Check if it still lacks an owner and re-queue if so
            has_owner = db.query(AssetOwner).filter_by(asset_id=existing_asset.asset_id).first() is not None
            if not has_owner:
                _governance_queue.put(existing_asset.asset_id)
        return existing_asset.asset_id
    else:
        new_asset = DataAsset(
            source_id=source.source_id,
            asset_name=asset_name,
            location_ref=location_ref,
            format=file_format
        )
        db.add(new_asset)
        db.commit()
        print(f"[+] New dataset discovered: {asset_name}  (awaiting governance — see terminal prompt)")
        # Signal the main thread to run governance for this asset
        _governance_queue.put(new_asset.asset_id)
        return new_asset.asset_id

def drain_governance_queue(db: Session):
    """
    Called from the MAIN THREAD after each pipeline run.
    Drains any new asset IDs from _governance_queue and prompts for ownership.
    This is safe because input() is only ever called here, on the main thread.
    """
    pending = []
    while not _governance_queue.empty():
        try:
            pending.append(_governance_queue.get_nowait())
        except queue.Empty:
            break
    
    if not pending:
        return
    
    print(f"\n[Governance] {len(pending)} new dataset(s) require ownership details:")
    for asset_id in pending:
        asset = db.query(DataAsset).filter_by(asset_id=asset_id).first()
        if asset:
            prompt_for_ownership(db, asset.asset_id, asset.asset_name)

def fetch_api_data(asset: DataAsset) -> dict:
    """
    Fetches JSON data from a REST API asset.
    Uses the cached file in ./data/api_cache/ if it exists and the user chose not to refresh.
    The decision is made once at startup via prompt_api_refresh().
    """
    if "rapidapi.com" in asset.location_ref:
        headers = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": ALPHA_VANTAGE_HOST
        }
        response = requests.get(asset.location_ref, headers=headers)
        response.raise_for_status()
        return response.json()
    
    # Generic REST API fetch
    response = requests.get(asset.location_ref)
    response.raise_for_status()
    return response.json()

def prompt_api_refresh() -> bool:
    """
    Called once at startup (main thread). Checks if any cached API JSON files exist.
    If so, asks the user whether to fetch fresh data or reuse the cache.
    Returns True if the user wants fresh data, False to use cache.
    """
    API_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_files = list(API_CACHE_DIR.glob("*_api.json"))
    
    if not cached_files:
        print("[API Cache] No cached API data found. Will fetch fresh data from API.")
        return True
    
    print("\n[API Cache] Cached API data found:")
    for f in cached_files:
        size_kb = f.stat().st_size / 1024
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  - {f.name} ({size_kb:.1f} KB, last fetched: {mtime})")
    
    choice = input("\nFetch FRESH data from API (overwrites cache)? [y/N]: ").strip().lower()
    return choice == "y"

def check_unowned_assets(db: Session):
    """
    Called once at startup from the main thread.
    Finds any active assets with no owner and prompts for governance details.
    This is the safe way to run input() — never from a watchdog background thread.
    """
    unowned = db.query(DataAsset).filter(
        DataAsset.is_active == True,
        ~DataAsset.asset_id.in_(
            db.query(AssetOwner.asset_id)
        )
    ).all()
    
    if not unowned:
        return
    
    print(f"\n[Governance] Found {len(unowned)} asset(s) with no owner assigned:")
    for asset in unowned:
        print(f"  - {asset.asset_name}")
        prompt_for_ownership(db, asset.asset_id, asset.asset_name)

def prompt_for_ownership(db: Session, asset_id: int, asset_name: str):
    """
    Prompt the user for dataset ownership information dynamically.
    """
    print("--- Dataset Governance ---")
    owner_name = input(f"Enter Owner Name for {asset_name} (or press Enter to skip): ").strip()
    
    if owner_name:
        owner_email = input(f"Enter Owner Email for {owner_name}: ").strip()
        
        # Check if owner already maps to our DB
        owner = db.query(DataOwner).filter_by(name=owner_name).first()
        if not owner:
            owner = DataOwner(name=owner_name, email=owner_email)
            db.add(owner)
            db.commit() # Commit immediately
            print(f"Created new governance owner: {owner_name}")
        
        ownership_type = input("Enter Ownership Type (e.g., technical, business) [default: business]: ").strip()
        if not ownership_type:
            ownership_type = "business"
            
        asset_owner = AssetOwner(
            asset_id=asset_id,
            owner_id=owner.owner_id,
            ownership_type=ownership_type
        )
        db.add(asset_owner)
        db.commit() # Commit the relationship
        print(f"Successfully linked owner {owner_name} to asset {asset_name}.")
    else:
        print("Skipping owner assignment.")

def scan_sources(db: Session):
    """
    Scans all enabled data sources for CSV and JSON files and registers them as data assets.
    """
    try:
        # Query all enabled sources
        sources = db.query(DataSource).filter_by(scan_enabled=True).all()
        
        if not sources:
            print("No enabled data sources found.")
            return

        print(f"Scanning {len(sources)} enabled source(s)...")
        
        for source in sources:
            if source.source_type == "file_store":
                folder_path = Path(source.connection_ref)
                
                if not folder_path.exists() or not folder_path.is_dir():
                    print(f"Warning: Source path '{folder_path}' does not exist or is not a directory. Skipping...")
                    continue
                    
                # Track active assets we find to detect deletions later
                found_asset_ids = []
                
                # Recursively scan using pathlib for supported extensions
                supported_extensions = ['.csv', '.json', '.pdf', '.png', '.jpg', '.jpeg']
                file_count = 0
                
                # Find all files and filter by our extensions
                for file_path in folder_path.rglob("*.*"):
                    # Skip the api_cache and extracted directories — these are managed results or cache
                    full_path_str = str(file_path.resolve()).lower()
                    if any(p in full_path_str for p in ["api_cache", "extracted"]):
                        continue
                    if file_path.suffix.lower() not in supported_extensions:
                        continue
                        
                    # Register the asset
                    asset_name = file_path.name
                    location_ref = str(file_path.resolve())
                    file_format = file_path.suffix.lower().lstrip('.')
                    
                    found_asset_ids.append(register_asset(db, source, asset_name, location_ref, file_format))
                    file_count += 1
                    
                print(f"Finished scanning file source '{source.name}'. Found {file_count} dataset files.")
            
            elif source.source_type == "rest_api":
                # For REST APIs like Alpha Vantage, "discovery" might be a predefined list of endpoints/symbols
                print(f"Scanning REST API source '{source.name}'...")
                found_asset_ids = []
                
                if "Alpha Vantage" in source.name:
                    # Specific discovery logic for Alpha Vantage
                    symbols = ["MSFT", "AAPL", "GOOGL"]
                    for symbol in symbols:
                        asset_name = f"{symbol} Stock Data"
                        # We store the symbol as part of the location_ref or just the full URL
                        location_ref = f"{source.connection_ref}?function=TIME_SERIES_DAILY&symbol={symbol}&outputsize=compact&datatype=json"
                        
                        found_asset_ids.append(register_asset(db, source, asset_name, location_ref, "json"))
                
                print(f"Finished scanning API source '{source.name}'. Registered {len(found_asset_ids)} virtual assets.")
            
            # --- Missing Asset Detection (Soft Delete) ---
            missing_assets_query = db.query(DataAsset).filter(
                DataAsset.source_id == source.source_id,
                DataAsset.is_active == True,
            )
            
            if found_asset_ids:
                missing_assets_query = missing_assets_query.filter(~DataAsset.asset_id.in_(found_asset_ids))
                
            missing_assets = missing_assets_query.all()
            
            for missing_asset in missing_assets:
                print(f"[!] Dataset missing and marked as inactive: {missing_asset.asset_name}")
                missing_asset.is_active = False

        # Commit all new assets, updates, and soft-deletes at the end
        db.commit()
        
    except Exception as e:
        db.rollback()
        print(f"Error scanning sources: {e}")
        raise
