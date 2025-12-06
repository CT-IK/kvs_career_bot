from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    course = Column(Integer)
    faculty = Column(String(50))
    info_source = Column(String(100))
    is_registered = Column(Boolean, default=False)
    registered_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)


class Vacancy(Base):
    __tablename__ = "vacancies"
    
    id = Column(Integer, primary_key=True)
    organization = Column(String(200))
    position = Column(String(200))
    sphere = Column(String(100))
    salary = Column(String(100))
    schedule = Column(String(100))
    work_format = Column(String(100))
    description = Column(Text)
    employment_format = Column(String(100))
    feature1 = Column(String(200))
    feature2 = Column(String(200))
    feature3 = Column(String(200))
    
    # Факультеты (булевы поля)
    itiabd = Column(Boolean, default=False)
    finfak = Column(Boolean, default=False)
    vshu = Column(Boolean, default=False)
    nab = Column(Boolean, default=False)
    snimk = Column(Boolean, default=False)
    meo = Column(Boolean, default=False)
    feb = Column(Boolean, default=False)
    yurfak = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Statistics(Base):
    __tablename__ = "statistics"
    
    id = Column(Integer, primary_key=True)
    total_users = Column(Integer, default=0)
    registered_users = Column(Integer, default=0)
    total_vacancies = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

