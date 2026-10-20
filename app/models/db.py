from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

Base = declarative_base()


class MediaRecord(Base):
    __tablename__ = "media_records"
    id = Column(String(64), primary_key=True)
    original_filename = Column(String(255), nullable=False)
    storage_path = Column(String(512), nullable=False)
    sha256_hash = Column(String(64), nullable=False)
    metadata_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TimelineRecord(Base):
    __tablename__ = "timelines"
    media_id = Column(String(64), primary_key=True)
    revision = Column(Integer, default=0, nullable=False)
    timeline_json = Column(Text, nullable=False)
    canonical_hash = Column(String(64), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class TimelineHistoryRecord(Base):
    __tablename__ = "timeline_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    media_id = Column(String(64), nullable=False, index=True)
    operation_id = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False)
    operation_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class JobRecord(Base):
    __tablename__ = "jobs"
    job_id = Column(String(64), primary_key=True)
    job_type = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="queued")
    progress = Column(Float, default=0.0)
    result_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    key = Column(String(255), primary_key=True)
    payload_hash = Column(String(64), nullable=False)
    state = Column(String(16), nullable=False, default="pending")
    status_code = Column(Integer, nullable=True)
    response_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class ClarificationSessionRecord(Base):
    __tablename__ = "clarification_sessions"
    session_id = Column(String(64), primary_key=True)
    media_id = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    options_json = Column(Text, nullable=False)
    pending_proposal_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ProjectRecord(Base):
    __tablename__ = "projects"
    project_id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    media_id = Column(String(64), nullable=True, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
