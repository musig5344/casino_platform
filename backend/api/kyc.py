from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any

from backend.database import get_db
from backend.models.kyc import KYCVerification, RiskAssessment, VerificationStatus, RiskLevel
from backend.schemas.kyc import (
    KYCVerificationRequest, KYCVerificationResponse, KYCVerificationDetailResponse,
    DocumentUploadRequest, DocumentUploadResponse, RiskAssessmentResponse, GDPRRequest, GDPRResponse
)
from backend.services.kyc_service import KYCService
from backend.utils.auth import get_current_user, get_current_player_id, get_admin_user
import logging
import uuid
from datetime import datetime, timedelta
import boto3
from fastapi.responses import JSONResponse
from backend.i18n import Translator, get_translator

router = APIRouter(prefix="/kyc", tags=["KYC"])

logger = logging.getLogger(__name__)

@router.post("/verification", response_model=KYCVerificationResponse)
async def create_kyc_verification(
    verification_request: KYCVerificationRequest,
    player_id: str = Depends(get_current_player_id),
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """
    KYC 검증 요청을 생성합니다. (i18n 적용)
    
    - 플레이어 신원 및 주소 정보 제출
    - 신분증 정보 제출
    """
    kyc_service = KYCService(db)
    
    try:
        kyc_verification = await kyc_service.create_verification(player_id, verification_request)
        
        # 응답으로 변환
        return KYCVerificationResponse(
            id=kyc_verification.id,
            player_id=kyc_verification.player_id,
            verification_status=kyc_verification.verification_status,
            risk_level=kyc_verification.risk_level,
            created_at=kyc_verification.created_at,
            updated_at=kyc_verification.updated_at,
            message=translator('kyc.messages.submission_successful')
        )
    except HTTPException as e:
        if isinstance(e.detail, str) and e.detail.startswith('errors.'):
             e.detail=translator(e.detail)
        raise e
    except Exception as e:
        logger.error(f"KYC 검증 생성 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error')
        )

@router.get("/verification", response_model=KYCVerificationResponse)
async def get_kyc_verification_status(
    player_id: str = Depends(get_current_player_id),
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """
    현재 플레이어의 KYC 검증 상태를 조회합니다. (i18n 적용)
    """
    kyc_service = KYCService(db)
    verification = kyc_service.get_verification(player_id)
    
    if not verification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translator('errors.error.kyc_not_found')
        )
    
    # 메시지 결정
    message = ""
    status_key = f'kyc.status.{verification.verification_status.name.lower()}'
    if verification.verification_status == VerificationStatus.REJECTED:
        reason = verification.verification_notes or translator('kyc.messages.no_reason_provided')
        message = translator(f'{status_key}.message', reason=reason)
    else:
        message = translator(f'{status_key}.message')
    
    return KYCVerificationResponse(
        id=verification.id,
        player_id=verification.player_id,
        verification_status=verification.verification_status,
        risk_level=verification.risk_level,
        created_at=verification.created_at,
        updated_at=verification.updated_at,
        message=message
    )

@router.get("/verification/{kyc_id}", response_model=KYCVerificationDetailResponse)
async def get_kyc_verification_detail(
    kyc_id: int,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """
    KYC 검증 상세 정보를 조회합니다 (관리자 전용). (i18n 적용 for errors)
    """
    verification = db.query(KYCVerification).filter(KYCVerification.id == kyc_id).first()
    
    if not verification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translator('errors.error.kyc_id_not_found', kyc_id=kyc_id)
        )
    
    return KYCVerificationDetailResponse(
        id=verification.id,
        player_id=verification.player_id,
        verification_status=verification.verification_status,
        risk_level=verification.risk_level,
        created_at=verification.created_at,
        updated_at=verification.updated_at,
        full_name=verification.full_name,
        nationality=verification.nationality,
        date_of_birth=verification.date_of_birth,
        document_type=verification.document_type,
        document_number=verification.document_number,
        document_expiry_date=verification.document_expiry_date,
        is_politically_exposed=verification.is_politically_exposed,
        is_sanctioned=verification.is_sanctioned,
        is_high_risk_jurisdiction=verification.is_high_risk_jurisdiction,
        verification_notes=verification.verification_notes,
        last_checked_at=verification.last_checked_at,
        verified_at=verification.verified_at
    )

@router.put("/verification/{kyc_id}/status", response_model=KYCVerificationResponse)
async def update_kyc_verification_status(
    kyc_id: int,
    status: VerificationStatus,
    notes: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """
    KYC 검증 상태를 업데이트합니다 (관리자 전용). (i18n 적용 for errors/messages)
    """
    kyc_service = KYCService(db)
    try:
        verification = kyc_service.update_verification_status(kyc_id, status, notes)
        
        status_name = translator(f'kyc.status.{status.name.lower()}.name', status.name)
        message = translator('kyc.messages.status_updated', status=status_name)
        
        return KYCVerificationResponse(
            id=verification.id,
            player_id=verification.player_id,
            verification_status=verification.verification_status,
            risk_level=verification.risk_level,
            created_at=verification.created_at,
            updated_at=verification.updated_at,
            message=message
        )
    except HTTPException as e:
        if isinstance(e.detail, str) and e.detail.startswith('errors.'):
             e.detail=translator(e.detail, kyc_id=kyc_id)
        raise e
    except Exception as e:
        logger.error(f"Error updating KYC status for {kyc_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error')
        )

@router.post("/document/upload", response_model=DocumentUploadResponse)
async def get_document_upload_url(
    upload_request: DocumentUploadRequest,
    player_id: str = Depends(get_current_player_id),
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """
    문서 업로드를 위한 미리 서명된 URL을 생성합니다. (i18n 적용)
    """
    kyc_service = KYCService(db)
    verification = kyc_service.get_verification(player_id)
    
    if not verification or verification.verification_status not in [VerificationStatus.PENDING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=translator('errors.error.kyc_not_pending')
        )
    
    try:
        s3_client = boto3.client(
            's3',
            region_name='eu-west-1',
            aws_access_key_id='YOUR_ACCESS_KEY',
            aws_secret_access_key='YOUR_SECRET_KEY'
        )
        
        bucket_name = 'your-kyc-documents-bucket'
        document_id = str(uuid.uuid4())
        file_key = f"kyc/{player_id}/{verification.id}/{document_id}/{upload_request.document_type}_{upload_request.document_side}.{upload_request.file_name.split('.')[-1]}"
        
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': bucket_name, 'Key': file_key, 'ContentType': upload_request.content_type},
            ExpiresIn=3600
        )
        
        return DocumentUploadResponse(
            upload_url=presigned_url,
            document_id=document_id,
            expires_at=(datetime.now() + timedelta(hours=1)).isoformat()
        )
    except Exception as e:
        logger.error(f"문서 업로드 URL 생성 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.upload_url_generation_failed')
        )
        
@router.get("/risk-assessments/{kyc_id}", response_model=List[RiskAssessmentResponse])
async def get_risk_assessments(
    kyc_id: int,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """
    KYC 위험 평가 이력을 조회합니다 (관리자 전용). (i18n 적용 for errors)
    """
    verification = db.query(KYCVerification).filter(KYCVerification.id == kyc_id).first()
    if not verification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translator('errors.error.kyc_id_not_found', kyc_id=kyc_id)
        )
    
    try:
        assessments = db.query(RiskAssessment).filter(
            RiskAssessment.kyc_id == kyc_id
        ).order_by(RiskAssessment.assessment_date.desc()).all()
        
        return [
            RiskAssessmentResponse(
                id=assessment.id,
                kyc_id=assessment.kyc_id,
                assessment_date=assessment.assessment_date,
                previous_risk_level=assessment.previous_risk_level,
                current_risk_level=assessment.current_risk_level,
                reason=assessment.reason
            )
            for assessment in assessments
        ]
    except Exception as e:
        logger.error(f"Error fetching risk assessments for KYC ID {kyc_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error')
        )

@router.post("/gdpr", response_model=GDPRResponse)
async def submit_gdpr_request(
    gdpr_request: GDPRRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """
    GDPR 관련 요청을 제출합니다.
    """
    # 본인 확인 (자신의 데이터에 대한 요청인지)
    if user.get("player_id") != gdpr_request.player_id and not user.get("is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="다른 사용자의 GDPR 요청을 제출할 권한이 없습니다"
        )
    
    # 요청 유형에 따른 처리
    request_id = str(uuid.uuid4())
    message = "요청이 접수되었습니다"
    status_value = "received"
    completion_estimate = (datetime.now() + timedelta(days=30)).isoformat()
    
    # 데이터 삭제 요청의 경우 즉시 처리
    if gdpr_request.request_type == "erasure":
        kyc_service = KYCService(db)
        success = kyc_service.handle_gdpr_delete_request(gdpr_request.player_id)
        
        if success:
            message = "데이터가 성공적으로 익명화되었습니다"
            status_value = "completed"
            completion_estimate = datetime.now().isoformat()
        else:
            message = "데이터 삭제에 실패했습니다"
            status_value = "rejected"
    
    # TODO: 다른 GDPR 요청 유형 처리 (접근, 정정, 이동성 등)
    # 실제 구현에서는 Kafka 등을 통해 비동기 처리
    
    return GDPRResponse(
        request_id=request_id,
        status=status_value,
        message=message,
        completion_estimate=completion_estimate
    ) 