#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
지갑 API 테스트 스크립트 (Pytest 스타일)
- Fixture를 사용하여 TestClient, 인증 토큰, 테스트 트랜잭션 관리
- 각 테스트 케이스를 독립적인 함수로 분리 (각 테스트는 자체 데이터 설정 수행)
- `assert`를 사용하여 결과 검증
"""

import pytest
import time
import uuid
from decimal import Decimal
from fastapi.testclient import TestClient # TestClient 타입 힌트
from urllib.parse import urlparse, parse_qs # 인증 토큰 추출용

# Use absolute imports for both test_utils and conftest
from tests.test_utils import (
    BASE_URL, TEST_PLAYER_ID, ADMIN_HEADERS,
    print_response, # 디버깅용
    generate_unique_id
)
from tests.conftest import get_auth_token_for_player

# --- Module Level Fixtures ---

@pytest.fixture(scope="module")
def auth_token(client: TestClient):
    """테스트 모듈용 인증 토큰을 가져옵니다."""
    # test_auth_api.py 의 default_auth_token fixture 와 유사 로직
    # 실제 유효한 casino_key 와 api_token 사용
    casino_key = "MY_CASINO"
    api_token = "qwqw6171"
    auth_endpoint = f"/ua/v1/{casino_key}/{api_token}"
    auth_data = {
        "uuid": str(uuid.uuid4()),
        "player": {
            "id": TEST_PLAYER_ID,
            "firstName": "기존",
            "lastName": "테스터",
            "country": "KR",
            "currency": "KRW",
            "session": {"id": generate_unique_id("session"), "ip": "127.0.0.1"}
        },
        "config": {}
    }
    try:
        response = client.post(auth_endpoint, json=auth_data, headers={"Host": "localhost"})
        response.raise_for_status()
        response_data = response.json()
        entry_url = response_data.get("entry")
        if not entry_url:
            pytest.fail("Wallet API 테스트용 인증 토큰 획득 실패: 응답에 entry URL 없음")
        parsed_url = urlparse(entry_url)
        query_params = parse_qs(parsed_url.query)
        token = query_params.get("params", [None])[0]
        if not token:
            pytest.fail("Wallet API 테스트용 인증 토큰 획득 실패: entry URL에서 토큰(params) 추출 불가")
        print(f"\nWallet API 테스트용 인증 토큰 획득 성공")
        return token
    except Exception as e:
        pytest.fail(f"Wallet API 테스트용 인증 토큰 획득 중 오류: {e}")


@pytest.fixture(scope="module")
def wallet_headers(auth_token: str) -> dict:
    """지갑 API 요청용 기본 헤더를 생성합니다."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Accept-Language": "ko", # 기본 언어 설정
        "Host": "localhost"
    }


# --- Test Data Storage (Module Scope) ---
# Fixture 간 데이터 전달을 위해 클래스나 딕셔너리 사용 가능
class WalletTestData:
    credit_tx_id: str = None
    debit_tx_id: str = None
    initial_balance: Decimal = None

@pytest.fixture(scope="module")
def test_data() -> WalletTestData:
    return WalletTestData()

# --- Test Functions ---

def test_get_initial_balance(client: TestClient, wallet_headers: dict, test_data: WalletTestData):
    """초기 잔액을 조회하고 저장합니다. (API 호출로 지갑 생성 시도 후 확인)"""
    print(f"\n===== 초기 잔액 조회 테스트 (API 호출) =====")
    player_id = TEST_PLAYER_ID
    currency = "KRW" # 기본 통화 가정

    # 지갑 생성을 위한 최소 금액 Credit 요청 (없으면 생성됨)
    setup_tx_id = f"setup_balance_{uuid.uuid4()}"
    credit_data = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": setup_tx_id,
        "player_id": player_id,
        "amount": "0.01", # 지갑 생성을 위한 최소 금액
        "currency": currency
    }
    setup_response = client.post(f"{BASE_URL}/api/credit", headers=wallet_headers, json=credit_data)
    assert setup_response.status_code == 200, f"지갑 생성/확인 위한 Credit 요청 실패: {setup_response.text}"
    print(f"지갑 생성/확인 Credit 요청 완료 (Tx: {setup_tx_id}), 상태 코드: {setup_response.status_code}")

    # BalanceRequest 스키마에 맞는 요청 본문 전달 (uuid, player_id)
    request_data = {"uuid": str(uuid.uuid4()), "player_id": player_id}
    response = client.post(f"{BASE_URL}/api/balance", headers=wallet_headers, json=request_data)
    print_response(response, "잔액 조회 응답 (지갑 생성/확인 후)")

    assert response.status_code == 200, f"초기 잔액 조회 실패 (지갑 생성 후): {response.text}"
    data = response.json()
    assert data["player_id"] == player_id
    # 지갑 생성 시 0.01을 넣었으므로, 잔액이 0.01인지 확인
    assert Decimal(data["balance"]) == Decimal("0.01")
    assert data["currency"] == currency
    test_data.initial_balance = Decimal(data["balance"]) # 실제 초기 잔액 저장
    print(f"초기 잔액 확인 (API 호출 방식): {test_data.initial_balance} {data['currency']}")


def test_wallet_credit(client: TestClient, wallet_headers: dict):
    """지갑 입금 테스트. 지갑이 없거나 0원인 상태에서 시작하여 입금을 테스트합니다."""
    print(f"\n===== 입금 테스트 (0원 시작 가정) =====")
    player_id = TEST_PLAYER_ID
    currency = "KRW"

    # 입금할 금액 및 거래 ID
    tx_id = generate_unique_id("cred")
    amount = Decimal("1000.50")

    # /api/credit 호출 (지갑이 없으면 생성되고 0원에서 시작)
    credit_data = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": tx_id,
        "player_id": player_id,
        "amount": str(amount),
        "currency": currency
    }
    response = client.post(f"{BASE_URL}/api/credit", headers=wallet_headers, json=credit_data)
    print_response(response, f"입금 응답 (Tx: {tx_id}) - 상태 코드: {response.status_code}")
    response.raise_for_status()
    data = response.json()
    assert data["player_id"] == player_id

    # 기대 잔액 계산 (0 + 입금액)
    expected_balance = Decimal("0.00") + amount
    print(f"기대 잔액 계산: 0.00 + {amount} = {expected_balance}")
    print(f"실제 API 응답 잔액: {data['balance']}")
    assert Decimal(data["balance"]) == expected_balance, f"입금 실패: 잔액 불일치 (기대: {expected_balance}, 실제: {data['balance']})"

    # test_data 사용 제거
    # test_data.credit_tx_id = tx_id
    print(f"입금 성공: {amount} {currency}, 최종 잔액: {data['balance']}")


def test_wallet_credit_idempotency(client: TestClient, wallet_headers: dict):
    """동일한 거래 ID로 재입금 시도 (멱등성 테스트). 테스트 함수 내에서 초기 입금 및 중복 호출을 수행합니다."""
    print(f"\n===== 입금 멱등성 테스트 (함수 내 설정) =====")
    player_id = TEST_PLAYER_ID
    currency = "KRW"
    amount = Decimal("500.25") # 테스트용 금액

    # 1. 첫 번째 Credit 호출 (테스트 대상 트랜잭션 생성)
    first_tx_id = generate_unique_id("cred_idem_1")
    credit_data_1 = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": first_tx_id,
        "player_id": player_id,
        "amount": str(amount),
        "currency": currency
    }
    response1 = client.post(f"{BASE_URL}/api/credit", headers=wallet_headers, json=credit_data_1)
    assert response1.status_code == 200, f"첫 번째 Credit 요청 실패: {response1.text}"
    print(f"첫 번째 Credit 완료 (Tx: {first_tx_id}), 잔액: {response1.json().get('balance')}")

    # 2. 현재 잔액 확인 (중복 호출 전)
    balance_request_data = {"uuid": str(uuid.uuid4()), "player_id": player_id}
    balance_response = client.post(f"{BASE_URL}/api/balance", headers=wallet_headers, json=balance_request_data)
    assert balance_response.status_code == 200, f"중복 Credit 전 잔액 확인 실패: {balance_response.text}"
    balance_before = Decimal(balance_response.json()["balance"])
    print(f"중복 Credit 시도 전 잔액: {balance_before}")

    # 3. 동일한 transaction_id로 /api/credit 재호출
    credit_data_2 = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": first_tx_id, # 동일 ID 사용
        "player_id": player_id,
        "amount": str(amount), # 동일 금액 사용
        "currency": currency
    }
    response2 = client.post(f"{BASE_URL}/api/credit", headers=wallet_headers, json=credit_data_2)
    print_response(response2, f"중복 입금 응답 (Tx: {first_tx_id}) - 상태 코드: {response2.status_code}")

    # 멱등성 요청은 성공(200)을 반환해야 함
    assert response2.status_code == 200, f"멱등성 입금 요청 실패: {response2.text}"
    data2 = response2.json()
    assert data2["player_id"] == player_id

    # 잔액이 변하지 않았는지 확인 (API 응답 기준)
    assert Decimal(data2["balance"]) == balance_before, f"멱등성 실패: 잔액 변경됨 (이전: {balance_before}, 현재: {data2['balance']})"
    print(f"입금 멱등성 확인: Tx {first_tx_id}, 잔액 불변: {data2['balance']}")


def test_wallet_debit(client: TestClient, wallet_headers: dict):
    """지갑 출금 테스트. 테스트 함수 내에서 초기 잔액을 설정하고 출금을 테스트합니다."""
    print(f"\n===== 출금 테스트 (함수 내 설정) =====")
    player_id = TEST_PLAYER_ID
    currency = "KRW"

    # 1. 초기 잔액 설정 (Credit API 사용)
    initial_credit_amount = Decimal("500.00")
    initial_tx_id = generate_unique_id("cred_deb_setup")
    initial_credit_data = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": initial_tx_id,
        "player_id": player_id,
        "amount": str(initial_credit_amount),
        "currency": currency
    }
    response_cred = client.post(f"{BASE_URL}/api/credit", headers=wallet_headers, json=initial_credit_data)
    assert response_cred.status_code == 200, f"출금 테스트 초기 입금 실패: {response_cred.text}"
    balance_before_debit = Decimal(response_cred.json()["balance"])
    print(f"초기 입금 완료 (Tx: {initial_tx_id}), 출금 전 잔액: {balance_before_debit}")
    # 초기 입금 금액과 잔액이 일치하는지 추가 확인 (선택적)
    assert balance_before_debit == initial_credit_amount, "초기 입금 후 잔액 불일치"

    # 2. /api/debit 호출
    tx_id = generate_unique_id("deb")
    amount_to_debit = Decimal("200.25")
    debit_data = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": tx_id,
        "player_id": player_id,
        "amount": str(amount_to_debit),
        "currency": currency
    }
    response_deb = client.post(f"{BASE_URL}/api/debit", headers=wallet_headers, json=debit_data)
    print_response(response_deb, f"출금 응답 (Tx: {tx_id})")
    response_deb.raise_for_status()
    data_deb = response_deb.json()
    assert data_deb["player_id"] == player_id

    # 3. 결과 검증 (API 응답)
    expected_balance = balance_before_debit - amount_to_debit
    assert Decimal(data_deb["balance"]) == expected_balance, f"출금 실패: 잔액 불일치 (기대: {expected_balance}, 실제: {data_deb['balance']})"

    # test_data 사용 제거
    # test_data.debit_tx_id = tx_id
    print(f"출금 성공: {amount_to_debit} {currency}, 최종 잔액: {data_deb['balance']}")


def test_wallet_cancel_debit(client: TestClient, wallet_headers: dict):
    """출금 거래 취소 테스트. 테스트 함수 내에서 초기 입금, 출금, 취소를 순차적으로 수행합니다."""
    print(f"\n===== 출금 취소 테스트 (함수 내 설정) =====")
    player_id = TEST_PLAYER_ID
    currency = "KRW"

    # 1. 초기 잔액 설정 (Credit API 사용)
    initial_credit_amount = Decimal("500.00")
    initial_tx_id = generate_unique_id("cred_cancel_setup")
    initial_credit_data = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": initial_tx_id,
        "player_id": player_id,
        "amount": str(initial_credit_amount),
        "currency": currency
    }
    response_cred = client.post(f"{BASE_URL}/api/credit", headers=wallet_headers, json=initial_credit_data)
    assert response_cred.status_code == 200, f"취소 테스트 초기 입금 실패: {response_cred.text}"
    balance_after_credit = Decimal(response_cred.json()["balance"])
    print(f"초기 입금 완료 (Tx: {initial_tx_id}), 잔액: {balance_after_credit}")

    # 2. 취소 대상 Debit 트랜잭션 생성
    debit_tx_id = generate_unique_id("deb_to_cancel")
    amount_to_debit = Decimal("200.25")
    debit_data = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": debit_tx_id,
        "player_id": player_id,
        "amount": str(amount_to_debit),
        "currency": currency
    }
    response_deb = client.post(f"{BASE_URL}/api/debit", headers=wallet_headers, json=debit_data)
    assert response_deb.status_code == 200, f"취소 대상 Debit 생성 실패: {response_deb.text}"
    balance_after_debit = Decimal(response_deb.json()["balance"])
    print(f"취소 대상 Debit 완료 (Tx: {debit_tx_id}), 잔액: {balance_after_debit}")

    # 3. /api/cancel 호출 (생성한 Debit 트랜잭션 ID 사용)
    cancel_tx_id = generate_unique_id("cancel")
    cancel_data = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": cancel_tx_id,
        "player_id": player_id,
        "original_transaction_id": debit_tx_id # 취소할 ID
    }
    response_cancel = client.post(f"{BASE_URL}/api/cancel", headers=wallet_headers, json=cancel_data)
    print_response(response_cancel, f"거래 취소 응답 (Ref Tx: {debit_tx_id}) - 상태 코드: {response_cancel.status_code}")
    response_cancel.raise_for_status()
    data_cancel = response_cancel.json()
    assert data_cancel["player_id"] == player_id

    # 4. 결과 검증 (API 응답)
    # 취소 후 잔액은 Debit 전 잔액(balance_after_credit)과 같아야 함
    expected_balance = balance_after_credit
    # 또는 balance_after_debit + amount_to_debit 와 같아야 함
    # expected_balance = balance_after_debit + amount_to_debit
    assert Decimal(data_cancel["balance"]) == expected_balance, f"취소 실패: 잔액 복구 확인 실패 (기대: {expected_balance}, 실제: {data_cancel['balance']})"
    print(f"출금 취소 성공: Tx {debit_tx_id} 취소됨, 잔액 복구됨: {data_cancel['balance']}")


def test_wallet_cancel_idempotency(client: TestClient, wallet_headers: dict):
    """이미 취소된 거래를 다시 취소 시도 (멱등성/오류 테스트). 함수 내에서 설정, 취소, 중복 취소를 수행합니다."""
    print(f"\n===== 거래 취소 멱등성/오류 테스트 (함수 내 설정) =====")
    player_id = TEST_PLAYER_ID
    currency = "KRW"

    # 1. 초기 잔액 설정
    initial_credit_amount = Decimal("500.00")
    initial_tx_id = generate_unique_id("cred_cancel_idem_setup")
    initial_credit_data = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": initial_tx_id,
        "player_id": player_id,
        "amount": str(initial_credit_amount),
        "currency": currency
    }
    response_cred = client.post(f"{BASE_URL}/api/credit", headers=wallet_headers, json=initial_credit_data)
    assert response_cred.status_code == 200, f"취소 멱등성 테스트 초기 입금 실패: {response_cred.text}"
    print(f"초기 입금 완료 (Tx: {initial_tx_id})")

    # 2. 취소 대상 Debit 트랜잭션 생성
    debit_tx_id = generate_unique_id("deb_for_cancel_idem")
    amount_to_debit = Decimal("200.25")
    debit_data = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": debit_tx_id,
        "player_id": player_id,
        "amount": str(amount_to_debit),
        "currency": currency
    }
    response_deb = client.post(f"{BASE_URL}/api/debit", headers=wallet_headers, json=debit_data)
    assert response_deb.status_code == 200, f"취소 대상 Debit 생성 실패 (멱등성): {response_deb.text}"
    print(f"취소 대상 Debit 완료 (Tx: {debit_tx_id})")

    # 3. 첫 번째 /api/cancel 호출 (정상 취소)
    first_cancel_tx_id = generate_unique_id("first_cancel_idem")
    first_cancel_data = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": first_cancel_tx_id,
        "player_id": player_id,
        "original_transaction_id": debit_tx_id
    }
    response_cancel1 = client.post(f"{BASE_URL}/api/cancel", headers=wallet_headers, json=first_cancel_data)
    assert response_cancel1.status_code == 200, f"첫 번째 Cancel 요청 실패: {response_cancel1.text}"
    balance_after_first_cancel = Decimal(response_cancel1.json()["balance"])
    print(f"첫 번째 Cancel 완료 (Tx: {first_cancel_tx_id}), 잔액: {balance_after_first_cancel}")

    # 4. 동일한 original_transaction_id로 /api/cancel 재호출
    duplicate_cancel_tx_id = generate_unique_id("cancel_dup_idem")
    duplicate_cancel_data = {
        "uuid": str(uuid.uuid4()),
        "transaction_id": duplicate_cancel_tx_id,
        "player_id": player_id,
        "original_transaction_id": debit_tx_id # 동일한 원본 ID
    }
    response_cancel2 = client.post(f"{BASE_URL}/api/cancel", headers=wallet_headers, json=duplicate_cancel_data)
    print_response(response_cancel2, f"중복 거래 취소 응답 (Ref Tx: {debit_tx_id}) - 상태 코드: {response_cancel2.status_code}")

    # 5. 결과 검증
    # API 구현에 따라 4xx 오류 또는 200 OK (상태 변경 없음) 기대
    if response_cancel2.status_code == 200:
        data2 = response_cancel2.json()
        assert data2["player_id"] == player_id
        assert Decimal(data2["balance"]) == balance_after_first_cancel, f"중복 취소 성공(200 OK) 응답이지만 잔액 변경됨"
        print(f"거래 취소 멱등성 확인 (200 OK, 잔액 불변): {data2['balance']}")
    elif response_cancel2.status_code >= 400:
        print(f"이미 취소된 거래 재취소 시 예상된 오류 ({response_cancel2.status_code}) 확인")
    else:
        pytest.fail(f"중복 취소 시 예상치 못한 상태 코드: {response_cancel2.status_code}")

    # 최종 잔액 확인
    final_balance_response = client.post(f"{BASE_URL}/api/balance", headers=wallet_headers, json={"uuid": str(uuid.uuid4()), "player_id": player_id})
    assert final_balance_response.status_code == 200
    final_balance = Decimal(final_balance_response.json()["balance"])
    assert final_balance == balance_after_first_cancel, f"중복 취소 후 최종 잔액 변경됨 (기대: {balance_after_first_cancel}, 실제: {final_balance})"
    print(f"중복 취소 시도 후 최종 잔액 불변 확인: {final_balance}")


def test_wallet_check(client: TestClient, wallet_headers: dict):
    """
    /api/check 엔드포인트 테스트. 특정 플레이어 ID로 인증 토큰을 생성하고,
    해당 플레이어의 지갑을 생성(Credit 호출)한 후, check 엔드포인트를 호출하여 검증합니다.
    """
    test_player_id = "check_test_player_123" # Use a specific player ID for this test
    initial_balance = Decimal("100.00")
    initial_currency = "KRW"

    # Get auth token specifically for this test player
    try:
        specific_player_token = get_auth_token_for_player(client, test_player_id)
    except RuntimeError as e:
        pytest.fail(f"Failed to get token for {test_player_id}: {e}")

    # Create headers with the specific token
    specific_player_headers = {
        "Authorization": f"Bearer {specific_player_token}",
        "Accept-Language": "ko",
        "Host": "localhost"
    }

    # Ensure wallet exists for this player (call credit to create if necessary)
    credit_payload = {
        "uuid": f"init-check-{uuid.uuid4()}",
        "player_id": test_player_id,
        "amount": float(initial_balance), # Use float for JSON serialization
        "currency": initial_currency,
        "transaction_id": f"init-check-tx-{uuid.uuid4()}",
        # Ensure all required fields for CreditRequest are present
        # Add dummy game/round IDs if required by the model, check CreditRequest schema
        # "game_id": "test_game_init",
        # "round_id": "test_round_init"
    }
    # Use the specific player's headers for the init call
    response_init = client.post("/api/credit", headers=specific_player_headers, json=credit_payload)

    # Print response for debugging
    print(f"\nInit Credit Response for {test_player_id} Status: {response_init.status_code}")
    try:
        print(f"Init Credit Response JSON: {response_init.json()}")
    except Exception:
        print(f"Init Credit Response Text: {response_init.text}")

    # We might need to handle the case where credit fails, but for check test,
    # we mainly need the wallet to exist. Status 200 OK (created) or 409 Conflict (already exists) is fine.
    # A 403 Forbidden here would indicate the token/player_id mismatch wasn't fixed.
    assert response_init.status_code in [200, 409], f"Credit call failed with {response_init.status_code}: {response_init.text}"

    # Call the /api/check endpoint with the required JSON body
    check_payload = {
        "uuid": f"check-{uuid.uuid4()}",
        "player_id": test_player_id
    }
    # Use the specific player's headers for the check call
    response = client.post(
        "/api/check",
        headers=specific_player_headers,
        json=check_payload # Add the JSON payload
    )

    print(f"Check Response Status: {response.status_code}")
    try:
        print(f"Check Response JSON: {response.json()}")
    except Exception:
        print(f"Check Response Text: {response.text}")

    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}. Response: {response.text}"
    response_data = response.json()
    assert response_data["status"] == "OK"
    assert response_data["player_id"] == test_player_id
    assert response_data["uuid"] == check_payload["uuid"]

# pytest 실행 커맨드 (예시)
# pytest -v tests/test_wallet_api.py 