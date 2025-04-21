from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.sql import select, and_, or_, func
from fastapi import HTTPException, status
from datetime import datetime, date, timedelta

from backend.models.kyc import KYCVerification, RiskAssessment, VerificationStatus, RiskLevel
from backend.models.user import Player
from backend.schemas.kyc import KYCVerificationRequest, DocumentInfo
from backend.utils.encryption import encryption_manager
import logging
import uuid
import json
import requests
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

class KYCService:
    """
    KYC(Know Your Customer) 서비스 클래스
    사용자 신원 확인 및 위험 평가를 처리
    """
    
    def __init__(self, db: Session):
        """
        KYC 서비스 초기화
        
        Args:
            db: 데이터베이스 세션
        """
        self.db = db
        self.HIGH_RISK_COUNTRIES = [
            "AF", "BY", "BI", "CF", "KP", "CD", "ER", "IR", "IQ", "LY", 
            "ML", "MM", "NI", "SO", "SS", "SD", "SY", "VE", "YE", "ZW"
        ]
        
        # 금융조치기구(FATF) 지정 고위험 국가 및 제재국
        self.SANCTIONED_COUNTRIES = ["KP", "IR"]
    
    async def create_verification(self, player_id: str, verification_data: KYCVerificationRequest) -> KYCVerification:
        """
        새 KYC 검증 생성
        
        Args:
            player_id: 플레이어 ID
            verification_data: KYC 검증 요청 데이터
            
        Returns:
            KYCVerification: 생성된 KYC 검증 객체
        """
        # 플레이어 존재 여부 확인
        player = self.db.query(Player).filter(Player.id == player_id).first()
        if not player:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"플레이어 ID {player_id}를 찾을 수 없습니다"
            )
        
        # 이미 KYC 인증이 진행 중인지 확인
        existing_verification = self.db.query(KYCVerification).filter(
            KYCVerification.player_id == player_id,
            KYCVerification.verification_status.in_([VerificationStatus.PENDING, VerificationStatus.APPROVED])
        ).first()
        
        if existing_verification:
            # 이미 승인된 경우
            if existing_verification.verification_status == VerificationStatus.APPROVED:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="이미 승인된 KYC 인증이 있습니다"
                )
            # 검토 중인 경우
            elif existing_verification.verification_status == VerificationStatus.PENDING:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="진행 중인 KYC 인증이 있습니다"
                )
        
        # 문서 정보 처리
        doc_info = verification_data.document_info
        
        # 신분증 만료 확인
        doc_expiry_date = datetime.strptime(doc_info.document_expiry_date, "%Y-%m-%d").date()
        if doc_expiry_date <= date.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="만료된 신분증입니다"
            )
        
        # 생년월일 유효성 검증
        birth_date = datetime.strptime(verification_data.date_of_birth, "%Y-%m-%d").date()
        today = date.today()
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
        if age < 18:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="플레이어는 18세 이상이어야 합니다"
            )
            
        # 초기 위험 수준 평가
        initial_risk_level = self._assess_initial_risk_level(verification_data)
        
        # 고위험 국가 및 제재국 확인
        is_high_risk = verification_data.nationality in self.HIGH_RISK_COUNTRIES or verification_data.country in self.HIGH_RISK_COUNTRIES
        is_sanctioned = verification_data.nationality in self.SANCTIONED_COUNTRIES or verification_data.country in self.SANCTIONED_COUNTRIES
        
        # 문서 데이터 암호화
        document_data = {
            "document_type": doc_info.document_type,
            "document_number": doc_info.document_number,
            "document_issue_date": doc_info.document_issue_date,
            "document_expiry_date": doc_info.document_expiry_date,
            "document_issuing_country": doc_info.document_issuing_country
        }
        encrypted_doc_data = encryption_manager.encrypt_document_data(document_data)
        
        # KYC 검증 생성
        kyc_verification = KYCVerification(
            player_id=player_id,
            full_name=verification_data.full_name,
            date_of_birth=verification_data.date_of_birth,
            nationality=verification_data.nationality,
            address=verification_data.address,
            city=verification_data.city,
            postal_code=verification_data.postal_code,
            country=verification_data.country,
            document_type=doc_info.document_type,
            document_number=doc_info.document_number,
            document_issue_date=doc_info.document_issue_date,
            document_expiry_date=doc_info.document_expiry_date,
            document_issuing_country=doc_info.document_issuing_country,
            encrypted_document_data=encrypted_doc_data,
            verification_status=VerificationStatus.PENDING,
            risk_level=initial_risk_level,
            is_high_risk_jurisdiction=is_high_risk,
            is_sanctioned=is_sanctioned
        )
        
        self.db.add(kyc_verification)
        self.db.flush()  # ID 생성을 위해 flush
        
        # 위험 평가 기록 생성
        risk_assessment = RiskAssessment(
            kyc_id=kyc_verification.id,
            current_risk_level=initial_risk_level,
            reason=f"초기 위험 평가 - {'고위험 국가' if is_high_risk else ''} {'제재국' if is_sanctioned else ''}",
            assessor="시스템"
        )
        
        self.db.add(risk_assessment)
        self.db.commit()
        self.db.refresh(kyc_verification)
        
        # 추가 검증 작업 트리거 (비동기 작업으로 처리 가능)
        await self._trigger_additional_verification(kyc_verification.id)
        
        return kyc_verification
    
    def _assess_initial_risk_level(self, verification_data: KYCVerificationRequest) -> RiskLevel:
        """
        초기 위험 수준 평가
        
        Args:
            verification_data: KYC 검증 데이터
            
        Returns:
            RiskLevel: 초기 위험 수준
        """
        # 고위험 국가 확인
        if verification_data.nationality in self.SANCTIONED_COUNTRIES or verification_data.country in self.SANCTIONED_COUNTRIES:
            return RiskLevel.BLOCKED
            
        if verification_data.nationality in self.HIGH_RISK_COUNTRIES or verification_data.country in self.HIGH_RISK_COUNTRIES:
            return RiskLevel.HIGH
        
        # 생년월일 확인
        birth_date = datetime.strptime(verification_data.date_of_birth, "%Y-%m-%d").date()
        today = date.today()
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
        
        # 25세 미만 또는 70세 이상인 경우 중간 위험으로 분류
        if age < 25 or age > 70:
            return RiskLevel.MEDIUM
            
        # 기본값
        return RiskLevel.LOW
    
    async def _trigger_additional_verification(self, kyc_id: int) -> None:
        """
        추가 검증 작업 트리거 (실제 구현은 환경에 따라 다름)
        이 예제에서는 간단한 비동기 함수로 구현
        실제로는 Kafka, RabbitMQ 등의 메시지 큐를 사용할 수 있음
        
        Args:
            kyc_id: KYC 검증 ID
        """
        # 여기서 작업을 큐에 추가하거나 비동기 태스크 시작
        verification = self.db.query(KYCVerification).filter(KYCVerification.id == kyc_id).first()
        if not verification:
            logger.error(f"KYC ID {kyc_id}를 찾을 수 없어 추가 검증을 수행할 수 없습니다")
            return
            
        # PEP 검사 수행 (Politically Exposed Person)
        await self._check_politically_exposed_person(verification)
        
        # 제재 목록 검사
        await self._check_sanctions_list(verification)
        
        # 위험 프로필 업데이트
        self._update_risk_profile(verification)
    
    async def _check_politically_exposed_person(self, verification: KYCVerification) -> None:
        """
        PEP(정치적 주요 인물) 여부 확인
        실제 구현에서는 외부 API를 사용하여 검증
        
        Args:
            verification: KYC 검증 객체
        """
        # 모의 PEP API 호출 - 실제 구현에서는 적절한 API 사용
        try:
            # PEP API 호출 모의
            is_pep = await self._mock_pep_check(verification.full_name, verification.nationality)
            
            # 결과 업데이트
            verification.is_politically_exposed = is_pep
            verification.last_checked_at = datetime.now()
            
            # PEP인 경우 위험 수준 업데이트
            if is_pep and verification.risk_level != RiskLevel.BLOCKED:
                previous_level = verification.risk_level
                verification.risk_level = RiskLevel.HIGH
                
                # 위험 평가 기록 추가
                risk_assessment = RiskAssessment(
                    kyc_id=verification.id,
                    previous_risk_level=previous_level,
                    current_risk_level=RiskLevel.HIGH,
                    reason="정치적 주요 인물(PEP) 검출",
                    assessor="시스템"
                )
                
                self.db.add(risk_assessment)
            
            self.db.commit()
            
        except Exception as e:
            logger.error(f"PEP 확인 중 오류 발생: {str(e)}")
            self.db.rollback()
    
    async def _mock_pep_check(self, name: str, nationality: str) -> bool:
        """
        PEP 확인을 모의하는 함수
        실제 구현에서는 실제 API를 사용
        
        Args:
            name: 확인할 사람의 이름
            nationality: 국적
            
        Returns:
            bool: PEP 여부
        """
        # 이 예제에서는 특정 이름 패턴이나 랜덤 확률로 PEP 여부 결정
        # 특정 테스트 이름으로 항상 PEP로 판정
        if "politician" in name.lower() or "minister" in name.lower() or "president" in name.lower():
            return True
            
        # 특정 고위험 국가의 경우 1% 확률로 PEP로 판정 (테스트용)
        if nationality in self.HIGH_RISK_COUNTRIES:
            import random
            return random.random() < 0.01
            
        return False
    
    async def _check_sanctions_list(self, verification: KYCVerification) -> None:
        """
        제재 목록 확인
        
        Args:
            verification: KYC 검증 객체
        """
        try:
            # 제재 목록 확인 API 호출 모의
            is_sanctioned = await self._mock_sanctions_check(verification.full_name, verification.nationality)
            
            # 결과 업데이트
            verification.is_sanctioned = is_sanctioned
            verification.last_checked_at = datetime.now()
            
            # 제재 대상인 경우 위험 수준 업데이트
            if is_sanctioned:
                previous_level = verification.risk_level
                verification.risk_level = RiskLevel.BLOCKED
                
                # 위험 평가 기록 추가
                risk_assessment = RiskAssessment(
                    kyc_id=verification.id,
                    previous_risk_level=previous_level,
                    current_risk_level=RiskLevel.BLOCKED,
                    reason="제재 목록 대상 검출",
                    assessor="시스템"
                )
                
                self.db.add(risk_assessment)
            
            self.db.commit()
            
        except Exception as e:
            logger.error(f"제재 목록 확인 중 오류 발생: {str(e)}")
            self.db.rollback()
    
    async def _mock_sanctions_check(self, name: str, nationality: str) -> bool:
        """
        제재 목록 확인을 모의하는 함수
        
        Args:
            name: 확인할 사람의 이름
            nationality: 국적
            
        Returns:
            bool: 제재 대상 여부
        """
        # 제재 대상 국가인 경우
        if nationality in self.SANCTIONED_COUNTRIES:
            return True
            
        # 특정 테스트 이름으로 항상 제재 대상으로 판정
        if "sanctioned" in name.lower() or "terrorist" in name.lower():
            return True
            
        return False
    
    def _update_risk_profile(self, verification: KYCVerification) -> None:
        """
        위험 프로필 업데이트
        
        Args:
            verification: KYC 검증 객체
        """
        try:
            # 위험 요소 집계
            risk_factors = []
            
            if verification.is_politically_exposed:
                risk_factors.append("PEP")
                
            if verification.is_sanctioned:
                risk_factors.append("SANCTIONED")
                
            if verification.is_high_risk_jurisdiction:
                risk_factors.append("HIGH_RISK_JURISDICTION")
            
            if risk_factors and verification.verification_status == VerificationStatus.PENDING:
                # 위험 요소가 있지만 차단되지 않은 경우 검토 메모 추가
                verification.verification_notes = f"추가 검토 필요: {', '.join(risk_factors)}"
                self.db.commit()
                
        except Exception as e:
            logger.error(f"위험 프로필 업데이트 중 오류 발생: {str(e)}")
            self.db.rollback()
    
    def get_verification(self, player_id: str) -> Optional[KYCVerification]:
        """
        플레이어 ID로 KYC 검증 조회
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            Optional[KYCVerification]: KYC 검증 객체 또는 None
        """
        return self.db.query(KYCVerification).filter(KYCVerification.player_id == player_id).first()
    
    def update_verification_status(self, kyc_id: int, status: VerificationStatus, notes: Optional[str] = None) -> KYCVerification:
        """
        KYC 검증 상태 업데이트
        
        Args:
            kyc_id: KYC 검증 ID
            status: 새로운 상태
            notes: 추가 메모
            
        Returns:
            KYCVerification: 업데이트된 KYC 검증 객체
        """
        verification = self.db.query(KYCVerification).filter(KYCVerification.id == kyc_id).first()
        if not verification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"KYC ID {kyc_id}를 찾을 수 없습니다"
            )
            
        verification.verification_status = status
        
        if notes:
            verification.verification_notes = notes
            
        if status == VerificationStatus.APPROVED:
            verification.verified_at = datetime.now()
            
        self.db.commit()
        self.db.refresh(verification)
        
        return verification
    
    def handle_gdpr_delete_request(self, player_id: str) -> bool:
        """
        GDPR 삭제 요청 처리
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            bool: 삭제 성공 여부
        """
        try:
            verification = self.db.query(KYCVerification).filter(KYCVerification.player_id == player_id).first()
            if not verification:
                return False
                
            # GDPR 준수를 위한 소프트 삭제 (실제 데이터는 유지하되 일부 필드 익명화)
            verification.deleted_at = datetime.now()
            
            # 민감 정보 익명화
            verification.full_name = encryption_manager.anonymize_data(verification.full_name, keep_start=1, keep_end=1)
            verification.document_number = encryption_manager.anonymize_data(verification.document_number)
            verification.address = encryption_manager.anonymize_data(verification.address)
            verification.city = encryption_manager.anonymize_data(verification.city)
            verification.postal_code = encryption_manager.anonymize_data(verification.postal_code)
            
            # 저장
            self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"GDPR 삭제 요청 처리 중 오류 발생: {str(e)}")
            self.db.rollback()
            return False 