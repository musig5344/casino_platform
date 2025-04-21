from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any

from backend.database import get_db
from backend.models.aml import AMLAlert, AMLTransaction, AMLRiskProfile, AlertType, AlertStatus, AlertSeverity
from backend.schemas.aml import (
    AMLAlertCreate, AMLAlertResponse, AMLAlertDetailResponse, AlertStatusUpdate,
    AMLTransactionAnalysis, AMLRiskProfileResponse, AMLReportRequest, AMLReportResponse,
    ReportingJurisdiction
)
from backend.services.aml_service import AMLService
from backend.utils.auth import get_current_user, get_current_player_id, get_admin_user
from backend.models.wallet import Transaction
from backend.utils.kafka_producer import send_kafka_message

import logging
from datetime import datetime

router = APIRouter(prefix="/aml", tags=["AML"])

logger = logging.getLogger(__name__)

def _convert_to_reporting_jurisdiction(jurisdiction_str):
    """
    문자열 형태의 관할을 ReportingJurisdiction Enum 값으로 변환
    
    Args:
        jurisdiction_str: 관할 문자열
        
    Returns:
        ReportingJurisdiction: 변환된 Enum 값
    """
    if not jurisdiction_str:
        return ReportingJurisdiction.MALTA  # 기본값
        
    # 대문자로 변환
    jurisdiction_str = jurisdiction_str.upper()
    
    # 매핑 테이블
    mapping = {
        "MT": ReportingJurisdiction.MALTA,
        "MALTA": ReportingJurisdiction.MALTA,
        "PH": ReportingJurisdiction.PHILIPPINES,
        "PHILIPPINES": ReportingJurisdiction.PHILIPPINES,
        "CW": ReportingJurisdiction.CURACAO,
        "CURACAO": ReportingJurisdiction.CURACAO,
        "GI": ReportingJurisdiction.GIBRALTAR,
        "GIBRALTAR": ReportingJurisdiction.GIBRALTAR,
        "IM": ReportingJurisdiction.ISLE_OF_MAN,
        "ISLE_OF_MAN": ReportingJurisdiction.ISLE_OF_MAN,
        "ALDERNEY": ReportingJurisdiction.ALDERNEY,
        "GG": ReportingJurisdiction.ALDERNEY,
        "KAHNAWAKE": ReportingJurisdiction.KAHNAWAKE,
        "CA": ReportingJurisdiction.KAHNAWAKE,
        "DEFAULT": ReportingJurisdiction.MALTA
    }
    
    # 매핑된 Enum 값 반환
    return mapping.get(jurisdiction_str, ReportingJurisdiction.MALTA)

@router.post("/analyze-transaction/{transaction_id}", response_model=AMLTransactionAnalysis)
async def analyze_transaction(
    transaction_id: str,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    트랜잭션을 AML 관점에서 분석합니다 (관리자 전용).
    """
    aml_service = AMLService(db)
    
    try:
        # 트랜잭션 존재 확인
        transaction = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"트랜잭션 ID {transaction_id}를 찾을 수 없습니다"
            )
        
        # 여기서 직접 AML 분석을 수행합니다
        is_pep = False
        is_high_risk_jurisdiction = False
        risk_score = 25.0  # 기본 위험 점수
        
        # 메타데이터 로깅
        logger.info(f"Transaction metadata: {transaction.transaction_metadata}")
        
        # PEP(정치적 노출 인물) 확인
        if transaction.transaction_metadata and 'is_pep' in transaction.transaction_metadata:
            if transaction.transaction_metadata['is_pep'] in [True, 'true', 'True', 1, '1']:
                is_pep = True
                risk_score += 40
                logger.info(f"PEP detected in transaction {transaction_id}")
        
        # 고위험 국가 확인
        high_risk_countries = ["AF", "BY", "BI", "CF", "CD", "KP", "ER", "IR", "IQ", "LY", "ML", "MM", "NI", "PK", "RU", "SO", "SS", "SD", "SY", "VE", "YE", "ZW"]
        
        if transaction.transaction_metadata and 'country' in transaction.transaction_metadata:
            country = transaction.transaction_metadata['country']
            if isinstance(country, str) and country.upper() in high_risk_countries:
                is_high_risk_jurisdiction = True
                risk_score += 35
                logger.info(f"High-risk country detected in transaction {transaction_id}: {country}")
        
        if transaction.transaction_metadata and 'high_risk_jurisdiction' in transaction.transaction_metadata:
            if transaction.transaction_metadata['high_risk_jurisdiction'] in [True, 'true', 'True', 1, '1']:
                is_high_risk_jurisdiction = True
                risk_score += 35
                logger.info(f"High-risk jurisdiction flag detected in transaction {transaction_id}")
        
        # 큰 금액 거래 확인
        is_large_transaction = transaction.amount >= 1000000  # 예: 1백만 이상
        if is_large_transaction:
            risk_score += 25
            logger.info(f"Large transaction detected: {transaction.amount}")
        
        # 분석 결과 구성
        analysis_result = {
            "transaction_id": transaction.transaction_id,
            "player_id": transaction.player_id,
            "is_politically_exposed_person": is_pep,
            "is_high_risk_jurisdiction": is_high_risk_jurisdiction,
            "is_large_transaction": is_large_transaction,
            "is_unusual_pattern": False,  # 이 예에서는 단순화
            "is_structuring_attempt": False,  # 이 예에서는 단순화
            "risk_score": risk_score,
            "risk_factors": {
                "is_pep": is_pep, 
                "is_high_risk_country": is_high_risk_jurisdiction,
                "is_large_amount": is_large_transaction
            },
            "needs_regulatory_report": risk_score >= 50
        }
        
        # 알림 생성
        alert_id = None
        if is_pep or is_high_risk_jurisdiction or is_large_transaction:
            try:
                # 알림 생성 데이터 준비
                if is_pep:
                    alert_type = "PEP_MATCH"
                    alert_severity = AlertSeverity.HIGH
                    description = "정치적 노출 인물(PEP)과 관련된 거래가 감지되었습니다"
                elif is_high_risk_jurisdiction:
                    alert_type = "HIGH_RISK_COUNTRY"
                    alert_severity = AlertSeverity.HIGH
                    description = "고위험 국가/관할지역과 관련된 거래가 감지되었습니다"
                else:  # 큰 금액 거래
                    alert_type = "LARGE_TRANSACTION"
                    alert_severity = AlertSeverity.MEDIUM
                    description = "대규모 거래가 감지되었습니다"
                
                # AML 알림 객체 생성
                alert = AMLAlert(
                    player_id=transaction.player_id,
                    alert_type=alert_type,
                    alert_severity=alert_severity,
                    alert_status=AlertStatus.NEW,
                    description=description,
                    detection_rule="automatic_detection",
                    risk_score=risk_score,
                    transaction_ids=[transaction.transaction_id],
                    transaction_details={
                        "amount": float(transaction.amount),
                        "transaction_type": transaction.transaction_type,
                        "created_at": transaction.created_at.isoformat() if transaction.created_at else None,
                        "metadata": transaction.transaction_metadata
                    }
                )
                
                db.add(alert)
                db.commit()
                db.refresh(alert)
                
                alert_id = alert.id
                analysis_result["alert"] = alert_id
                logger.info(f"Created alert ID {alert_id} for transaction {transaction_id}")
            except Exception as e:
                logger.error(f"Error creating alert: {str(e)}")
                db.rollback()
        
        # AML 서비스에 분석 요청 (백그라운드로)
        try:
            analysis_service_result = await aml_service.analyze_transaction(transaction_id, user.get("id"))
            if analysis_service_result:
                # 서비스 결과가 있으면 일부 필드 업데이트
                analysis_result.update({
                    "alert": analysis_service_result.get("alert"),
                    "risk_factors": analysis_service_result.get("risk_factors", analysis_result["risk_factors"])
                })
        except Exception as e:
            logger.error(f"Error in AML service analysis: {str(e)}")
        
        # 분석 결과를 Kafka로 전송 (비동기)
        background_tasks.add_task(
            send_kafka_message,
            "aml_transaction_analysis",
            {
                "transaction_id": transaction_id,
                "player_id": transaction.player_id,
                "analysis_result": analysis_result,
                "analyzed_at": datetime.now().isoformat()
            }
        )
        
        # 응답 변환
        return AMLTransactionAnalysis(
            transaction_id=transaction_id,
            player_id=transaction.player_id,
            is_large_transaction=analysis_result["is_large_transaction"],
            is_suspicious_pattern=analysis_result["is_unusual_pattern"],
            is_unusual_for_player=analysis_result.get("is_unusual_for_player", False),
            is_structuring_attempt=analysis_result["is_structuring_attempt"],
            is_regulatory_report_required=analysis_result["needs_regulatory_report"],
            risk_score=analysis_result["risk_score"],
            risk_factors=analysis_result["risk_factors"],
            regulatory_threshold_currency="KRW",  # 기본값
            regulatory_threshold_amount=1000000.0,  # 기본값
            reporting_jurisdiction=_convert_to_reporting_jurisdiction("MALTA"),  # 기본값
            analysis_version="1.0.0",
            analysis_details={
                "is_politically_exposed_person": analysis_result["is_politically_exposed_person"],
                "is_high_risk_jurisdiction": analysis_result["is_high_risk_jurisdiction"],
                "alert_id": analysis_result.get("alert"),
                "analyzed_at": datetime.now().isoformat()
            }
        )
    except HTTPException as e:
        logger.error(f"트랜잭션 분석 중 HTTP 예외: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"트랜잭션 분석 중 오류 발생: {str(e)}")
        # 오류 세부 정보 로깅
        import traceback
        logger.error(traceback.format_exc())
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"트랜잭션 분석 중 오류가 발생했습니다: {str(e)[:100]}"
        )

@router.post("/alerts", response_model=AMLAlertResponse)
async def create_aml_alert(
    alert_data: AMLAlertCreate,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    AML 알림을 수동으로 생성합니다 (관리자 전용).
    """
    aml_service = AMLService(db)
    
    try:
        alert = await aml_service.create_alert(alert_data)
        
        return AMLAlertResponse(
            id=alert.id,
            player_id=alert.player_id,
            alert_type=alert.alert_type,
            alert_severity=alert.alert_severity,
            alert_status=alert.alert_status,
            description=alert.description,
            detection_rule=alert.detection_rule,
            risk_score=alert.risk_score,
            created_at=alert.created_at,
            reviewed_by=alert.reviewed_by,
            review_notes=alert.review_notes,
            reviewed_at=alert.reviewed_at
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"알림 생성 중 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="알림 생성 중 오류가 발생했습니다"
        )

@router.get("/alerts", response_model=List[AMLAlertResponse])
async def get_alerts(
    status: Optional[AlertStatus] = None,
    severity: Optional[AlertSeverity] = None,
    player_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    AML 알림 목록을 조회합니다 (관리자 전용).
    """
    try:
        query = db.query(AMLAlert)
        
        # 필터 적용
        if status:
            query = query.filter(AMLAlert.alert_status == status)
        if severity:
            query = query.filter(AMLAlert.alert_severity == severity)
        if player_id:
            query = query.filter(AMLAlert.player_id == player_id)
        
        # 정렬 및 페이지네이션
        total_count = query.count()
        alerts = query.order_by(AMLAlert.created_at.desc()).offset(offset).limit(limit).all()
        
        # 응답 변환
        result = []
        for alert in alerts:
            try:
                alert_type_value = str(alert.alert_type) if alert.alert_type else "unusual_pattern"
                # AlertType Enum 타입에 맞게 변환
                if hasattr(AlertType, alert_type_value.upper()):
                    alert_type = getattr(AlertType, alert_type_value.upper())
                else:
                    alert_type = AlertType.UNUSUAL_PATTERN
                
                result.append(
                    AMLAlertResponse(
                        id=alert.id,
                        player_id=alert.player_id,
                        alert_type=alert_type,
                        alert_severity=alert.alert_severity,
                        alert_status=alert.alert_status,
                        description=alert.description,
                        detection_rule=alert.detection_rule or "unknown",
                        risk_score=alert.risk_score,
                        created_at=alert.created_at,
                        reviewed_by=alert.reviewed_by,
                        review_notes=alert.review_notes,
                        reviewed_at=alert.reviewed_at
                    )
                )
            except Exception as e:
                logger.error(f"알림 ID {alert.id} 변환 중 오류: {str(e)}")
                # 오류가 있는 알림은 건너뛰기
                continue
        
        return result
        
    except Exception as e:
        logger.error(f"알림 목록 조회 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # 빈 목록 반환
        return []

@router.get("/alerts/{alert_id}", response_model=AMLAlertDetailResponse)
async def get_alert_detail(
    alert_id: int,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    AML 알림 상세 정보를 조회합니다 (관리자 전용).
    """
    alert = db.query(AMLAlert).filter(AMLAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"알림 ID {alert_id}를 찾을 수 없습니다"
        )
    
    return AMLAlertDetailResponse(
        id=alert.id,
        player_id=alert.player_id,
        alert_type=alert.alert_type,
        alert_severity=alert.alert_severity,
        alert_status=alert.alert_status,
        description=alert.description,
        detection_rule=alert.detection_rule,
        risk_score=alert.risk_score,
        created_at=alert.created_at,
        reviewed_by=alert.reviewed_by,
        review_notes=alert.review_notes,
        reviewed_at=alert.reviewed_at,
        transaction_ids=alert.transaction_ids,
        transaction_details=alert.transaction_details,
        alert_data=alert.alert_data,
        reported_at=alert.reported_at,
        report_reference=alert.report_reference
    )

@router.put("/alerts/{alert_id}/status", response_model=AMLAlertResponse)
async def update_alert_status(
    alert_id: int,
    update_data: AlertStatusUpdate,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    AML 알림 상태를 업데이트합니다 (관리자 전용).
    """
    aml_service = AMLService(db)
    
    # alert_id 확인 및 설정
    update_data.alert_id = alert_id
    
    # 사용자 아이디 설정
    if not update_data.reviewed_by:
        update_data.reviewed_by = user.get("username") or user.get("player_id")
    
    try:
        alert = aml_service.update_alert_status(update_data)
        
        # 알림이 보고됨으로 변경된 경우, 이벤트 발행
        if update_data.status == AlertStatus.REPORTED:
            background_tasks.add_task(
                send_kafka_message,
                "aml_alert_reported",
                {
                    "alert_id": alert.id,
                    "player_id": alert.player_id,
                    "alert_type": str(alert.alert_type),
                    "severity": str(alert.alert_severity),
                    "risk_score": alert.risk_score,
                    "transaction_ids": alert.transaction_ids,
                    "reported_at": alert.reported_at.isoformat(),
                    "report_reference": alert.report_reference,
                    "reviewed_by": alert.reviewed_by
                }
            )
        
        return AMLAlertResponse(
            id=alert.id,
            player_id=alert.player_id,
            alert_type=alert.alert_type,
            alert_severity=alert.alert_severity,
            alert_status=alert.alert_status,
            description=alert.description,
            detection_rule=alert.detection_rule,
            risk_score=alert.risk_score,
            created_at=alert.created_at,
            reviewed_by=alert.reviewed_by,
            review_notes=alert.review_notes,
            reviewed_at=alert.reviewed_at
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"알림 상태 업데이트 중 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="알림 상태 업데이트 중 오류가 발생했습니다"
        )

@router.get("/player/{player_id}/risk-profile", response_model=AMLRiskProfileResponse)
async def get_player_risk_profile(
    player_id: str,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    플레이어의 AML 위험 프로필을 조회합니다 (관리자 전용).
    """
    aml_service = AMLService(db)
    
    # 플레이어 위험 프로필 조회
    risk_profile = aml_service._get_or_create_risk_profile(player_id)
    
    return AMLRiskProfileResponse(
        player_id=risk_profile.player_id,
        overall_risk_score=risk_profile.overall_risk_score,
        deposit_risk_score=risk_profile.deposit_risk_score,
        withdrawal_risk_score=risk_profile.withdrawal_risk_score,
        gameplay_risk_score=risk_profile.gameplay_risk_score,
        is_active=risk_profile.is_active,
        last_deposit_at=risk_profile.last_deposit_at,
        last_withdrawal_at=risk_profile.last_withdrawal_at,
        last_played_at=risk_profile.last_played_at,
        deposit_count_7d=risk_profile.deposit_count_7d,
        deposit_amount_7d=risk_profile.deposit_amount_7d,
        withdrawal_count_7d=risk_profile.withdrawal_count_7d,
        withdrawal_amount_7d=risk_profile.withdrawal_amount_7d,
        deposit_count_30d=risk_profile.deposit_count_30d,
        deposit_amount_30d=risk_profile.deposit_amount_30d,
        withdrawal_count_30d=risk_profile.withdrawal_count_30d,
        withdrawal_amount_30d=risk_profile.withdrawal_amount_30d,
        wager_to_deposit_ratio=risk_profile.wager_to_deposit_ratio,
        withdrawal_to_deposit_ratio=risk_profile.withdrawal_to_deposit_ratio,
        risk_factors=risk_profile.risk_factors,
        risk_mitigation=risk_profile.risk_mitigation,
        last_assessment_at=risk_profile.last_assessment_at
    )

@router.get("/high-risk-players", response_model=List[AMLRiskProfileResponse])
async def get_high_risk_players(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    고위험 플레이어 목록을 조회합니다 (관리자 전용).
    """
    aml_service = AMLService(db)
    risk_profiles = aml_service.get_high_risk_players(limit=limit, offset=offset)
    
    return [
        AMLRiskProfileResponse(
            player_id=profile.player_id,
            overall_risk_score=profile.overall_risk_score,
            deposit_risk_score=profile.deposit_risk_score,
            withdrawal_risk_score=profile.withdrawal_risk_score,
            gameplay_risk_score=profile.gameplay_risk_score,
            is_active=profile.is_active,
            last_deposit_at=profile.last_deposit_at,
            last_withdrawal_at=profile.last_withdrawal_at,
            last_played_at=profile.last_played_at,
            deposit_count_7d=profile.deposit_count_7d,
            deposit_amount_7d=profile.deposit_amount_7d,
            withdrawal_count_7d=profile.withdrawal_count_7d,
            withdrawal_amount_7d=profile.withdrawal_amount_7d,
            deposit_count_30d=profile.deposit_count_30d,
            deposit_amount_30d=profile.deposit_amount_30d,
            withdrawal_count_30d=profile.withdrawal_count_30d,
            withdrawal_amount_30d=profile.withdrawal_amount_30d,
            wager_to_deposit_ratio=profile.wager_to_deposit_ratio,
            withdrawal_to_deposit_ratio=profile.withdrawal_to_deposit_ratio,
            risk_factors=profile.risk_factors,
            risk_mitigation=profile.risk_mitigation,
            last_assessment_at=profile.last_assessment_at
        )
        for profile in risk_profiles
    ]

@router.get("/player/{player_id}/alerts", response_model=List[AMLAlertResponse])
async def get_player_alerts(
    player_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    플레이어 관련 알림 목록을 조회합니다 (관리자 전용).
    """
    try:
        aml_service = AMLService(db)
        alerts = aml_service.get_player_alerts(player_id=player_id, limit=limit, offset=offset)
        
        result = []
        for alert in alerts:
            try:
                alert_type_value = str(alert.alert_type) if alert.alert_type else "unusual_pattern"
                # AlertType Enum 타입에 맞게 변환
                if hasattr(AlertType, alert_type_value.upper()):
                    alert_type = getattr(AlertType, alert_type_value.upper())
                else:
                    alert_type = AlertType.UNUSUAL_PATTERN
                    
                result.append(
                    AMLAlertResponse(
                        id=alert.id,
                        player_id=alert.player_id,
                        alert_type=alert_type,
                        alert_severity=alert.alert_severity,
                        alert_status=alert.alert_status,
                        description=alert.description,
                        detection_rule=alert.detection_rule or "unknown",
                        risk_score=alert.risk_score,
                        created_at=alert.created_at,
                        reviewed_by=alert.reviewed_by,
                        review_notes=alert.review_notes,
                        reviewed_at=alert.reviewed_at
                    )
                )
            except Exception as e:
                logger.error(f"플레이어 알림 ID {alert.id} 변환 중 오류: {str(e)}")
                # 오류가 있는 알림은 건너뛰기
                continue
        
        return result
        
    except Exception as e:
        logger.error(f"플레이어 알림 목록 조회 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # 빈 목록 반환
        return []

@router.post("/report", response_model=AMLReportResponse)
async def create_aml_report(
    report_request: AMLReportRequest,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    AML 보고서를 생성합니다 (관리자 전용).
    규제 기관에 제출하기 위한 보고서 (STR, CTR, SAR 등)
    """
    # 관련 알림 존재 확인 (선택 사항)
    if report_request.alert_id:
        alert = db.query(AMLAlert).filter(AMLAlert.id == report_request.alert_id).first()
        if not alert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"알림 ID {report_request.alert_id}를 찾을 수 없습니다"
            )
    
    # 플레이어 존재 확인
    from backend.models.user import Player
    player = db.query(Player).filter(Player.id == report_request.player_id).first()
    if not player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"플레이어 ID {report_request.player_id}를 찾을 수 없습니다"
        )
    
    # 보고서 ID 생성
    import uuid
    report_id = str(uuid.uuid4())
    
    # 보고서 작성 및 알림 (비동기)
    background_tasks.add_task(
        send_kafka_message,
        "aml_report_created",
        {
            "report_id": report_id,
            "player_id": report_request.player_id,
            "report_type": report_request.report_type,
            "jurisdiction": str(report_request.jurisdiction),
            "created_at": datetime.now().isoformat(),
            "alert_id": report_request.alert_id,
            "transaction_ids": report_request.transaction_ids,
            "notes": report_request.notes,
            "created_by": user.get("username") or user.get("player_id")
        }
    )
    
    # TODO: 실제 구현에서는 실제 규제 보고서 생성 및 보관
    
    return AMLReportResponse(
        report_id=report_id,
        player_id=report_request.player_id,
        report_type=report_request.report_type,
        jurisdiction=report_request.jurisdiction,
        created_at=datetime.now(),
        status="draft"
    ) 