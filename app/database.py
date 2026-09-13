"""
DB engine/session setup. Uses SQLite by default (file: mailpulse.db).
Switch DATABASE_URL in .env to a Postgres URL later for production, per the
project doc's SQLite -> PostgreSQL migration plan.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://mailpulse:mailpulse@localhost:5432/mailpulse")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401 ensures models are registered
    Base.metadata.create_all(bind=engine)
