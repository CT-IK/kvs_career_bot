from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    max_user_id = Column(BigInteger, unique=True, nullable=True, index=True)
    username = Column(String(64), index=True)
    email = Column(String(255), index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    patronymic = Column(String(100), nullable=True)
    course = Column(Integer)
    faculty = Column(String(50))
    info_source = Column(String(100))
    is_admin = Column(Boolean, default=False, nullable=False)
    is_registered = Column(Boolean, default=False)
    registered_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)

    event_registrations = relationship("EventRegistration", back_populates="user")
    actions = relationship("UserAction", back_populates="user")


class Vacancy(Base):
    __tablename__ = "vacancies"

    id = Column(Integer, primary_key=True)
    source_key = Column(String(64), unique=True, nullable=True, index=True)
    source_row = Column(Integer, nullable=True)
    organization = Column(String(200))
    division = Column(String(200))
    position = Column(String(200))
    sphere = Column(String(100))
    salary = Column(String(100))
    schedule = Column(String(100))
    work_format = Column(String(100))
    description = Column(Text)
    vacancy_url = Column(Text)
    employment_format = Column(String(100))
    feature1 = Column(String(200))
    feature2 = Column(String(200))
    feature3 = Column(String(200))

    itiabd = Column(Boolean, default=False)
    ioo = Column(Boolean, default=False)
    finfak = Column(Boolean, default=False)
    vshu = Column(Boolean, default=False)
    nab = Column(Boolean, default=False)
    snimk = Column(Boolean, default=False)
    meo = Column(Boolean, default=False)
    feb = Column(Boolean, default=False)
    yurfak = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VacancySyncState(Base):
    __tablename__ = "vacancy_sync_state"

    id = Column(Integer, primary_key=True, default=1)
    status = Column(String(20), nullable=False, default="idle")
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    source_count = Column(Integer, nullable=False, default=0)
    added_count = Column(Integer, nullable=False, default=0)
    updated_count = Column(Integer, nullable=False, default=0)
    deleted_count = Column(Integer, nullable=False, default=0)


class Statistics(Base):
    __tablename__ = "statistics"

    id = Column(Integer, primary_key=True)
    total_users = Column(Integer, default=0)
    registered_users = Column(Integer, default=0)
    total_vacancies = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserAction(Base):
    __tablename__ = "user_actions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    username = Column(String(64), index=True)
    update_type = Column(String(32), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    raw_value = Column(Text)
    chat_type = Column(String(32))
    fsm_state = Column(String(255), index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="actions")


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), unique=True, nullable=False, index=True)
    description = Column(Text)
    logo_url = Column(Text)
    achievements = Column(Text)
    is_partner = Column(Boolean, default=False, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    divisions = relationship(
        "Division",
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="Division.id",
    )


class Division(Base):
    __tablename__ = "divisions"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company", back_populates="divisions")


class MiniappEvent(Base):
    """Career events shown in the miniapp's "Мероприятия" tab.

    Separate from the legacy Event/EventRegistration flow below. These events
    are managed in the MAX miniapp and support capacity plus a reserve queue.
    """

    __tablename__ = "miniapp_events"

    id = Column(Integer, primary_key=True)
    category = Column(String(50), nullable=False, default="Другое")
    format = Column(String(50), nullable=False, default="Офлайн")
    image_url = Column(Text)
    lead = Column(String(255))
    title = Column(String(255), nullable=False)
    date_text = Column(String(255))
    starts_at = Column(DateTime(timezone=True), nullable=True, index=True)
    place = Column(String(255))
    description = Column(Text)
    deadline_text = Column(String(255))
    external_url = Column(Text)
    capacity = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    registrations = relationship(
        "MiniappEventRegistration",
        back_populates="event",
        cascade="all, delete-orphan",
    )


class MiniappEventRegistration(Base):
    __tablename__ = "miniapp_event_registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "telegram_id", name="uq_miniapp_event_registration"),
        UniqueConstraint("event_id", "max_user_id", name="uq_miniapp_event_registration_max"),
    )

    id = Column(Integer, primary_key=True)
    event_id = Column(
        Integer,
        ForeignKey("miniapp_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # telegram_id is retained only for existing rows created before the MAX
    # migration. All new miniapp registrations use max_user_id.
    telegram_id = Column(BigInteger, nullable=True, index=True)
    max_user_id = Column(BigInteger, nullable=True, index=True)
    status = Column(String(20), nullable=False, default="confirmed", index=True)
    promoted_at = Column(DateTime(timezone=True), nullable=True)
    reminder_day_sent_at = Column(DateTime(timezone=True), nullable=True)
    reminder_two_hours_sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    event = relationship("MiniappEvent", back_populates="registrations")


class MiniappAction(Base):
    """Page views and UI actions generated by the MAX mini app."""

    __tablename__ = "miniapp_actions"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, nullable=True, index=True)
    max_user_id = Column(BigInteger, nullable=True, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(24), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    route = Column(String(255), nullable=False, index=True)
    target = Column(String(255))
    raw_data = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    photo_file_id = Column(String(255))
    capacity = Column(Integer, nullable=False, default=0)
    success_message = Column(Text, nullable=False)
    reserve_message = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    spreadsheet_id = Column(String(255), unique=True)
    spreadsheet_url = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    registrations = relationship(
        "EventRegistration",
        back_populates="event",
        cascade="all, delete-orphan",
    )


class EventRegistration(Base):
    __tablename__ = "event_registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_event_registrations_event_user"),
    )

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("Event", back_populates="registrations")
    user = relationship("User", back_populates="event_registrations")
