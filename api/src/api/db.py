# imports:
import os
import sqlmodel
from sqlmodel import Session, SQLModel

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL == "":
    raise NotImplementedError("`DATABASE_URL` needs to be set")

DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://")


engine = sqlmodel.create_engine(DATABASE_URL)

# Database models:
def init_db():
    print("Creating database tables...")
    from api.chat.models import ChatMessage  # noqa: F401
    from api.drafts import Draft  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _ensure_draft_confirmed_at()


def _ensure_draft_confirmed_at() -> None:
    """Add Confirm time on databases created before that column existed."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "draft" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("draft")}
    if "confirmed_at" in columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE draft ADD COLUMN confirmed_at TIMESTAMP WITH TIME ZONE"
            )
        )

# Api routes:
def get_session():
    with Session(engine) as session:
        yield session