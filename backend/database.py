from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
# Note: declarative_base is deprecated in newer SQLAlchemy versions, but we follow the provided snippet for now.
# Consider migrating to `from sqlalchemy.orm import DeclarativeBase` later.
# from sqlalchemy.ext.declarative import declarative_base # 이전 임포트 주석 처리
from backend.config.database import settings # Adjusted import path

# Create the SQLAlchemy engine using the DATABASE_URL from settings
# echo=True logs SQL queries, useful for debugging, can be removed in production
engine = create_engine(settings.DATABASE_URL, echo=True)

# Create a configured "Session" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create a Base class for declarative class definitions
Base = declarative_base()

# Dependency function to get a DB session per request
def get_db():
    db = SessionLocal()
    try:
        yield db # Provide the session to the endpoint
    finally:
        db.close() # Ensure the session is closed after the request 