from pydantic import BaseModel, Field, validator, constr
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, date
from enum import Enum
import re

# 열거형
class VerificationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"

class DocumentType(str, Enum):
    PASSPORT = "passport"
    ID_CARD = "id_card"
    DRIVING_LICENSE = "driving_license"
    RESIDENCE_PERMIT = "residence_permit"
    OTHER = "other"

# 기본 모델
class KYCBase(BaseModel):
    full_name: constr(min_length=2, max_length=100) = Field(..., description="플레이어의 전체 이름")
    date_of_birth: str = Field(..., description="생년월일 (YYYY-MM-DD 형식)")
    nationality: constr(min_length=2, max_length=2) = Field(..., description="국적 (ISO 3166-1 alpha-2)")
    address: str = Field(..., description="거주지 주소")
    city: str = Field(..., description="도시")
    postal_code: str = Field(..., description="우편번호")
    country: constr(min_length=2, max_length=2) = Field(..., description="국가 코드 (ISO 3166-1 alpha-2)")
    
    @validator('date_of_birth')
    def validate_date_of_birth(cls, v):
        try:
            date_obj = datetime.strptime(v, "%Y-%m-%d").date()
            today = date.today()
            age = today.year - date_obj.year - ((today.month, today.day) < (date_obj.month, date_obj.day))
            
            if age < 18:
                raise ValueError("플레이어는 18세 이상이어야 합니다")
            if age > 120:
                raise ValueError("유효하지 않은 생년월일")
                
            return v
        except ValueError as e:
            if "does not match format" in str(e):
                raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다")
            raise
    
    @validator('nationality', 'country')
    def validate_country_code(cls, v):
        if not re.match(r'^[A-Z]{2}$', v):
            raise ValueError("국가 코드는 ISO 3166-1 alpha-2 형식이어야 합니다 (예: KR, US)")
        return v

# 신분증 정보 모델
class DocumentInfo(BaseModel):
    document_type: DocumentType
    document_number: constr(min_length=3, max_length=50)
    document_issue_date: str  # YYYY-MM-DD 형식
    document_expiry_date: str  # YYYY-MM-DD 형식
    document_issuing_country: constr(min_length=2, max_length=2)
    
    @validator('document_issue_date', 'document_expiry_date')
    def validate_dates(cls, v, values, **kwargs):
        try:
            date_obj = datetime.strptime(v, "%Y-%m-%d").date()
            field_name = kwargs.get('field').name
            
            if field_name == 'document_expiry_date':
                today = date.today()
                if date_obj < today:
                    raise ValueError("만료된 신분증입니다")
                
            return v
        except ValueError as e:
            if "does not match format" in str(e):
                raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다")
            raise
    
    @validator('document_issuing_country')
    def validate_country_code(cls, v):
        if not re.match(r'^[A-Z]{2}$', v):
            raise ValueError("국가 코드는 ISO 3166-1 alpha-2 형식이어야 합니다 (예: KR, US)")
        return v

# KYC 생성 요청 모델
class KYCVerificationRequest(KYCBase):
    document_info: DocumentInfo
    terms_accepted: bool = Field(..., description="이용 약관 동의 여부")
    privacy_accepted: bool = Field(..., description="개인정보 수집 동의 여부")
    
    @validator('terms_accepted', 'privacy_accepted')
    def validate_acceptance(cls, v):
        if not v:
            raise ValueError("이용 약관 및 개인정보 수집에 대한 동의가 필요합니다")
        return v

# 문서 업로드 요청 모델
class DocumentUploadRequest(BaseModel):
    document_type: DocumentType
    document_side: Literal["front", "back", "selfie"] = "front"
    file_name: str
    content_type: str = Field(..., description="파일 MIME 타입 (예: image/jpeg)")

# 문서 업로드 응답 모델
class DocumentUploadResponse(BaseModel):
    upload_url: str
    document_id: str
    expires_at: str

# KYC 확인 응답 모델
class KYCVerificationResponse(BaseModel):
    id: int
    player_id: str
    verification_status: VerificationStatus
    risk_level: RiskLevel
    created_at: datetime
    updated_at: datetime
    message: Optional[str] = None

# KYC 상세 조회 응답 모델
class KYCVerificationDetailResponse(KYCVerificationResponse):
    full_name: str
    nationality: str
    date_of_birth: str
    document_type: DocumentType
    document_number: str
    document_expiry_date: str
    is_politically_exposed: bool
    is_sanctioned: bool
    is_high_risk_jurisdiction: bool
    verification_notes: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None

# 위험 평가 응답 모델
class RiskAssessmentResponse(BaseModel):
    id: int
    kyc_id: int
    assessment_date: datetime
    previous_risk_level: Optional[RiskLevel]
    current_risk_level: RiskLevel
    reason: str

# GDPR 관련 요청 모델
class GDPRRequest(BaseModel):
    player_id: str
    request_type: Literal["access", "rectification", "erasure", "restriction", "portability", "objection"]
    request_details: Optional[str] = None

# GDPR 응답 모델
class GDPRResponse(BaseModel):
    request_id: str
    status: Literal["received", "processing", "completed", "rejected"]
    message: str
    completion_estimate: Optional[str] = None 