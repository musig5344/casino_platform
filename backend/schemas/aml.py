from pydantic import BaseModel, Field, validator, confloat, ConfigDict
from typing import Optional, List, Dict, Any, Literal, Union
from datetime import datetime
from enum import Enum
import re
import uuid

# 기본 열거형
class AlertStatus(str, Enum):
    NEW = "new"
    REVIEWING = "reviewing"
    DISMISSED = "dismissed"
    REPORTED = "reported"
    CLOSED = "closed"

class AlertType(str, Enum):
    LARGE_DEPOSIT = "large_deposit"
    LARGE_WITHDRAWAL = "large_withdrawal"
    RAPID_MOVEMENT = "rapid_movement"
    UNUSUAL_PATTERN = "unusual_pattern"
    SUSPICIOUS_LOSS = "suspicious_loss"
    MULTIPLE_ACCOUNTS = "multiple_accounts"
    UNUSUAL_PLAY_PATTERN = "unusual_play_pattern"
    MULTIPLE_PAYMENT_METHODS = "multiple_payment_methods"
    LOW_WAGERING = "low_wagering"
    THRESHOLD_AVOIDANCE = "threshold_avoidance"
    PEP_ACTIVITY = "politically_exposed_person"
    SANCTIONED_COUNTRY = "sanctioned_country"
    JURISDICTION_RISK = "high_risk_jurisdiction"

class AlertSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ReportingJurisdiction(str, Enum):
    MALTA = "MT"  # 몰타 관할
    PHILIPPINES = "PH"  # 필리핀 관할
    CURACAO = "CW"  # 퀴라소 관할
    GIBRALTAR = "GI"  # 지브롤터 관할
    ISLE_OF_MAN = "IM"  # 맨 섬 관할
    ALDERNEY = "GG"  # 올더니 관할
    KAHNAWAKE = "CA"  # 카나와케(캐나다) 관할

# 기본 모델
class AMLBase(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

# 알림 생성 요청 모델
class AMLAlertCreate(AMLBase):
    player_id: str
    alert_type: AlertType
    alert_severity: AlertSeverity
    description: str
    detection_rule: str
    transaction_ids: Optional[List[str]] = None
    transaction_details: Optional[Dict[str, Any]] = None
    alert_data: Optional[Dict[str, Any]] = None
    risk_score: confloat(ge=0, le=100) = 50.0

# 알림 상태 업데이트 요청 모델
class AlertStatusUpdate(AMLBase):
    alert_id: int
    status: AlertStatus
    review_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    report_reference: Optional[str] = None

# 알림 조회 응답 모델
class AMLAlertResponse(AMLBase):
    id: int
    player_id: str
    alert_type: AlertType
    alert_severity: AlertSeverity
    alert_status: AlertStatus
    description: str
    detection_rule: str
    risk_score: float
    created_at: datetime
    reviewed_by: Optional[str] = None
    review_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None

# 알림 상세 조회 응답 모델
class AMLAlertDetailResponse(AMLAlertResponse):
    transaction_ids: Optional[List[str]] = None
    transaction_details: Optional[Dict[str, Any]] = None
    alert_data: Optional[Dict[str, Any]] = None
    reported_at: Optional[datetime] = None
    report_reference: Optional[str] = None

# AML 트랜잭션 분석 결과 모델
class AMLTransactionAnalysis(AMLBase):
    transaction_id: str
    player_id: str
    is_large_transaction: bool = False
    is_suspicious_pattern: bool = False
    is_unusual_for_player: bool = False
    is_structuring_attempt: bool = False
    is_regulatory_report_required: bool = False
    risk_score: float
    risk_factors: Optional[Dict[str, Any]] = None
    regulatory_threshold_currency: Optional[str] = None
    regulatory_threshold_amount: Optional[float] = None
    reporting_jurisdiction: Optional[ReportingJurisdiction] = None
    analysis_version: str
    analysis_details: Optional[Dict[str, Any]] = None

# AML 위험 프로필 모델
class AMLRiskProfileResponse(AMLBase):
    player_id: str
    overall_risk_score: float
    deposit_risk_score: float
    withdrawal_risk_score: float
    gameplay_risk_score: float
    is_active: bool
    last_deposit_at: Optional[datetime] = None
    last_withdrawal_at: Optional[datetime] = None
    last_played_at: Optional[datetime] = None
    deposit_count_7d: int
    deposit_amount_7d: float
    withdrawal_count_7d: int
    withdrawal_amount_7d: float
    deposit_count_30d: int
    deposit_amount_30d: float
    withdrawal_count_30d: int
    withdrawal_amount_30d: float
    wager_to_deposit_ratio: Optional[float] = None
    withdrawal_to_deposit_ratio: Optional[float] = None
    risk_factors: Optional[Dict[str, Any]] = None
    risk_mitigation: Optional[Dict[str, Any]] = None
    last_assessment_at: Optional[datetime] = None

# AML 보고서 요청 모델
class AMLReportRequest(AMLBase):
    player_id: str
    alert_id: Optional[int] = None
    report_type: Literal["STR", "CTR", "SAR"] = "STR"  # STR: 의심거래보고서, CTR: 고액현금거래보고서, SAR: 의심활동보고서
    jurisdiction: ReportingJurisdiction
    notes: Optional[str] = None
    transaction_ids: Optional[List[str]] = None

# AML 보고서 응답 모델
class AMLReportResponse(AMLBase):
    report_id: str
    player_id: str
    report_type: str
    jurisdiction: ReportingJurisdiction
    created_at: datetime
    status: Literal["draft", "submitted", "acknowledged"] = "draft"
    submission_reference: Optional[str] = None

# AML 규제 요구사항 모델 - 관할별 규제 임계값 등
class RegulatoryRequirement(AMLBase):
    jurisdiction: ReportingJurisdiction
    currency: str
    deposit_threshold: float  # 보고 필요한 입금 임계값
    withdrawal_threshold: float  # 보고 필요한 출금 임계값
    reporting_timeframe_hours: int  # 보고 기한(시간)
    str_required: bool = True  # 의심거래보고서 필요 여부
    ctr_required: bool = True  # 고액현금거래보고서 필요 여부
    regulatory_authority: str  # 규제 기관명
    regulation_reference: str  # 관련 규정 참조 