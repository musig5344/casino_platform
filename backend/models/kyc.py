from sqlalchemy import Column, String, Integer, ForeignKey, TIMESTAMP, func, Boolean, Enum, JSON, Index, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from enum import Enum as PyEnum
from backend.database import Base, engine
from backend.models.user import Player  # Player 모델 임포트
from datetime import datetime

class VerificationStatus(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"

class RiskLevel(str, PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"

class KYCVerification(Base):
    __tablename__ = "kyc_verifications"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String(50), ForeignKey("players.id"), nullable=False, unique=True)
    
    # 기본 신원 정보
    full_name = Column(String(100), nullable=False)
    date_of_birth = Column(String(10), nullable=False)  # 'YYYY-MM-DD' 형식
    nationality = Column(String(2), nullable=False)  # ISO 3166-1 alpha-2 국가 코드
    address = Column(Text, nullable=False)
    city = Column(String(100), nullable=False)
    postal_code = Column(String(20), nullable=False)
    country = Column(String(2), nullable=False)  # ISO 3166-1 alpha-2 국가 코드
    
    # 신분증 정보
    document_type = Column(String(20), nullable=False)  # passport, id_card, driving_license
    document_number = Column(String(50), nullable=False)
    document_issue_date = Column(String(10), nullable=False)  # 'YYYY-MM-DD' 형식
    document_expiry_date = Column(String(10), nullable=False)  # 'YYYY-MM-DD' 형식
    document_issuing_country = Column(String(2), nullable=False)  # ISO 3166-1 alpha-2 국가 코드
    
    # 민감 정보 (암호화된 형태로 저장)
    encrypted_document_data = Column(Text, nullable=True)  # 암호화된 문서 이미지 참조 또는 데이터
    encrypted_additional_data = Column(JSONB, nullable=True)  # 기타 암호화된 민감 정보
    
    # 검증 상태 및 리스크 수준
    verification_status = Column(Enum(VerificationStatus), default=VerificationStatus.PENDING, nullable=False)
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.MEDIUM, nullable=False)
    verification_notes = Column(Text, nullable=True)
    last_checked_at = Column(TIMESTAMP, nullable=True)
    verified_at = Column(TIMESTAMP, nullable=True)
    
    # 검증 메타데이터
    verification_method = Column(String(20), nullable=True)  # manual, automated, third_party
    verification_provider = Column(String(50), nullable=True)  # 제3자 검증 서비스 제공업체
    verification_reference = Column(String(100), nullable=True)  # 외부 검증 참조 ID
    
    # PEP 및 제재 목록 검사 결과
    is_politically_exposed = Column(Boolean, default=False, nullable=False)
    is_sanctioned = Column(Boolean, default=False, nullable=False)
    is_high_risk_jurisdiction = Column(Boolean, default=False, nullable=False)
    
    # 시스템 메타데이터
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(TIMESTAMP, nullable=True)  # GDPR용 소프트 삭제
    
    # 관계 설정
    player = relationship("Player", back_populates="kyc_verification")
    risk_assessments = relationship("RiskAssessment", back_populates="kyc_verification", cascade="all, delete-orphan")

class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    kyc_id = Column(Integer, ForeignKey("kyc_verifications.id"), nullable=False)
    
    assessment_date = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    previous_risk_level = Column(Enum(RiskLevel), nullable=True)
    current_risk_level = Column(Enum(RiskLevel), nullable=False)
    reason = Column(Text, nullable=False)
    assessor = Column(String(50), nullable=True)  # 담당자 ID 또는 '시스템'
    assessment_data = Column(JSONB, nullable=True)  # 평가에 사용된 데이터 또는 규칙 요약
    
    # 관계 설정
    kyc_verification = relationship("KYCVerification", back_populates="risk_assessments")

# Player 모델에 kyc_verification 관계 추가를 위한 백 참조 설정
Player.kyc_verification = relationship("KYCVerification", back_populates="player", uselist=False)

# 테이블이 존재하지 않는 경우에만 생성
def create_tables():
    Base.metadata.create_all(bind=engine, tables=[
        KYCVerification.__table__, 
        RiskAssessment.__table__
    ])

# 서버 시작 시 테이블 생성
create_tables() 