from data_platform.database.connection import SessionLocal
from data_platform.database import models
from sqlalchemy import func
import json

def verify_kpis():
    db = SessionLocal()
    try:
        # Original logic (approximate)
        all_results = db.query(models.DataQualityResult).all()
        if all_results:
            old_avg = sum(r.score for r in all_results) / len(all_results)
            old_rank_a = len([r for r in all_results if r.rank == "A"])
            old_below_gate = len([r for r in all_results if r.score < 70])
        else:
            old_avg, old_rank_a, old_below_gate = 0.0, 0, 0

        # New logic (matching api.py)
        subquery = db.query(
            func.max(models.DataQualityResult.result_id)
        ).join(models.DataAsset).filter(models.DataAsset.is_active == True).group_by(models.DataQualityResult.asset_id).subquery()

        new_avg = db.query(func.avg(models.DataQualityResult.score)).filter(models.DataQualityResult.result_id.in_(subquery)).scalar() or 0.0
        new_rank_a = db.query(models.DataQualityResult).filter(models.DataQualityResult.result_id.in_(subquery), models.DataQualityResult.rank == "A").count()
        new_below_gate = db.query(models.DataQualityResult).filter(models.DataQualityResult.result_id.in_(subquery), models.DataQualityResult.score < 70).count()
        
        print(f"{'Metric':<25} | {'Old (All)':<15} | {'New (Latest/Active)':<20}")
        print("-" * 65)
        print(f"{'Average Score':<25} | {old_avg:<15.1f} | {new_avg:<20.1f}")
        print(f"{'Rank A Count':<25} | {old_rank_a:<15} | {new_rank_a:<20}")
        print(f"{'Below Gate Count':<25} | {old_below_gate:<15} | {new_below_gate:<20}")
            
    finally:
        db.close()

if __name__ == "__main__":
    verify_kpis()
