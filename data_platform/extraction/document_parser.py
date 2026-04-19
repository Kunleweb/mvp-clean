import os
import json
import requests
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Type, Optional
from pydantic import BaseModel
from landingai_ade.lib import pydantic_to_json_schema

class LandingAIADEClient:
    """
    Wrapper for LandingAI Agentic Document Extraction (ADE) service using direct REST API.
    """
    def __init__(self):
        self.api_key = os.environ.get("VISION_AGENT_API_KEY")
        self.parse_url = "https://api.va.landing.ai/v1/ade/parse"
        self.extract_url = "https://api.va.landing.ai/v1/ade/extract"

    def extract_structured_data(self, file_path: str, schema_class: Type[BaseModel]) -> pd.DataFrame:
        if not self.api_key:
            raise ValueError("VISION_AGENT_API_KEY is not set.")

        print(f"[ADE] Processing: {os.path.basename(file_path)}")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        with open(file_path, "rb") as f:
            files = {"document": f}
            resp_parse = requests.post(self.parse_url, headers=headers, files=files)
        
        if resp_parse.status_code != 200:
            raise Exception(f"Parse failed {resp_parse.status_code}: {resp_parse.text}")
            
        parsed_data = resp_parse.json()
        markdown_content = parsed_data.get("markdown", "")
        if not markdown_content:
            if "chunks" in parsed_data:
                markdown_content = "\n\n".join([c.get("content", str(c)) for c in parsed_data["chunks"]])
            else:
                markdown_content = str(parsed_data.get("content", str(parsed_data)))

        print(f"[ADE] Extracting structured data using schema: {schema_class.__name__}")
        
        dynamic_schema = {
            "type": "object",
            "properties": {}
        }
        for name, field in schema_class.model_fields.items():
            f_type = "number" if field.annotation in [int, float] else "string"
            dynamic_schema["properties"][name] = {"type": f_type}
            
        payload = {
            "markdown": markdown_content,
            "schema": json.dumps(dynamic_schema)
        }
        
        resp_extract = requests.post(self.extract_url, headers=headers, json=payload)
        
        if resp_extract.status_code not in [200, 206]:
            resp_extract = requests.post(self.extract_url, headers=headers, data=payload)
            if resp_extract.status_code not in [200, 206]:
                raise Exception(f"Extract failed {resp_extract.status_code}: {resp_extract.text}")
            
        result = resp_extract.json()
        data = result.get("extraction", result.get("content", result))
        
        df = pd.DataFrame(data if isinstance(data, list) else [data])
        
        mvp_dir = Path(__file__).resolve().parent.parent.parent
        out_dir = mvp_dir / "data" / "extracted"
        out_dir.mkdir(parents=True, exist_ok=True)
        base = os.path.basename(file_path).rsplit('.', 1)[0]
        
        md_file = out_dir / f"{base}_parsed.md"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
            
        csv_file = out_dir / f"{base}_extracted.csv"
        df.to_csv(csv_file, index=False)
        print(f"[ADE] SUCCESS: Saved to {csv_file.absolute()}")
            
        return df

class InvoiceSchema(BaseModel):
    invoice_number: Optional[str] = None
    date: Optional[str] = None
    total_amount: Optional[float] = None
    vendor_name: Optional[str] = None
    items_purchased: Optional[str] = None

class UtilityBillSchema(BaseModel):
    account_number: Optional[str] = None
    billing_period: Optional[str] = None
    total_due: Optional[float] = None
    utility_provider: Optional[str] = None

class GenericDocumentSchema(BaseModel):
    document_type: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    date: Optional[str] = None
    key_entities: Optional[str] = None
