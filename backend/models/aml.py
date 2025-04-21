import enum
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, JSON, Enum, Text, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.database import Base, engine

class AlertStatus(str, enum.Enum):
    NEW = "new"
    INVESTIGATING = "investigating"
    DISMISSED = "dismissed" 
    REPORTED = "reported"
    CLOSED = "closed"

class AlertType(str, enum.Enum):
    LARGE_TRANSACTION = "large_transaction"
    UNUSUAL_PATTERN = "unusual_pattern"
    STRUCTURING = "structuring"
    HIGH_RISK_COUNTRY = "high_risk_country"
    SANCTIONS_MATCH = "sanctions_match"
    PEP_MATCH = "pep_match"
    RAPID_MOVEMENT = "rapid_movement"
    MANUAL = "manual"

class AlertSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class AMLAlert(Base):
    __tablename__ = "aml_alerts"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(String, index=True, nullable=False)
    alert_type = Column(Enum(AlertType), nullable=False)
    alert_severity = Column(Enum(AlertSeverity), nullable=False)
    alert_status = Column(Enum(AlertStatus), default=AlertStatus.NEW, nullable=False)
    description = Column(Text, nullable=False)
    detection_rule = Column(String, nullable=True)
    risk_score = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reviewed_by = Column(String, nullable=True)
    review_notes = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    transaction_ids = Column(ARRAY(String), nullable=True)
    transaction_details = Column(JSON, nullable=True)
    alert_data = Column(JSON, nullable=True)
    reported_at = Column(DateTime(timezone=True), nullable=True)
    report_reference = Column(String, nullable=True)

    def __repr__(self):
        return f"<AMLAlert(id={self.id}, player_id={self.player_id}, alert_type={self.alert_type})>"

class AMLTransaction(Base):
    __tablename__ = "aml_transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(String, index=True, unique=True, nullable=False)
    player_id = Column(String, index=True, nullable=False)
    is_large_transaction = Column(Boolean, default=False, nullable=False)
    is_suspicious_pattern = Column(Boolean, default=False, nullable=False)
    is_unusual_for_player = Column(Boolean, default=False, nullable=False)
    is_structuring_attempt = Column(Boolean, default=False, nullable=False)
    is_regulatory_report_required = Column(Boolean, default=False, nullable=False)
    risk_score = Column(Float, nullable=False)
    risk_factors = Column(JSON, nullable=True)
    regulatory_threshold_currency = Column(String, nullable=True)
    regulatory_threshold_amount = Column(Float, nullable=True)
    reporting_jurisdiction = Column(String, nullable=True)
    analysis_version = Column(String, nullable=False)
    analysis_details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<AMLTransaction(id={self.id}, transaction_id={self.transaction_id}, player_id={self.player_id})>"

class AMLRiskProfile(Base):
    __tablename__ = "aml_risk_profiles"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(String, index=True, unique=True, nullable=False)
    overall_risk_score = Column(Float, default=0.0, nullable=False)
    deposit_risk_score = Column(Float, default=0.0, nullable=False)
    withdrawal_risk_score = Column(Float, default=0.0, nullable=False)
    gameplay_risk_score = Column(Float, default=0.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_deposit_at = Column(DateTime(timezone=True), nullable=True)
    last_withdrawal_at = Column(DateTime(timezone=True), nullable=True)
    last_played_at = Column(DateTime(timezone=True), nullable=True)
    deposit_count_7d = Column(Integer, default=0, nullable=False)
    deposit_amount_7d = Column(Float, default=0.0, nullable=False)
    withdrawal_count_7d = Column(Integer, default=0, nullable=False)
    withdrawal_amount_7d = Column(Float, default=0.0, nullable=False)
    deposit_count_30d = Column(Integer, default=0, nullable=False)
    deposit_amount_30d = Column(Float, default=0.0, nullable=False)
    withdrawal_count_30d = Column(Integer, default=0, nullable=False)
    withdrawal_amount_30d = Column(Float, default=0.0, nullable=False)
    wager_to_deposit_ratio = Column(Float, default=0.0, nullable=False)
    withdrawal_to_deposit_ratio = Column(Float, default=0.0, nullable=False)
    risk_factors = Column(JSON, nullable=True)
    risk_mitigation = Column(JSON, nullable=True)
    last_assessment_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<AMLRiskProfile(id={self.id}, player_id={self.player_id}, risk_score={self.overall_risk_score})>"

class AMLReport(Base):
    __tablename__ = "aml_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(String, index=True, unique=True, nullable=False)
    player_id = Column(String, index=True, nullable=False)
    report_type = Column(String, nullable=False)
    jurisdiction = Column(String, nullable=False)
    alert_id = Column(Integer, ForeignKey("aml_alerts.id"), nullable=True)
    transaction_ids = Column(ARRAY(String), nullable=True)
    report_data = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String, default="draft", nullable=False)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    submission_reference = Column(String, nullable=True)

    # 관계
    alert = relationship("AMLAlert", backref="reports")

    def __repr__(self):
        return f"<AMLReport(id={self.id}, report_id={self.report_id}, player_id={self.player_id})>"

# 테이블이 존재하지 않는 경우에만 생성
def create_tables():
    Base.metadata.create_all(bind=engine, tables=[
        AMLAlert.__table__,
        AMLTransaction.__table__,
        AMLRiskProfile.__table__,
        AMLReport.__table__,
    ])

# 서버 시작 시 테이블 생성 호출 삭제
# create_tables() 