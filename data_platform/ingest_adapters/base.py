from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseIngestAdapter(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str:
        """Name of the API source (e.g., 'alpha-vantage'). Used for the S3 path."""
        pass

    @abstractmethod
    async def fetch_data(self, **kwargs) -> Dict[str, Any]:
        """Specific logic to pull data from the API and return a Python dictionary."""
        pass
