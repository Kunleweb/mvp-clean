from data_platform.database.connection import SessionLocal
from data_platform.database import models
from sqlalchemy import func

def check_assets():
    db = SessionLocal()
    try:
        assets = db.query(
            models.DataAsset.asset_id,
            models.DataAsset.asset_name,
            models.DataAsset.is_active,
            func.count(models.DataQualityResult.result_id).label("result_count")
        ).outerjoin(models.DataQualityResult, models.DataAsset.asset_id == models.DataQualityResult.asset_id)\
         .group_by(models.DataAsset.asset_id).all()
        
        print(f"{'ID':<5} | {'Name':<40} | {'Active':<10} | {'Results':<10}")
        print("-" * 75)
        for a in assets:
            status = "ACTIVE" if a.is_active else "INACTIVE"
            warning = " !!!" if a.result_count > 1 else ""
            print(f"{a.asset_id:<5} | {a.asset_name:<40} | {status:<10} | {a.result_count:<10}{warning}")
            
    finally:
        db.close()

if __name__ == "__main__":
    check_assets()
