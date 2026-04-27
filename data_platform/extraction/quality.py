import json
import re
import os
import pandas as pd
import great_expectations as gx
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from data_platform.database.models import DataAsset, DataQualityResult, ScanRun

def load_quality_rules() -> Dict[str, Any]:
    """
    Loads custom quality rules from config file.
    """
    # Relative path from this file to config directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    rules_path = os.path.join(current_dir, "..", "config", "quality_rules.json")
    
    if os.path.exists(rules_path):
        try:
            with open(rules_path, 'r') as f:
                content = json.load(f)
                print(f"[DEBUG] Loaded {len(content.get('rules', []))} rules from {rules_path}")
                return content
        except Exception as e:
            print(f"Error loading quality rules: {e}")
            
    print(f"[DEBUG] Quality rules file NOT FOUND at {rules_path}")
    return {"rules": [], "global_defaults": {}}


import uuid

def generate_generic_suite(context: Any, schema_fields: List[Dict[str, Any]], asset_name: str, unique_id: str) -> str:
    """
    Dynamically generates a an Expectation Suite based on inferred schema.
    """
    suite_name = f"{asset_name}_{unique_id}_generic_suite"
        
    suite = context.suites.add(gx.ExpectationSuite(name=suite_name))

    # Load custom rules
    config = load_quality_rules()
    rules = config.get("rules", [])
    global_defaults = config.get("global_defaults", {})

    for field in schema_fields:
        col_name = field["field_name"]
        
        # Rule 1: Existence
        suite.add_expectation(gx.expectations.ExpectColumnToExist(column=col_name))
        
        # Rule 2: Aggressive Null & Empty Check
        # 1. Standard Null Check (catch NaN/None)
        suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column=col_name))
        
        # 2. Content Check for Text Columns (catch "", " ", "null", "n/a")
        if "string" in field["data_type"].lower() or "object" in field["data_type"].lower():
             # Catch whitespace-only strings
             suite.add_expectation(gx.expectations.ExpectColumnValuesToMatchRegex(column=col_name, regex=r"^(?!\s*$).+"))
             # Catch common string-placeholders
             suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeInSet(column=col_name, value_set=["null", "NULL", "n/a", "N/A", "nan", "NaN"]))
            
        # Rule 3: Enforce Types (Rule-based vs Inferred)
        enforced_type = None
        for rule in rules:
            pattern = rule.get("pattern")
            if pattern and re.match(pattern, col_name, re.IGNORECASE):
                enforced_type = rule.get("type")
                print(f"[DEBUG] Column '{col_name}' matched pattern '{pattern}' -> Enforcing type '{enforced_type}'")
                break
        
        # Use enforced type if found, otherwise fall back to pandas inference
        dtype_to_check = enforced_type if enforced_type else field["data_type"]
        if not enforced_type:
             print(f"[DEBUG] Column '{col_name}' no rule match. Using inferred type: {dtype_to_check}")
        
        if "int" in dtype_to_check.lower() or "float" in dtype_to_check.lower() or "numeric" in dtype_to_check.lower():
            suite.add_expectation(gx.expectations.ExpectColumnValuesToBeInTypeList(column=col_name, type_list=["int64", "float64", "int32", "float32", "Int64", "Float64"]))
        elif "string" in dtype_to_check.lower() or "object" in dtype_to_check.lower():
            suite.add_expectation(gx.expectations.ExpectColumnValuesToBeOfType(column=col_name, type_="str"))
        elif "datetime" in dtype_to_check.lower():
            pass # Skipping complex date validaton
            
    return suite_name


def detect_outliers(df: pd.DataFrame) -> Dict[str, int]:
    """
    Z-score outlier detection for numeric columns.
    Returns {column_name: outlier_count} for any column with |z| > 3.
    """
    results = {}
    for col in df.select_dtypes(include="number").columns:
        std = df[col].std()
        if std == 0 or pd.isna(std):
            continue
        z = ((df[col] - df[col].mean()) / std).abs()
        count = int((z > 3).sum())
        if count > 0:
            results[col] = count
    return results


def evaluate_quality(db: Session, asset: DataAsset, df_sample: pd.DataFrame, schema_fields: List[Dict[str, Any]], scan_run_id: int):
    """
    Runs Great Expectations validations + outlier/duplicate checks.
    """
    try:
        print(f"[{asset.asset_name}] Evaluating Data Quality...")

        dup_count = int(df_sample.duplicated().sum())
        if dup_count > 0:
            print(f"[Duplicate] {asset.asset_name}: {dup_count} duplicate row(s) detected")

        outliers = detect_outliers(df_sample)
        for col, cnt in outliers.items():
            print(f"[Outlier]   {asset.asset_name} → '{col}': {cnt} outlier(s) (|z| > 3)")

        context = gx.get_context(mode="ephemeral")

        unique_id = str(uuid.uuid4())[:8]

        data_source_name = f"pandas_source_{asset.asset_id}_{unique_id}"
        data_source = context.data_sources.add_pandas(name=data_source_name)

        data_asset_name = f"sample_data_{unique_id}"
        gx_asset = data_source.add_dataframe_asset(name=data_asset_name)

        batch_definition = gx_asset.add_batch_definition_whole_dataframe("batch_def_1")
        batch_parameters = {"dataframe": df_sample}

        suite_name = generate_generic_suite(context, schema_fields, asset.asset_name, unique_id)

        validation_definition_name = f"{asset.asset_name}_{unique_id}_validation"

        validation_definition = context.validation_definitions.add(
            gx.ValidationDefinition(
                name=validation_definition_name,
                data=batch_definition,
                suite=context.suites.get(suite_name),
            )
        )

        validation_results = validation_definition.run(batch_parameters=batch_parameters)

        stats = validation_results.statistics
        print(f"[DEBUG] [{asset.asset_name}] Stats: {json.dumps(stats)}")

        success_count = stats["successful_expectations"]
        total_count   = stats["evaluated_expectations"]
        score = (success_count / total_count * 100) if total_count > 0 else 0.0

        if score >= 95.0:   rank = "A"
        elif score >= 80.0: rank = "B"
        elif score >= 70.0: rank = "C"
        else:               rank = "D"

        print(f"[{asset.asset_name}] Quality Score: {score:.1f}% (Rank {rank})")

        config    = load_quality_rules()
        gate      = config.get("quality_gate", {})
        min_score = gate.get("min_score", 0)
        action    = gate.get("action", "warn")

        if score < min_score:
            msg = f"[Gate] {asset.asset_name} scored {score:.1f}% < threshold {min_score}%"
            if action == "reject":
                raise ValueError(msg + " — asset REJECTED.")
            else:
                print(f"[WARNING] {msg}")

        failed_results = [res.to_json_dict() for res in validation_results.results if not res.success]
        
        # Safely limit the number of failed results to prevent database bloat/truncation issues
        # while keeping the JSON valid for the frontend.
        limited_failed_results = failed_results[:50]
        
        extras = {
            "failed_expectations": limited_failed_results,
            "outliers": outliers,
            "duplicate_rows": dup_count,
            "total_failed_count": len(failed_results)
        }
        
        quality_result = DataQualityResult(
            asset_id=asset.asset_id,
            scan_run_id=scan_run_id,
            score=score,
            rank=rank,
            total_rows=len(df_sample),
            failed_rows=len(failed_results),
            duplicate_rows=dup_count,
            detailed_results_json=json.dumps(extras),
        )
        db.add(quality_result)
        db.commit()

    except Exception as e:
        print(f"[{asset.asset_name}] Error during quality evaluation: {e}")
        db.rollback()
