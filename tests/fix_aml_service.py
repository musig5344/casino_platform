#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AML 서비스 수정 스크립트

1. _update_risk_profile_from_transaction 함수 파라미터 불일치 수정
2. _create_alert_from_transaction 함수 관련 문제 수정
3. AML 알림 생성 로직 강화
"""

import sys
import os
import logging
import traceback
from datetime import datetime
import argparse

# 시스템 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AML_SERVICE_FIX")

# 모델 클래스 임포트 (필요시 backend 모듈 경로 추가)
sys.path.append('.')
try:
    from backend.services.aml_service import AMLService
except ImportError:
    logger.error("AML 서비스 클래스 가져오기 실패. 프로젝트 루트 디렉토리에서 실행하세요.")
    sys.exit(1)

def backup_file(filepath):
    """파일 백업"""
    if os.path.exists(filepath):
        backup_path = f"{filepath}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        try:
            with open(filepath, 'r', encoding='utf-8') as src, open(backup_path, 'w', encoding='utf-8') as dst:
                dst.write(src.read())
            logger.info(f"파일 백업 완료: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"파일 백업 중 오류: {str(e)}")
            return False
    else:
        logger.error(f"파일이 존재하지 않음: {filepath}")
        return False

def fix_update_risk_profile_function(content):
    """_update_risk_profile_from_transaction 함수 파라미터 불일치 수정"""
    logger.info("_update_risk_profile_from_transaction 함수 파라미터 수정 시작...")
    
    # 호출부 수정
    # 원본: await self._update_risk_profile_from_transaction(aml_transaction)
    old_call = "await self._update_risk_profile_from_transaction(aml_transaction)"
    new_call = """# 위험 프로필 가져오기
            risk_profile = self._get_or_create_risk_profile(aml_transaction.player_id)
            # 트랜잭션 조회
            transaction = self.db.query(Transaction).filter(Transaction.transaction_id == aml_transaction.transaction_id).first()
            if transaction:
                await self._update_risk_profile_from_transaction(transaction, risk_profile, aml_transaction.risk_score)
            else:
                logging.error(f"위험 프로필 업데이트를 위한 트랜잭션을 찾을 수 없음: {aml_transaction.transaction_id}")"""
    
    updated_content = content.replace(old_call, new_call)
    
    # 함수 정의부 확인
    if "async def _update_risk_profile_from_transaction(self, transaction: Transaction, risk_profile: AMLRiskProfile, transaction_risk_score: float)" in content:
        logger.info("_update_risk_profile_from_transaction 함수 정의 확인됨")
    else:
        logger.warning("_update_risk_profile_from_transaction 함수 정의를 찾을 수 없음")
    
    if updated_content != content:
        logger.info("_update_risk_profile_from_transaction 함수 호출부 수정 완료")
    else:
        logger.warning("_update_risk_profile_from_transaction 함수 호출부를 찾을 수 없음")
    
    return updated_content

def fix_create_alert_function(content):
    """_create_alert_from_transaction 함수 관련 문제 수정"""
    logger.info("_create_alert_from_transaction 함수 수정 시작...")
    
    # 함수 내 트랜잭션 ID 유효성 검사 강화
    old_code = """            self.db.add(alert)
            self.db.flush()  # 알림 객체가 데이터베이스에 즉시 반영되도록 flush 호출
            logging.info(f"알림 생성 성공: ID={alert.id}, 유형={alert_type}, 심각도={severity}")
            return alert"""
    
    new_code = """            # 트랜잭션 ID 유효성 확인
            if aml_transaction and aml_transaction.transaction_id:
                # 트랜잭션이 실제로 존재하는지 한번 더 확인
                tx_exists = self.db.query(Transaction).filter(
                    Transaction.transaction_id == aml_transaction.transaction_id
                ).first() is not None
                
                if not tx_exists:
                    logging.error(f"알림 생성 실패: 트랜잭션 ID {aml_transaction.transaction_id}가 유효하지 않음")
                    return None
            
            try:
                self.db.add(alert)
                self.db.flush()  # 알림 객체가 데이터베이스에 즉시 반영되도록 flush 호출
                
                # 알림 ID 확인
                if not alert.id:
                    logging.error("알림 생성 후 ID가 할당되지 않음")
                    self.db.rollback()
                    return None
                
                logging.info(f"알림 생성 성공: ID={alert.id}, 유형={alert_type}, 심각도={severity}")
                return alert
            except Exception as e:
                logging.error(f"알림 DB 저장 중 오류: {str(e)}")
                self.db.rollback()
                return None"""
    
    updated_content = content.replace(old_code, new_code)
    
    # 예외 처리 개선
    old_exception = """        except Exception as e:
            logging.error(f"알림 생성 중 오류 발생: {str(e)}")
            logging.error(traceback.format_exc())
            # 오류가 발생해도 분석 과정 자체는 계속 진행되도록 None 반환
            return None"""
    
    new_exception = """        except Exception as e:
            logging.error(f"알림 생성 중 오류 발생: {str(e)}")
            logging.error(traceback.format_exc())
            # 오류 상세 정보 로깅
            if 'aml_transaction' in locals():
                logging.error(f"문제의 트랜잭션 ID: {getattr(aml_transaction, 'transaction_id', 'unknown')}")
                logging.error(f"문제의 플레이어 ID: {getattr(aml_transaction, 'player_id', 'unknown')}")
            # 오류가 발생해도 분석 과정 자체는 계속 진행되도록 None 반환
            return None"""
    
    updated_content = updated_content.replace(old_exception, new_exception)
    
    if updated_content != content:
        logger.info("_create_alert_from_transaction 함수 수정 완료")
    else:
        logger.warning("_create_alert_from_transaction 함수 수정 대상을 찾을 수 없음")
    
    return updated_content

def enhance_analyze_transaction(content):
    """analyze_transaction 함수 개선"""
    logger.info("analyze_transaction 함수 개선 시작...")
    
    # 알림 생성 로직에 로깅 추가
    old_code = """            # 알림 생성 (필요한 경우)
            alert = None
            if is_large_transaction or is_structuring_attempt:
                alert_severity = AlertSeverity.HIGH if is_structuring_attempt else AlertSeverity.MEDIUM
                alert_type = None
                
                if is_structuring_attempt:
                    alert_type = AlertType.THRESHOLD_AVOIDANCE
                elif transaction_type == "deposit" and is_large_transaction:
                    alert_type = AlertType.LARGE_DEPOSIT
                elif transaction_type == "withdrawal" and is_large_transaction:
                    alert_type = AlertType.LARGE_WITHDRAWAL
                
                alert = await self._create_alert_from_transaction(aml_transaction, alert_severity, alert_type)
                logging.info(f"분석 결과로 알림 생성: {alert.id if alert else 'None'}")
            else:
                logging.info("분석 결과 알림이 필요하지 않음")"""
    
    new_code = """            # 알림 생성 (필요한 경우)
            alert = None
            if is_large_transaction or is_structuring_attempt:
                logging.info(f"알림 생성 조건 충족: 대규모 거래={is_large_transaction}, 구조화 시도={is_structuring_attempt}")
                alert_severity = AlertSeverity.HIGH if is_structuring_attempt else AlertSeverity.MEDIUM
                alert_type = None
                
                if is_structuring_attempt:
                    alert_type = AlertType.THRESHOLD_AVOIDANCE
                    logging.info("구조화 시도 알림 생성")
                elif transaction_type == "deposit" and is_large_transaction:
                    alert_type = AlertType.LARGE_DEPOSIT
                    logging.info(f"대규모 입금 알림 생성: {transaction_amount} {transaction.currency}")
                elif transaction_type == "withdrawal" and is_large_transaction:
                    alert_type = AlertType.LARGE_WITHDRAWAL
                    logging.info(f"대규모 출금 알림 생성: {transaction_amount} {transaction.currency}")
                
                # 모든 데이터 검증
                if not hasattr(aml_transaction, 'transaction_id') or not aml_transaction.transaction_id:
                    logging.error("AML 트랜잭션에 유효한 transaction_id가 없음")
                    aml_transaction.transaction_id = transaction_id
                
                if not hasattr(aml_transaction, 'player_id') or not aml_transaction.player_id:
                    logging.error("AML 트랜잭션에 유효한 player_id가 없음")
                    aml_transaction.player_id = player.id
                
                alert = await self._create_alert_from_transaction(aml_transaction, alert_severity, alert_type)
                if alert:
                    logging.info(f"분석 결과로 알림 생성 성공: ID={alert.id}, 유형={alert_type}")
                else:
                    logging.error(f"분석 결과로 알림 생성 실패: 트랜잭션={transaction_id}, 유형={alert_type}")
            else:
                logging.info("분석 결과 알림이 필요하지 않음: 조건 불충족")"""
    
    updated_content = content.replace(old_code, new_code)
    
    # 트랜잭션 조회 부분 개선
    old_query = """        try:
            # 트랜잭션 조회
            transaction = self.db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
            if not transaction:
                logging.error(f"트랜잭션을 찾을 수 없음: {transaction_id}")
                raise HTTPException(status_code=404, detail=f"Transaction not found: {transaction_id}")"""
    
    new_query = """        try:
            # 트랜잭션 조회 (정확한 ID 매칭 확인)
            logging.info(f"트랜잭션 ID 검색: '{transaction_id}'")
            transaction = self.db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
            
            if not transaction:
                # ID 매칭 실패 시 상세 로깅
                sample_ids = self.db.query(Transaction.transaction_id).limit(5).all()
                logging.error(f"트랜잭션을 찾을 수 없음: {transaction_id}")
                logging.error(f"현재 DB의 트랜잭션 ID 샘플: {[tx[0] for tx in sample_ids]}")
                raise HTTPException(status_code=404, detail=f"Transaction not found: {transaction_id}")
                
            logging.info(f"트랜잭션 조회 성공: ID={transaction_id}, 유형={transaction.transaction_type}, 금액={transaction.amount}")"""
    
    updated_content = updated_content.replace(old_query, new_query)
    
    if updated_content != content:
        logger.info("analyze_transaction 함수 개선 완료")
    else:
        logger.warning("analyze_transaction 함수 개선 대상을 찾을 수 없음")
    
    return updated_content

def fix_aml_service_file(filepath):
    """AML 서비스 파일 수정"""
    if not os.path.exists(filepath):
        logger.error(f"파일이 존재하지 않음: {filepath}")
        return False
    
    # 파일 백업
    if not backup_file(filepath):
        logger.error(f"{filepath} 백업 실패. 수정을 중단합니다.")
        return False
    
    try:
        # 파일 읽기
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 함수별 수정 적용
        updated_content = fix_update_risk_profile_function(content)
        updated_content = fix_create_alert_function(updated_content)
        updated_content = enhance_analyze_transaction(updated_content)
        
        # 수정된 내용으로 파일 업데이트
        if updated_content != content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            logger.info(f"{filepath} 수정 완료")
            return True
        else:
            logger.warning(f"{filepath}에 수정할 내용이 없음")
            return False
            
    except Exception as e:
        logger.error(f"파일 수정 중 오류: {str(e)}")
        logger.error(traceback.format_exc())
        return False

def main():
    parser = argparse.ArgumentParser(description="AML 서비스 수정 스크립트")
    parser.add_argument("--service-file", help="AML 서비스 파일 경로", default="backend/services/aml_service.py")
    args = parser.parse_args()
    
    logger.info("AML 서비스 수정 시작...")
    
    # AML 서비스 파일 수정
    if fix_aml_service_file(args.service_file):
        logger.info("AML 서비스 수정 완료")
    else:
        logger.error("AML 서비스 수정 실패")
    
    logger.info("스크립트 종료")

if __name__ == "__main__":
    main() 