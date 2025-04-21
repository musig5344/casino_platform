import requests
import json
import uuid
import time
import random
from datetime import datetime
import traceback
import os
import sys

# 기본 설정
BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
TEST_PLAYER_ID = os.environ.get("TEST_PLAYER_ID", "test_player_123")
ADMIN_HEADERS = {"X-Admin": "true", "Content-Type": "application/json"}

# 테스트 결과 추적
TEST_RESULTS = {
    "success": 0,
    "fail": 0,
    "tests": []
}

# 테스트 환경 변수
TEST_ENV = {
    "transactions": {},  # 생성된 트랜잭션 캐시
    "tokens": {},        # 획득한 토큰 캐시
    "debug_mode": os.environ.get("TEST_DEBUG", "0") == "1"
}

def print_response(response, title=None, verbose=True):
    """
    API 응답 내용을 보기 좋게 출력
    
    Args:
        response: API 응답 객체
        title: 출력 제목
        verbose: 상세 출력 여부
    
    Returns:
        JSON 응답 또는 None
    """
    if title and verbose:
        print(f"\n===== {title} =====")
    
    if verbose:
        print(f"상태 코드: {response.status_code}")
        
        try:
            # JSON 응답이면 예쁘게 출력
            data = response.json()
            print("응답 내용:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
        except:
            # JSON이 아니면 텍스트로 출력
            print(f"응답 내용: {response.text}")
        
        print("-" * 50)
    
    return response.json() if response.status_code in [200, 201] else None

def track_test_result(test_name, success, response=None, error=None, expected_failure=False):
    """
    테스트 결과를 추적하고 통계 업데이트
    
    Args:
        test_name: 테스트 이름
        success: 성공 여부
        response: API 응답 객체
        error: 오류 정보
        expected_failure: 예상된 실패인지 여부
    
    Returns:
        성공 여부
    """
    result = {
        "name": test_name,
        "success": success,
        "timestamp": datetime.now().isoformat(),
        "expected_failure": expected_failure
    }
    
    if response:
        try:
            result["response"] = response.json() if hasattr(response, 'json') else response
            result["status_code"] = response.status_code if hasattr(response, 'status_code') else None
        except:
            result["response"] = str(response)
    
    if error:
        result["error"] = str(error)
    
    TEST_RESULTS["tests"].append(result)
    
    if success or expected_failure:
        TEST_RESULTS["success"] += 1
    else:
        TEST_RESULTS["fail"] += 1
    
    return success

def generate_unique_id(prefix="tx", include_timestamp=True, module_name=None):
    """
    고유한 ID 생성
    
    Args:
        prefix: ID 접두어
        include_timestamp: 타임스탬프 포함 여부
        module_name: 호출한 모듈 이름 (테스트 간 충돌 방지)
    
    Returns:
        고유 ID 문자열
    """
    # 호출자 모듈 이름이 제공되면 접두어에 추가
    if module_name:
        prefix = f"{module_name}_{prefix}"
    else:
        # 호출자 모듈 이름 자동 탐지 시도
        try:
            import inspect
            caller_frame = inspect.stack()[1]
            caller_module = inspect.getmodule(caller_frame[0])
            if caller_module and caller_module.__name__ != "__main__":
                # 모듈 이름에서 'test_' 접두어 제거하고 짧게 만들기
                module_prefix = caller_module.__name__.replace("test_", "").split('.')[0][:3]
                prefix = f"{module_prefix}_{prefix}"
        except:
            pass
    
    unique_part = str(uuid.uuid4())
    timestamp_part = f"_{int(time.time())}" if include_timestamp else ""
    random_part = f"_{random.randint(1000, 9999)}"
    
    return f"{prefix}{timestamp_part}{random_part}_{unique_part[:8]}"

def get_auth_token(player_id=None, force_new=False, cache=True):
    """
    플레이어 인증하여 JWT 토큰을 반환
    
    Args:
        player_id: 인증할 플레이어 ID (None이면 기본값 사용)
        force_new: 캐시된 토큰 무시하고 새로 획득
        cache: 토큰 캐싱 여부
        
    Returns:
        인증 토큰 또는 None(실패시)
    """
    player_id = player_id or TEST_PLAYER_ID
    
    # 캐시된 토큰이 있고 강제 갱신이 아니면 캐시 사용
    if not force_new and player_id in TEST_ENV["tokens"] and cache:
        return TEST_ENV["tokens"][player_id]
    
    print("\n===== 인증 토큰 획득 =====")
    try:
        session_id = f"session_{int(time.time())}"
        auth_data = {
            "player": {
                "id": player_id,
                "firstName": "테스트",
                "lastName": "플레이어",
                "country": "KR",
                "currency": "KRW",
                "session": {
                    "id": session_id,
                    "ip": "127.0.0.1"
                }
            },
            "uuid": str(uuid.uuid4())
        }
        
        response = requests.post(f"{BASE_URL}/ua/v1/MY_CASINO/qwqw6171", json=auth_data)
        if response.status_code != 200:
            print(f"인증 실패: {response.status_code} - {response.text}")
            track_test_result("인증 토큰 획득", False, response)
            return None
        
        print("인증 성공")
        response_data = response.json()
        token = None
        
        if "token" in response_data:
            token = response_data["token"]
        else:
            # entryEmbedded에서 토큰 추출 시도
            entry_url = response_data.get("entry", "")
            if "params=" in entry_url:
                token = entry_url.split("params=")[1].split("&")[0]
        
        if token:
            # 토큰 캐싱
            if cache:
                TEST_ENV["tokens"][player_id] = token
            
            masked_token = token[:30] + "..." if len(token) > 30 else token
            print(f"인증 토큰 획득 성공: {masked_token}")
            track_test_result("인증 토큰 획득", True, response)
            return token
        else:
            print("토큰 획득 실패: 응답에 토큰 정보 없음")
            track_test_result("인증 토큰 획득", False, response)
            return None
            
    except Exception as e:
        print(f"인증 토큰 획득 중 오류: {e}")
        track_test_result("인증 토큰 획득", False, error=e)
        return None

def init_wallet(player_id=None, initial_amount=10000.0):
    """
    지갑 초기화 (잔액을 0으로 만든 후 초기 금액 설정)
    
    Args:
        player_id: 플레이어 ID (None이면 기본값 사용)
        initial_amount: 초기 잔액
    
    Returns:
        성공 여부, 초기화 후 잔액
    """
    player_id = player_id or TEST_PLAYER_ID
    
    print("\n===== 지갑 초기화 =====")
    
    try:
        # 먼저 출금으로 잔액 초기화
        reset_withdrawal = {
            "transaction_id": generate_unique_id("reset_withdrawal"),
            "player_id": player_id,
            "amount": 99000000.0,  # 큰 금액으로 설정
            "transaction_type": "withdrawal",
            "source": "wallet_reset"
        }
        
        # 출금 요청 전송 (응답은 무시)
        requests.post(
            f"{BASE_URL}/test/mock-transaction",
            headers=ADMIN_HEADERS,
            json=reset_withdrawal
        )
        
        # 새 입금으로 초기 잔액 설정
        deposit_transaction_id = generate_unique_id("reset_deposit")
        deposit_data = {
            "transaction_id": deposit_transaction_id,
            "player_id": player_id,
            "amount": initial_amount,
            "transaction_type": "deposit",
            "source": "wallet_reset"
        }
        
        response = requests.post(
            f"{BASE_URL}/test/mock-transaction",
            headers=ADMIN_HEADERS,
            json=deposit_data
        )
        
        if response.status_code == 201:
            result = response.json()
            balance = result.get("transaction", {}).get("wallet_balance", 0)
            print(f"지갑 초기화 완료: 잔액 = {balance}")
            track_test_result("지갑 초기화", True, response)
            
            # 트랜잭션 기록
            TEST_ENV["transactions"][deposit_transaction_id] = {
                "type": "deposit",
                "amount": initial_amount,
                "player_id": player_id,
                "created_at": datetime.now().isoformat(),
                "status": "completed"
            }
            
            return True, balance
        else:
            print(f"지갑 초기화 오류: {response.status_code}")
            track_test_result("지갑 초기화", False, response)
            return False, 0
    except Exception as e:
        print(f"지갑 초기화 중 예외 발생: {str(e)}")
        track_test_result("지갑 초기화", False, error=e)
        return False, 0

def create_test_transaction(amount=1000, transaction_type="deposit", player_id=None, metadata=None, module_name=None):
    """
    테스트용 트랜잭션 생성
    
    Args:
        amount: 트랜잭션 금액
        transaction_type: 트랜잭션 유형 (deposit/withdrawal)
        player_id: 플레이어 ID (None이면 기본값 사용)
        metadata: 추가 메타데이터 (딕셔너리)
        module_name: 호출한 모듈 이름 (테스트 간 충돌 방지)
    
    Returns:
        (성공 여부, 트랜잭션 ID)
    """
    player_id = player_id or TEST_PLAYER_ID
    transaction_id = generate_unique_id(f"{transaction_type}", module_name=module_name)
    
    print(f"\n===== 테스트 트랜잭션 생성 (금액: {amount}, 유형: {transaction_type}) =====")
    
    try:
        transaction_data = {
            "transaction_id": transaction_id,
            "player_id": player_id,
            "amount": amount,
            "transaction_type": transaction_type,
            "source": "test_utils"
        }
        
        # 메타데이터가 있으면 추가
        if metadata:
            transaction_data["metadata"] = metadata
        
        url = f"{BASE_URL}/test/mock-transaction"
        response = requests.post(
            url,
            headers=ADMIN_HEADERS,
            json=transaction_data
        )
        
        if response.status_code == 201:
            print(f"트랜잭션 생성 성공: {transaction_id}")
            
            # 생성된 트랜잭션 캐싱
            TEST_ENV["transactions"][transaction_id] = {
                "type": transaction_type,
                "amount": amount,
                "player_id": player_id,
                "created_at": datetime.now().isoformat(),
                "status": "completed",
                "canceled": False,
                "module": module_name or "unknown"
            }
            
            track_test_result("트랜잭션 생성", True, response)
            return True, transaction_id
        else:
            print(f"트랜잭션 생성 실패: {response.status_code}")
            print_response(response)
            track_test_result("트랜잭션 생성", False, response)
            return False, transaction_id
    except Exception as e:
        print(f"트랜잭션 생성 중 오류: {str(e)}")
        track_test_result("트랜잭션 생성", False, error=e)
        return False, transaction_id

def get_wallet_balance(player_id=None):
    """
    지갑 잔액 조회
    
    Args:
        player_id: 플레이어 ID (None이면 기본값 사용)
        
    Returns:
        (성공 여부, 잔액)
    """
    player_id = player_id or TEST_PLAYER_ID
    
    try:
        data = {
            "uuid": str(uuid.uuid4()),
            "player_id": player_id
        }
        
        response = requests.post(f"{BASE_URL}/api/balance", json=data)
        
        if response.status_code == 200:
            result = response.json()
            balance = result.get('balance', '0')
            return True, balance
        else:
            return False, 0
    except Exception as e:
        print(f"잔액 조회 중 오류: {str(e)}")
        return False, 0

def is_transaction_canceled(transaction_id):
    """
    트랜잭션이 이미 취소되었는지 확인
    
    Args:
        transaction_id: 확인할 트랜잭션 ID
        
    Returns:
        취소 여부 (True/False)
    """
    # 트랜잭션 ID가 캐시에 있고 취소 상태가 기록되어 있는 경우
    if transaction_id in TEST_ENV["transactions"]:
        return TEST_ENV["transactions"][transaction_id].get("canceled", False)
    
    return False

def mark_transaction_canceled(transaction_id, cancel_transaction_id=None):
    """
    트랜잭션을 취소 상태로 표시
    
    Args:
        transaction_id: 취소된 트랜잭션 ID
        cancel_transaction_id: 취소 트랜잭션 ID
        
    Returns:
        성공 여부
    """
    if transaction_id in TEST_ENV["transactions"]:
        # 트랜잭션 상태 업데이트
        TEST_ENV["transactions"][transaction_id]["canceled"] = True
        TEST_ENV["transactions"][transaction_id]["status"] = "canceled"
        TEST_ENV["transactions"][transaction_id]["cancel_transaction_id"] = cancel_transaction_id
        TEST_ENV["transactions"][transaction_id]["canceled_at"] = datetime.now().isoformat()
        return True
    
    return False

def reset_test_environment():
    """
    테스트 환경 완전 초기화
    - 지갑 잔액 초기화
    - 캐시된 데이터 삭제
    
    Returns:
        성공 여부
    """
    print("\n===== 테스트 환경 초기화 중 =====")
    
    # 지갑 초기화
    wallet_reset, _ = init_wallet(TEST_PLAYER_ID, 0)
    
    # 캐시 초기화
    TEST_ENV["transactions"] = {}
    TEST_ENV["tokens"] = {}
    
    return wallet_reset

def print_test_summary():
    """
    테스트 결과 요약을 출력
    
    Returns:
        성공 여부 (모든 테스트가 성공하면 True)
    """
    print("\n" + "=" * 50)
    print("API 테스트 요약")
    print("=" * 50)
    
    total_tests = len(TEST_RESULTS["tests"])
    expected_failures = sum(1 for test in TEST_RESULTS["tests"] if test.get("expected_failure", False))
    real_failures = TEST_RESULTS["fail"]
    real_success = TEST_RESULTS["success"] - expected_failures
    
    success_rate = (real_success / total_tests * 100) if total_tests > 0 else 0
    
    print(f"전체 테스트: {total_tests}")
    print(f"성공: {real_success}")
    print(f"실패: {real_failures}")
    print(f"예상된 실패: {expected_failures}")
    print(f"성공률: {success_rate:.2f}%")
    
    if real_failures > 0:
        print("\n실패한 테스트:")
        for test in TEST_RESULTS["tests"]:
            if not test["success"] and not test.get("expected_failure", False):
                print(f"  - {test['name']}")
                if "error" in test:
                    print(f"    오류: {test['error']}")
                if "status_code" in test:
                    print(f"    상태 코드: {test['status_code']}")
    
    if expected_failures > 0:
        print("\n예상된 실패 (무시됨):")
        for test in TEST_RESULTS["tests"]:
            if test.get("expected_failure", False):
                print(f"  - {test['name']}")
    
    print("=" * 50)
    
    # 예상된 실패를 제외한 진짜 실패가 없으면 성공
    return real_failures == 0

def reset_test_results():
    """테스트 결과 초기화"""
    global TEST_RESULTS
    TEST_RESULTS = {
        "success": 0,
        "fail": 0,
        "tests": []
    } 