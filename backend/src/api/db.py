# imports:
import os
import sqlmodel
from sqlmodel import Session, SQLModel

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# SQLAlchemy 2.0+ with psycopg v3 requires the "psycopg" scheme.
# Railway (and most providers) set DATABASE_URL with "postgresql://", so
# rewrite it here so the correct driver is selected automatically.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "psycopg://", 1)
elif DATABASE_URL.startswith("postgresql+psycopg2://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "psycopg://", 1)

if DATABASE_URL == "":
    raise NotImplementedError("`DATABASE_URL` needs to be set")

engine = sqlmodel.create_engine(DATABASE_URL)

# Database models:
def init_db():
    print("Creating database tables...")
    SQLModel.metadata.create_all(engine)

# Api routes:
def get_session():
    with Session(engine) as session:
        yield session