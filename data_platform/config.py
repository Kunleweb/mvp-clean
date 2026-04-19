import os
from dotenv import load_dotenv

load_dotenv()

# Centralized settings
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///metadata.db")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")

DATA_SOURCE_PATH = "./data"
DATA_SOURCE_NAME = "Local CSV Folder"
SCAN_COOLDOWN_SECONDS = 2

# RapidAPI Settings
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
ALPHA_VANTAGE_HOST = "alpha-vantage.p.rapidapi.com"

# AWS S3 Settings
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "eu-west-2")
AWS_S3_BUCKET = os.getenv("S3")