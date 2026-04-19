import requests
from fastapi import HTTPException
from typing import Dict, Any
from .base import BaseIngestAdapter
from data_platform.config import RAPIDAPI_KEY, ALPHA_VANTAGE_HOST

class AlphaVantageAdapter(BaseIngestAdapter):
    @property
    def source_name(self) -> str:
        return "alpha-vantage"

    async def fetch_data(self, symbol: str) -> Dict[str, Any]:
        if not symbol:
            raise HTTPException(status_code=400, detail="Symbol parameter is required for Alpha Vantage.")
            
        url = f"https://{ALPHA_VANTAGE_HOST}/query?function=TIME_SERIES_DAILY&symbol={symbol}&outputsize=compact&datatype=json"
        
        headers = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": ALPHA_VANTAGE_HOST
        }
        
        try:
            # We use synchronous requests here for simplicity, 
            # but in a high-throughput async app this should be httpx.
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # Check for API level errors disguised as 200 OK
            if "Error Message" in data:
                raise HTTPException(status_code=400, detail=f"Alpha Vantage API Error: {data['Error Message']}")
            if "Note" in data:
                # Often indicative of rate limiting
                raise HTTPException(status_code=429, detail=f"Alpha Vantage API Rate Limit: {data['Note']}")
                
            return data
            
        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch data from Alpha Vantage: {str(e)}")
