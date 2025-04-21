from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship

from casino_platform.database import Base
from casino_platform.schemas.wallet import Language, TimeZone, Currency


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    
    # 국제화 지원을 위한 필드 추가
    country = Column(String(2), nullable=True)  # ISO 국가 코드
    language = Column(String(5), default="ko", nullable=False)  # 선호 언어
    timezone = Column(String(50), default="UTC", nullable=False)  # 선호 시간대
    preferred_currency = Column(String(3), default="KRW", nullable=False)  # 선호 통화
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계 설정
    profile = relationship("Profile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    wallet = relationship("Wallet", back_populates="user", uselist=False, cascade="all, delete-orphan")
    preferences = relationship("UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    first_name = Column(String)
    last_name = Column(String)
    bio = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    
    # 국제화 및 규제 준수를 위한 추가 필드
    date_of_birth = Column(DateTime, nullable=True)  # 연령 제한 검증용
    country = Column(String(2), nullable=True)  # ISO 국가 코드
    city = Column(String(100), nullable=True)
    address = Column(String(255), nullable=True)
    phone_number = Column(String(20), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계 설정
    user = relationship("User", back_populates="profile")


class UserPreference(Base):
    """사용자 환경설정 모델"""
    __tablename__ = "user_preferences"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    language = Column(Enum(Language), default=Language.KO, nullable=False)
    timezone = Column(Enum(TimeZone), default=TimeZone.UTC, nullable=False)
    currency = Column(Enum(Currency), default=Currency.KRW, nullable=False)
    
    # 알림 설정
    email_notifications = Column(Boolean, default=True)
    sms_notifications = Column(Boolean, default=False)
    push_notifications = Column(Boolean, default=True)
    
    # 인증 설정
    two_factor_auth = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 관계 설정
    user = relationship("User", back_populates="preferences") 