"""
Database session management.

Provides session factory and dependency injection for FastAPI.
"""

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from portal.config import settings

# Create engine with connection pooling
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # Verify connections before use
    pool_size=5,
    max_overflow=10,
    echo=settings.debug,  # Log SQL in debug mode
)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """
    Database session dependency for FastAPI.

    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session() -> Session:
    """
    Get a database session for non-FastAPI usage (e.g., batch jobs).

    Usage:
        with get_session() as session:
            session.query(...)

    Or:
        session = get_session()
        try:
            session.query(...)
            session.commit()
        finally:
            session.close()
    """
    return SessionLocal()
