# imports:
import os
import sqlmodel
from sqlmodel import Session, SQLModel

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL == "":
    raise NotImplementedError("`DATABASE_URL` needs to be set")

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "psycopg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "psycopg://", 1)

engine = sqlmodel.create_engine(DATABASE_URL)

# Database models:
def init_db():
    print("Creating database tables...")
    SQLModel.metadata.create_all(engine)

# Api routes:
def get_session():
    with Session(engine) as session:
        yield session