from typing import Optional, Dict, Any, List, Tuple, Union
from sqlalchemy.orm import Session
from sqlalchemy.sql import select, and_, or_, func, text
from fastapi import HTTPException, status
from datetime import datetime, date, timedelta
import json
import uuid
import logging
import asyncio
from decimal import Decimal
import traceback

from backend.models.aml import AMLAlert, AMLTransaction, AMLRiskProfile, AlertType, AlertStatus, AlertSeverity
from backend.models.wallet import Transaction, Wallet
from backend.models.user import Player
from backend.schemas.aml import AMLAlertCreate, AlertStatusUpdate, ReportingJurisdiction
from backend.utils.encryption import encryption_manager
from backend.config.settings import get_settings

logger = logging.getLogger(__name__)

class AMLService:
    """
    AML(Anti-Money Laundering) 서비스 클래스
    자금세탁방지 및 이상거래 탐지 관련 기능 제공
    """
    
    def __init__(self, db: Session):
        """
        AML 서비스 초기화
        
        Args:
            db: 데이터베이스 세션
        """
        self.db = db
        self.settings = get_settings()
        
        # 관할별 규제 임계값 (Key: 관할, Value: 통화별 임계값)
        self.jurisdiction_thresholds = {
            ReportingJurisdiction.MALTA: {
                "EUR": 2000.0,  # 유로화 기준 2,000 유로
                "USD": 2200.0,  # 달러 기준 2,200 달러
                "GBP": 1700.0,  # 파운드 기준 1,700 파운드
                "DEFAULT": 2000.0  # 기본값
            },
            ReportingJurisdiction.PHILIPPINES: {
                "PHP": 500000.0,  # 필리핀 페소 기준 500,000 페소
                "USD": 10000.0,   # 달러 기준 10,000 달러
                "DEFAULT": 10000.0 # 기본값 (USD 기준)
            },
            ReportingJurisdiction.CURACAO: {
                "USD": 5000.0,   # 달러 기준 5,000 달러
                "EUR": 4500.0,   # 유로화 기준 4,500 유로
                "DEFAULT": 5000.0 # 기본값 (USD 기준)
            },
            "DEFAULT": {  # 기본 관할 (어떤 관할에도 해당하지 않을 경우)
                "USD": 10000.0,   # 달러 기준 10,000 달러
                "EUR": 9500.0,    # 유로화 기준 9,500 유로
                "DEFAULT": 10000.0 # 기본값 (USD 기준)
            }
        }
        
        # 분석 모듈 버전
        self.analysis_version = "1.0.0"
    
    async def analyze_transaction(self, transaction_id: str, user_id: str = None):
        """
        트랜잭션을 분석하여 의심스러운 활동이 있는지 확인합니다.
        """
        try:
            # AMLTransaction에서 검색하는 대신 Transaction 모델에서 직접 조회
            transaction = self.db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
            if not transaction:
                logging.error(f"Transaction {transaction_id} not found")
                return None

            logging.info(f"Analyzing transaction {transaction_id}")
            
            # 플레이어 정보 가져오기
            player = self.db.query(Player).filter(Player.id == transaction.player_id).first()
            if not player:
                logging.error(f"Player {transaction.player_id} not found")
                return None
                
            # 위험 프로필 가져오기 또는 새로 생성
            risk_profile = self._get_or_create_risk_profile(transaction.player_id)
            if not risk_profile:
                logging.error(f"Could not get or create risk profile for player {transaction.player_id}")
                return None
                
            # 거래 유형에 따라 금액 설정
            amount = transaction.amount if transaction.transaction_type == "deposit" else -transaction.amount
                
            # 알림 생성 여부 플래그
            create_alert = False
            alert_type = None
            severity = None
            description = None
            
            # 거래 위험 점수 계산 (기본값 0)
            risk_score = 0
            
            # 정치적 노출 인물(PEP) 확인 - 플레이어 속성과 트랜잭션 메타데이터 모두 확인
            is_politically_exposed_person = False
            
            # 로깅 추가 - 트랜잭션 메타데이터 출력
            logging.info(f"Transaction metadata: {transaction.transaction_metadata}")
            logging.info(f"Player attributes: {vars(player)}")
            
            # 플레이어 속성에서 PEP 상태 확인
            if hasattr(player, 'is_pep') and player.is_pep:
                is_politically_exposed_person = True
                logging.info(f"Player {player.id} is PEP based on player attribute is_pep")
            
            # 트랜잭션 메타데이터에서 PEP 상태 확인
            if transaction.transaction_metadata:
                logging.info(f"Checking PEP status in metadata: {transaction.transaction_metadata}")
                # is_pep 키 확인
                if 'is_pep' in transaction.transaction_metadata:
                    logging.info(f"is_pep found in metadata: {transaction.transaction_metadata['is_pep']}")
                    if transaction.transaction_metadata['is_pep'] in [True, 'true', 'True', 1, '1']:
                        is_politically_exposed_person = True
                        logging.info(f"Transaction {transaction.transaction_id} is related to PEP based on is_pep metadata")
                
                # is_politically_exposed_person 키 확인
                elif 'is_politically_exposed_person' in transaction.transaction_metadata:
                    logging.info(f"is_politically_exposed_person found in metadata: {transaction.transaction_metadata['is_politically_exposed_person']}")
                    if transaction.transaction_metadata['is_politically_exposed_person'] in [True, 'true', 'True', 1, '1']:
                        is_politically_exposed_person = True
                        logging.info(f"Transaction {transaction.transaction_id} is related to PEP based on is_politically_exposed_person metadata")
                
                # pep_status 키 확인
                elif 'pep_status' in transaction.transaction_metadata:
                    logging.info(f"pep_status found in metadata: {transaction.transaction_metadata['pep_status']}")
                    if transaction.transaction_metadata['pep_status'] in ['politically_exposed_person', 'pep']:
                        is_politically_exposed_person = True
                        logging.info(f"Transaction {transaction.transaction_id} is related to PEP based on pep_status metadata")
            
            # 고위험 관할지역 목록 정의
            high_risk_jurisdictions = [
                "AF", "BY", "BI", "CF", "CD", "KP", "ER", "IR", "IQ", "LY", 
                "ML", "MM", "NI", "PK", "RU", "SO", "SS", "SD", "SY", "VE", 
                "YE", "ZW"
            ]
            
            # 고위험 관할지역 확인 - 플레이어 국가와 트랜잭션 메타데이터 모두 확인
            is_high_risk_jurisdiction = False
            
            # 플레이어 국가 정보 로깅
            logging.info(f"Player country: {player.country if player.country else 'None'}")
            
            # 플레이어 국가 기반 확인
            if player.country and player.country.upper() in high_risk_jurisdictions:
                is_high_risk_jurisdiction = True
                logging.info(f"Player {player.id} is from high-risk country {player.country}")
            
            # 트랜잭션 메타데이터 기반 확인
            if transaction.transaction_metadata:
                logging.info(f"Checking high-risk jurisdiction in metadata: {transaction.transaction_metadata}")
                # country 키 확인
                if 'country' in transaction.transaction_metadata:
                    country_code = transaction.transaction_metadata['country']
                    logging.info(f"Country code found in metadata: {country_code}")
                    if isinstance(country_code, str) and country_code.upper() in high_risk_jurisdictions:
                        is_high_risk_jurisdiction = True
                        logging.info(f"Transaction {transaction.transaction_id} is related to high-risk country {country_code}")
                
                # high_risk_jurisdiction 키 확인
                elif 'high_risk_jurisdiction' in transaction.transaction_metadata:
                    logging.info(f"high_risk_jurisdiction found in metadata: {transaction.transaction_metadata['high_risk_jurisdiction']}")
                    if transaction.transaction_metadata['high_risk_jurisdiction'] in [True, 'true', 'True', 1, '1']:
                        is_high_risk_jurisdiction = True
                        logging.info(f"Transaction {transaction.transaction_id} has high_risk_jurisdiction flag in metadata")
            
            # 대규모 거래 확인
            is_large_transaction = False
            threshold = self._get_threshold_for_currency(player.currency)
            if transaction.amount >= threshold:
                is_large_transaction = True
                risk_score += 25
                logging.info(f"Large transaction detected: {transaction.amount} {player.currency}")
                create_alert = True
                alert_type = AlertType.large_transaction
                severity = AlertSeverity.medium
                description = f"대규모 입금 거래가 감지되었습니다"
            
            # 비정상적인 패턴 확인
            player_transactions = self.db.query(Transaction).filter(
                Transaction.player_id == transaction.player_id
            ).all()
            
            # 구조화 시도 확인
            is_structuring_attempt = self._check_structuring_attempt(player_transactions, transaction)
            if is_structuring_attempt:
                risk_score += 35
                logging.info(f"Potential structuring attempt detected for player {transaction.player_id}")
                create_alert = True
                alert_type = AlertType.structuring_attempt
                severity = AlertSeverity.high
                description = f"구조화 시도가 감지되었습니다"
            
            # 해당 플레이어에 대한 비정상적인 패턴 확인
            is_unusual_pattern = self._check_unusual_pattern(player_transactions, transaction, risk_profile)
            if is_unusual_pattern and not create_alert:  # 다른 알림이 없을 경우에만 비정상 패턴 알림 생성
                risk_score += 25
                logging.info(f"Unusual pattern detected for player {transaction.player_id}")
                create_alert = True
                alert_type = AlertType.unusual_pattern
                severity = AlertSeverity.medium
                description = f"비정상적인 거래 패턴이 감지되었습니다"
            
            # PEP 관련 알림 생성
            if is_politically_exposed_person:
                risk_score += 40
                logging.info(f"Transaction from a politically exposed person: {transaction.player_id}")
                create_alert = True
                alert_type = "PEP_MATCH"  # AlertType에 맞게 수정
                severity = AlertSeverity.HIGH
                description = f"정치적 노출 인물(PEP)과 관련된 거래가 감지되었습니다"
            
            # 고위험 관할지역 관련 알림 생성
            if is_high_risk_jurisdiction:
                risk_score += 35
                logging.info(f"Transaction from a high-risk jurisdiction: {player.country}")
                create_alert = True
                alert_type = "HIGH_RISK_COUNTRY"  # AlertType에 맞게 수정
                severity = AlertSeverity.HIGH
                description = f"고위험 국가/관할지역과 관련된 거래가 감지되었습니다"
            
            # 알림 생성
            alert = None
            if create_alert:
                alert = self._create_alert_from_transaction(
                    transaction=transaction,
                    alert_type=alert_type,
                    severity=severity,
                    description=description
                )
                
            # 위험 프로필 업데이트
            self._update_risk_profile_from_transaction(risk_profile, transaction, risk_score)
            
            # 결과 반환
            result = {
                "transaction_id": transaction.transaction_id,
                "player_id": transaction.player_id,
                "is_politically_exposed_person": is_politically_exposed_person,
                "is_high_risk_jurisdiction": is_high_risk_jurisdiction,
                "is_large_transaction": is_large_transaction,
                "is_unusual_pattern": is_unusual_pattern,
                "is_structuring_attempt": is_structuring_attempt,
                "risk_score": risk_score,
                "risk_factors": {"is_pep": is_politically_exposed_person, "is_high_risk_country": is_high_risk_jurisdiction},
                "alert": alert.id if alert else None,
                "needs_regulatory_report": risk_score >= 50,
                "regulatory_threshold_currency": player.currency,
                "regulatory_threshold_amount": threshold,
                "reporting_jurisdiction": "MALTA"  # 기본값
            }
            
            logging.info(f"Transaction analysis result: {result}")
            return result
        except Exception as e:
            logging.error(f"Error analyzing transaction {transaction_id}: {str(e)}")
            return None
    
    def _get_threshold_for_player(self, player: Player) -> float:
        """
        플레이어별 거래 임계값 조회
        
        Args:
            player: 플레이어 객체
            
        Returns:
            float: 임계값
        """
        # 플레이어 국가 기반으로 관할 결정
        jurisdiction = self._determine_reporting_jurisdiction(player)
        
        # 관할별 임계값 조회
        jurisdiction_config = self.jurisdiction_thresholds.get(jurisdiction, self.jurisdiction_thresholds["DEFAULT"])
        
        # 플레이어 통화별 임계값 조회
        currency = player.currency if player.currency else "DEFAULT"
        threshold = jurisdiction_config.get(currency, jurisdiction_config["DEFAULT"])
        
        return threshold
    
    def _determine_reporting_jurisdiction(self, player: Player) -> str:
        """
        플레이어의 보고 관할 결정
        
        Args:
            player: 플레이어 객체
            
        Returns:
            str: 보고 관할
        """
        # 플레이어 국가 기반으로 관할 결정
        country = player.country.upper() if player.country else "US"
        
        # 관할 매핑
        if country == "MT":
            return ReportingJurisdiction.MALTA
        elif country == "PH":
            return ReportingJurisdiction.PHILIPPINES
        elif country in ["AW", "CW"]:  # 아루바, 퀴라소
            return ReportingJurisdiction.CURACAO
        
        # 기본값
        return "DEFAULT"
    
    def _get_or_create_risk_profile(self, player_id: str) -> AMLRiskProfile:
        """
        플레이어의 위험 프로필 조회 또는 생성
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            AMLRiskProfile: 플레이어의 위험 프로필
        """
        # 기존 프로필 조회
        profile = self.db.query(AMLRiskProfile).filter(AMLRiskProfile.player_id == player_id).first()
        
        # 없으면 생성
        if not profile:
            profile = AMLRiskProfile(
                player_id=player_id,
                overall_risk_score=50.0,  # 초기 위험 점수 (중간)
                deposit_risk_score=50.0,
                withdrawal_risk_score=50.0,
                gameplay_risk_score=50.0,
                is_active=True,
                created_at=datetime.now(),
                last_assessment_at=datetime.now()
            )
            self.db.add(profile)
            self.db.flush()
        
        return profile
    
    async def _check_unusual_pattern(self, transaction: Transaction, risk_profile: AMLRiskProfile) -> Tuple[float, bool]:
        """
        비정상적인 거래 패턴 확인
        
        Args:
            transaction: 거래 객체
            risk_profile: 위험 프로필
            
        Returns:
            Tuple[float, bool]: (위험 점수, 비정상 여부)
        """
        transaction_type = transaction.transaction_type
        amount = float(transaction.amount)
        risk_score = 0.0
        is_unusual = False
        
        # 1. 플레이어의 평균 거래 금액 대비 확인
        avg_amount = await self._get_player_average_transaction_amount(transaction.player_id, transaction_type)
        
        if avg_amount and amount > avg_amount * 3:
            risk_score += 25.0
            is_unusual = True
            
        # 2. 최근 거래 패턴 확인
        recent_transactions = await self._get_recent_transactions(transaction.player_id, transaction_type, limit=5)
        
        if recent_transactions:
            # 갑작스러운 큰 금액의 거래 확인
            recent_max = max([float(tx.amount) for tx in recent_transactions])
            recent_avg = sum([float(tx.amount) for tx in recent_transactions]) / len(recent_transactions)
            
            if amount > recent_max * 2 and amount > recent_avg * 3:
                risk_score += 20.0
                is_unusual = True
                
            # 시간대 이상 확인 (새벽 시간대 등)
            current_hour = transaction.created_at.hour
            if 1 <= current_hour <= 5:  # 새벽 1시~5시
                risk_score += 10.0
        
        # 3. 총 위험 점수 조정
        risk_score = min(60.0, risk_score)  # 최대 60점으로 제한
        
        return risk_score, is_unusual
    
    async def _check_structuring(self, transaction: Transaction, player: Player) -> Tuple[float, bool]:
        """
        구조화(Structuring) 시도 확인 - 임계값 우회를 위한 소액 분할 거래
        
        Args:
            transaction: 거래 객체
            player: 플레이어 객체
            
        Returns:
            Tuple[float, bool]: (위험 점수, 구조화 시도 여부)
        """
        # 임계값 조회
        threshold = self._get_threshold_for_player(player)
        transaction_type = transaction.transaction_type
        risk_score = 0.0
        is_structuring = False
        
        # 1. 24시간 이내 동일 유형의 거래 수와 총액 확인
        start_time_24h = transaction.created_at - timedelta(hours=24)
        
        daily_transactions = self.db.query(Transaction).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == transaction_type,
            Transaction.created_at >= start_time_24h,
            Transaction.created_at <= transaction.created_at,
            Transaction.transaction_id != transaction.transaction_id  # 현재 거래 제외
        ).all()
        
        # 2. 7일 이내 동일 유형의 거래 패턴 확인 (개선된 구조화 감지)
        start_time_7d = transaction.created_at - timedelta(days=7)
        
        weekly_transactions = self.db.query(Transaction).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == transaction_type,
            Transaction.created_at >= start_time_7d,
            Transaction.created_at <= transaction.created_at,
            Transaction.transaction_id != transaction.transaction_id  # 현재 거래 제외
        ).all()
        
        if daily_transactions:
            # 24시간 내 거래 수 확인
            if len(daily_transactions) >= 3:
                risk_score += 15.0
                
            # 총액 확인
            daily_total = sum([float(tx.amount) for tx in daily_transactions]) + float(transaction.amount)
            
            # 총액이 임계값 근처인데 분할 거래로 보이는 경우
            if daily_total >= threshold * 0.8 and daily_total < threshold * 1.1:
                risk_score += 35.0
                is_structuring = True
                
            # 임계값보다 약간 적은 여러 건의 거래가 있는 경우
            threshold_avoidance = [tx for tx in daily_transactions if float(tx.amount) >= threshold * 0.7 and float(tx.amount) < threshold]
            if len(threshold_avoidance) >= 2 or (len(threshold_avoidance) >= 1 and float(transaction.amount) >= threshold * 0.7 and float(transaction.amount) < threshold):
                risk_score += 40.0
                is_structuring = True
        
        # 3. 7일 이내 거래 패턴 분석 (개선된 구조화 감지)
        if weekly_transactions and len(weekly_transactions) > 0:
            weekly_total = sum([float(tx.amount) for tx in weekly_transactions]) + float(transaction.amount)
            weekly_avg = weekly_total / (len(weekly_transactions) + 1)
            
            # 7일 이내 거래가 많고 평균 금액이 임계값의 일정 비율 이상인 경우
            if len(weekly_transactions) >= 10 and weekly_avg > threshold * 0.1:
                risk_score += 20.0
                
                # 7일 이내 거래 횟수가 많고 총액이 임계값에 근접하는 경우
                if len(weekly_transactions) >= 50 and weekly_total > threshold * 0.8:
                    risk_score += 30.0
                    is_structuring = True
                    logging.info(f"대량 거래 구조화 감지: 7일 내 {len(weekly_transactions)}회 거래, 총액 {weekly_total}, 임계값 {threshold}")
            
            # 평균 금액이 매우 낮고 거래 횟수가 많은 경우 (소액 분산)
            if len(weekly_transactions) >= 20 and weekly_avg < threshold * 0.05:
                risk_score += 25.0
                is_structuring = True
                logging.info(f"소액 분산 구조화 감지: 7일 내 {len(weekly_transactions)}회 거래, 평균 {weekly_avg}, 임계값 {threshold}")
        
        # 같은 금액대의 거래가 반복되는 경우
        if weekly_transactions and len(weekly_transactions) >= 5:
            amount_clusters = {}
            for tx in weekly_transactions:
                # 금액을 10% 단위로 클러스터링
                cluster_key = int(float(tx.amount) / (threshold * 0.1))
                amount_clusters[cluster_key] = amount_clusters.get(cluster_key, 0) + 1
            
            # 특정 금액대에 집중된 거래가 있는 경우
            for cluster, count in amount_clusters.items():
                if count >= 5:  # 동일 금액대 5회 이상
                    risk_score += 25.0
                    is_structuring = True
                    cluster_amount = cluster * threshold * 0.1
                    logging.info(f"반복 패턴 구조화 감지: 금액대 {cluster_amount} 부근에 {count}회 거래 집중")
                    break
        
        # 3. 총 위험 점수 조정
        risk_score = min(80.0, risk_score)  # 최대 80점으로 상향 조정
        
        return risk_score, is_structuring
    
    async def _get_player_average_transaction_amount(self, player_id: str, transaction_type: str) -> Optional[float]:
        """
        플레이어의 평균 거래 금액 조회
        
        Args:
            player_id: 플레이어 ID
            transaction_type: 거래 유형
            
        Returns:
            Optional[float]: 평균 거래 금액 또는 None
        """
        # 최근 30일 내 동일 유형의 거래 평균 조회
        start_time = datetime.now() - timedelta(days=30)
        
        result = self.db.query(func.avg(Transaction.amount)).filter(
            Transaction.player_id == player_id,
            Transaction.transaction_type == transaction_type,
            Transaction.created_at >= start_time
        ).scalar()
        
        return float(result) if result else None
    
    async def _get_recent_transactions(self, player_id: str, transaction_type: str, limit: int = 5) -> List[Transaction]:
        """
        최근 거래 내역 조회
        
        Args:
            player_id: 플레이어 ID
            transaction_type: 거래 유형
            limit: 최대 조회 수
            
        Returns:
            List[Transaction]: 최근 거래 목록
        """
        recent_transactions = self.db.query(Transaction).filter(
            Transaction.player_id == player_id,
            Transaction.transaction_type == transaction_type
        ).order_by(Transaction.created_at.desc()).limit(limit).all()
        
        return recent_transactions
    
    def _create_alert_from_transaction(self, transaction, alert_type, severity, description=None, predefined_alert_type=None):
        """
        트랜잭션 분석 결과를 기반으로 알림을 생성합니다.
        
        Args:
            transaction: 트랜잭션 객체 (Transaction)
            alert_type: 알림 유형 (string 또는 AlertType)
            severity: 심각도 (AlertSeverity)
            description: 알림 설명 (선택 사항)
            predefined_alert_type: 미리 정의된 알림 유형 (선택 사항)
            
        Returns:
            AMLAlert 객체 또는 None (오류 시)
        """
        try:
            if not transaction:
                logging.error("Cannot create alert from None transaction")
                return None
                
            logging.info(f"Creating alert for transaction {transaction.transaction_id}, type: {alert_type}, severity: {severity}")
            
            # AlertType enum 처리
            if isinstance(alert_type, str):
                # 문자열을 AlertType Enum으로 변환
                try:
                    alert_type_enum_map = {
                        "LARGE_TRANSACTION": AlertType.LARGE_TRANSACTION,
                        "UNUSUAL_PATTERN": AlertType.UNUSUAL_PATTERN,
                        "STRUCTURING": AlertType.STRUCTURING,
                        "HIGH_RISK_COUNTRY": AlertType.HIGH_RISK_COUNTRY,
                        "SANCTIONS_MATCH": AlertType.SANCTIONS_MATCH,
                        "PEP_MATCH": AlertType.PEP_MATCH,
                        "RAPID_MOVEMENT": AlertType.RAPID_MOVEMENT,
                        "MANUAL": AlertType.MANUAL
                    }
                    
                    alert_type_upper = alert_type.upper()
                    if alert_type_upper in alert_type_enum_map:
                        alert_type_value = alert_type_enum_map[alert_type_upper]
                    else:
                        # 일치하는 Enum 값이 없는 경우 기본값 사용
                        logging.warning(f"알 수 없는 알림 유형: {alert_type}, 기본값 사용")
                        alert_type_value = AlertType.UNUSUAL_PATTERN
                except (KeyError, ValueError):
                    # 일치하는 Enum 값이 없는 경우 기본값 사용
                    logging.warning(f"알 수 없는 알림 유형: {alert_type}, 기본값 사용")
                    alert_type_value = AlertType.UNUSUAL_PATTERN
            else:
                alert_type_value = alert_type
                
            # 알림 객체 생성
            alert = AMLAlert(
                player_id=transaction.player_id,
                alert_type=alert_type_value,
                alert_severity=severity,
                alert_status=AlertStatus.NEW,
                description=description or f"Alert for transaction {transaction.transaction_id}",
                detection_rule="automatic_detection",
                risk_score=50.0,  # 기본 위험 점수
                transaction_ids=[transaction.transaction_id],
                transaction_details={
                    "transaction_id": transaction.transaction_id,
                    "amount": float(transaction.amount),
                    "transaction_type": transaction.transaction_type,
                    "created_at": transaction.created_at.isoformat() if transaction.created_at else None
                }
            )
            
            self.db.add(alert)
            self.db.commit()
            self.db.refresh(alert)
            
            logging.info(f"Alert created successfully: {alert.id}")
            return alert
        except Exception as e:
            logging.error(f"Error creating alert from transaction {transaction.transaction_id if transaction else 'None'}: {str(e)}")
            self.db.rollback()
            return None
    
    async def _update_risk_profile_from_transaction(self, risk_profile: AMLRiskProfile, transaction: Transaction, transaction_risk_score: float) -> None:
        """
        거래 기반으로 위험 프로필 업데이트
        
        Args:
            risk_profile: 위험 프로필
            transaction: 거래 객체
            transaction_risk_score: 거래 위험 점수
        """
        transaction_type = transaction.transaction_type
        amount = float(transaction.amount)
        
        # 1. 마지막 거래 시간 업데이트
        if transaction_type == "deposit":
            risk_profile.last_deposit_at = transaction.created_at
        elif transaction_type == "withdrawal":
            risk_profile.last_withdrawal_at = transaction.created_at
        elif transaction_type in ["bet", "win"]:
            risk_profile.last_played_at = transaction.created_at
        
        # 2. 최근 7일/30일 통계 업데이트
        now = datetime.now()
        days_7_ago = now - timedelta(days=7)
        days_30_ago = now - timedelta(days=30)
        
        # 7일 내 거래 통계 및 금액
        deposit_count_7d = self.db.query(func.count(Transaction.id)).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == "deposit",
            Transaction.created_at >= days_7_ago
        ).scalar() or 0
        
        deposit_amount_7d = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == "deposit",
            Transaction.created_at >= days_7_ago
        ).scalar()
        deposit_amount_7d = float(deposit_amount_7d) if deposit_amount_7d else 0.0
        
        withdrawal_count_7d = self.db.query(func.count(Transaction.id)).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == "withdrawal",
            Transaction.created_at >= days_7_ago
        ).scalar() or 0
        
        withdrawal_amount_7d = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == "withdrawal",
            Transaction.created_at >= days_7_ago
        ).scalar()
        withdrawal_amount_7d = float(withdrawal_amount_7d) if withdrawal_amount_7d else 0.0
        
        # 업데이트
        risk_profile.deposit_count_7d = deposit_count_7d
        risk_profile.deposit_amount_7d = deposit_amount_7d
        risk_profile.withdrawal_count_7d = withdrawal_count_7d
        risk_profile.withdrawal_amount_7d = withdrawal_amount_7d
        
        # 30일 내 거래 통계 및 금액
        deposit_count_30d = self.db.query(func.count(Transaction.id)).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == "deposit",
            Transaction.created_at >= days_30_ago
        ).scalar() or 0
        
        deposit_amount_30d = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == "deposit",
            Transaction.created_at >= days_30_ago
        ).scalar()
        deposit_amount_30d = float(deposit_amount_30d) if deposit_amount_30d else 0.0
        
        withdrawal_count_30d = self.db.query(func.count(Transaction.id)).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == "withdrawal",
            Transaction.created_at >= days_30_ago
        ).scalar() or 0
        
        withdrawal_amount_30d = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == "withdrawal",
            Transaction.created_at >= days_30_ago
        ).scalar()
        withdrawal_amount_30d = float(withdrawal_amount_30d) if withdrawal_amount_30d else 0.0
        
        # 업데이트
        risk_profile.deposit_count_30d = deposit_count_30d
        risk_profile.deposit_amount_30d = deposit_amount_30d
        risk_profile.withdrawal_count_30d = withdrawal_count_30d
        risk_profile.withdrawal_amount_30d = withdrawal_amount_30d
        
        # 3. 비율 계산 - 베팅 대 입금 비율
        total_bet = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == "bet",
            Transaction.created_at >= days_30_ago
        ).scalar()
        total_bet = float(total_bet) if total_bet else 0.0
        
        total_win = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.player_id == transaction.player_id,
            Transaction.transaction_type == "win",
            Transaction.created_at >= days_30_ago
        ).scalar()
        total_win = float(total_win) if total_win else 0.0
        
        # 베팅 대 입금 비율 (0으로 나누는 오류 방지)
        if deposit_amount_30d > 0:
            risk_profile.wager_to_deposit_ratio = total_bet / deposit_amount_30d
        else:
            risk_profile.wager_to_deposit_ratio = 0.0
        
        # 출금 대 입금 비율 (0으로 나누는 오류 방지)
        if deposit_amount_30d > 0:
            risk_profile.withdrawal_to_deposit_ratio = withdrawal_amount_30d / deposit_amount_30d
        else:
            risk_profile.withdrawal_to_deposit_ratio = 0.0
        
        # 4. 위험 점수 업데이트 (가중치 조정)
        # 거래 유형별 위험 점수 업데이트 - 새 트랜잭션 영향 강화
        if transaction_type == "deposit":
            # 기존 점수와 새로운 위험 점수를 가중 평균으로 계산 (새 점수 영향력 증가)
            risk_profile.deposit_risk_score = risk_profile.deposit_risk_score * 0.6 + transaction_risk_score * 0.4
        elif transaction_type == "withdrawal":
            risk_profile.withdrawal_risk_score = risk_profile.withdrawal_risk_score * 0.6 + transaction_risk_score * 0.4
        elif transaction_type in ["bet", "win"]:
            risk_profile.gameplay_risk_score = risk_profile.gameplay_risk_score * 0.6 + transaction_risk_score * 0.4
        
        # 전체 위험 점수 업데이트 - 거래 유형별 가중치 조정
        if transaction_risk_score >= 70.0:
            # 고위험 거래인 경우 전체 위험 점수에 더 큰 영향
            risk_profile.overall_risk_score = (
                risk_profile.overall_risk_score * 0.5 + transaction_risk_score * 0.5
            )
            logging.info(f"고위험 거래(점수: {transaction_risk_score})로 인해 전체 위험 점수 가중치 조정")
        else:
            # 일반적인 경우의 가중치
            risk_profile.overall_risk_score = (
                risk_profile.deposit_risk_score * 0.4 +
                risk_profile.withdrawal_risk_score * 0.4 +
                risk_profile.gameplay_risk_score * 0.2
            )
        
        # 마지막 평가 시간 업데이트
        risk_profile.last_assessment_at = now
        
        # 5. 위험 요소 업데이트 및 강화된 위험 요소 추가
        risk_factors = risk_profile.risk_factors or {}
        
        # 낮은 베팅 대 입금 비율 (자금세탁 위험 지표) - 더 세분화된 조건
        if risk_profile.wager_to_deposit_ratio is not None:
            if risk_profile.wager_to_deposit_ratio < 0.1:
                # 매우 낮은 베팅률 (입금의 10% 미만)
                risk_factors["very_low_wagering"] = {
                    "current_ratio": risk_profile.wager_to_deposit_ratio,
                    "severity": "high",
                    "updated_at": now.isoformat()
                }
                # 매우 낮은 베팅률은 위험 점수 직접 상향
                if risk_profile.overall_risk_score < 70:
                    risk_profile.overall_risk_score = max(risk_profile.overall_risk_score, 70.0)
                    logging.info(f"매우 낮은 베팅률({risk_profile.wager_to_deposit_ratio})로 인해 위험 점수 70으로 상향")
            elif risk_profile.wager_to_deposit_ratio < 0.3:
                # 낮은 베팅률 (입금의 10-30%)
                risk_factors["low_wagering"] = {
                    "current_ratio": risk_profile.wager_to_deposit_ratio,
                    "severity": "medium",
                    "updated_at": now.isoformat()
                }
        
        # 높은 출금 대 입금 비율 감지 (이상 패턴)
        if risk_profile.withdrawal_to_deposit_ratio is not None:
            if risk_profile.withdrawal_to_deposit_ratio > 0.95:
                # 95% 이상의 입금액을 출금 (위험 지표)
                risk_factors["high_withdrawal_ratio"] = {
                    "current_ratio": risk_profile.withdrawal_to_deposit_ratio,
                    "severity": "high",
                    "updated_at": now.isoformat()
                }
                # 위험 점수 직접 상향
                if risk_profile.overall_risk_score < 75:
                    risk_profile.overall_risk_score = max(risk_profile.overall_risk_score, 75.0)
                    logging.info(f"높은 출금률({risk_profile.withdrawal_to_deposit_ratio})로 인해 위험 점수 75로 상향")
        
        # 다량의 소액 거래 패턴 감지
        if deposit_count_7d > 50 and deposit_amount_7d / deposit_count_7d < 1000000:
            # 7일 내 50회 이상 거래, 평균 100만원 미만 소액
            risk_factors["multiple_small_deposits"] = {
                "count": deposit_count_7d,
                "avg_amount": deposit_amount_7d / deposit_count_7d,
                "severity": "medium",
                "updated_at": now.isoformat()
            }
        
        # 구조화 시도
        if transaction_risk_score >= 50 and transaction.transaction_type in ["deposit", "withdrawal"]:
            risk_factors["high_risk_transaction"] = {
                "transaction_id": transaction.transaction_id,
                "risk_score": transaction_risk_score,
                "transaction_type": transaction.transaction_type,
                "amount": str(transaction.amount),
                "updated_at": now.isoformat()
            }
        
        risk_profile.risk_factors = risk_factors
        
        # 변경사항 로깅
        logging.info(f"플레이어 {transaction.player_id} 위험 프로필 업데이트: "
                    f"위험 점수 {risk_profile.overall_risk_score}, "
                    f"베팅/입금 비율 {risk_profile.wager_to_deposit_ratio}, "
                    f"출금/입금 비율 {risk_profile.withdrawal_to_deposit_ratio}")
    
    async def create_alert(self, alert_data: AMLAlertCreate) -> AMLAlert:
        """
        AML 알림 수동 생성
        
        Args:
            alert_data: 알림 생성 데이터
            
        Returns:
            AMLAlert: 생성된 알림
        """
        # 플레이어 존재 확인
        player = self.db.query(Player).filter(Player.id == alert_data.player_id).first()
        if not player:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"플레이어 ID {alert_data.player_id}를 찾을 수 없습니다"
            )
        
        # 알림 생성
        alert = AMLAlert(
            player_id=alert_data.player_id,
            alert_type=alert_data.alert_type,
            alert_severity=alert_data.alert_severity,
            alert_status=AlertStatus.NEW,
            description=alert_data.description,
            detection_rule=alert_data.detection_rule,
            transaction_ids=alert_data.transaction_ids,
            transaction_details=alert_data.transaction_details,
            alert_data=alert_data.alert_data,
            risk_score=alert_data.risk_score
        )
        
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        
        return alert
    
    def update_alert_status(self, update_data: AlertStatusUpdate) -> AMLAlert:
        """
        알림 상태 업데이트
        
        Args:
            update_data: 업데이트 데이터
            
        Returns:
            AMLAlert: 업데이트된 알림
        """
        # 알림 조회
        alert = self.db.query(AMLAlert).filter(AMLAlert.id == update_data.alert_id).first()
        if not alert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"알림 ID {update_data.alert_id}를 찾을 수 없습니다"
            )
        
        # 상태 업데이트
        alert.alert_status = update_data.status
        
        # 검토 정보 업데이트
        if update_data.review_notes:
            alert.review_notes = update_data.review_notes
            
        if update_data.reviewed_by:
            alert.reviewed_by = update_data.reviewed_by
            
        # 검토 시간 업데이트
        if update_data.status != alert.alert_status:
            alert.reviewed_at = datetime.now()
            
        # 보고된 경우 보고 시간 및 참조 업데이트
        if update_data.status == AlertStatus.REPORTED:
            alert.reported_at = datetime.now()
            if update_data.report_reference:
                alert.report_reference = update_data.report_reference
        
        self.db.commit()
        self.db.refresh(alert)
        
        return alert
    
    def get_player_alerts(self, player_id: str, limit: int = 50, offset: int = 0) -> List[AMLAlert]:
        """
        플레이어 알림 조회
        
        Args:
            player_id: 플레이어 ID
            limit: 최대 조회 수
            offset: 조회 시작 위치
            
        Returns:
            List[AMLAlert]: 알림 목록
        """
        alerts = self.db.query(AMLAlert).filter(
            AMLAlert.player_id == player_id
        ).order_by(AMLAlert.created_at.desc()).offset(offset).limit(limit).all()
        
        return alerts
    
    def get_high_risk_players(self, limit: int = 50, offset: int = 0) -> List[AMLRiskProfile]:
        """
        고위험 플레이어 조회
        
        Args:
            limit: 최대 조회 수
            offset: 조회 시작 위치
            
        Returns:
            List[AMLRiskProfile]: 고위험 플레이어 목록
        """
        high_risk_profiles = self.db.query(AMLRiskProfile).filter(
            AMLRiskProfile.overall_risk_score >= 70.0,
            AMLRiskProfile.is_active == True
        ).order_by(AMLRiskProfile.overall_risk_score.desc()).offset(offset).limit(limit).all()
        
        return high_risk_profiles 