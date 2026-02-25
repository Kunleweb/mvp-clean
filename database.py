import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# File-based SQLite Database
DATABASE_URL = "sqlite:///metadata.db"

# Create Engine
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class to create models
Base = declarative_base()

