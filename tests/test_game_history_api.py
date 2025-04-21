#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
게임 기록 API 테스트 스크립트 (/history) - TestClient 사용
각 테스트 함수는 독립적으로 실행되며, 필요한 데이터(플레이어, 기록 등)를 자체적으로 생성합니다.
"""

import sys
# import os # No longer needed here for path manipulation
import uuid
import time
import pytest
from fastapi.testclient import TestClient # Import TestClient type hint
import random

# # Add project root to sys.path to allow backend imports (Moved to conftest.py)
# project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# if project_root not in sys.path:
#     sys.path.insert(0, project_root)

# 공통 유틸리티 임포트
# Assuming test_utils is in the same directory or pytest handles discovery
from test_utils import (
    BASE_URL, ADMIN_HEADERS, TEST_ENV,
    print_response, track_test_result, print_test_summary, reset_test_results,
    generate_unique_id, requests
)
# 인증 토큰 생성 헬퍼 임포트
from conftest import get_auth_token_for_player

# 번역 로더는 TestClient 사용 시 필요 없음 (API 내에서 처리됨)
# try:
#     from backend.i18n import translations 
# except ImportError as e:
#     pytest.fail(f"backend.i18n 에서 translations 임포트 실패: {e}")

# --- Fixtures --- 
# 모듈 스코프 auth_token fixture 제거
# @pytest.fixture(scope="module")
# def auth_token(): ...

# --- Helper Function for Creating History --- 
def create_test_history(client: TestClient, token: str, player_id: str, count: int, game_type_prefix: str = "test_game"):
    """주어진 플레이어 ID에 대해 지정된 개수의 테스트 기록을 생성합니다."""
    created_ids = []
    headers = {"Authorization": f"Bearer {token}", "Host": "localhost"}
    for i in range(count):
        data = {
            "user_id": player_id,
            "game_type": f"{game_type_prefix}_{i}",
            "room_id": f"room_{i}",
            "bet_amount": 10.0 + i,
            "bet_type": "main",
            "result": "win" if i % 2 == 0 else "loss",
            "payout": 10.0 + i if i % 2 == 0 else -(10.0 + i),
            "game_data": {"round": f"round_{str(uuid.uuid4())[:8]}"}
        }
        response = client.post("/history", json=data, headers=headers)
        if response.status_code not in [200, 201]:
            print(f"Warning: Failed to create test history {i+1}/{count} for {player_id}. Status: {response.status_code}, Response: {response.text}")
        else:
             created_ids.append(response.json().get("id"))
    print(f"Created {len(created_ids)} history records for player {player_id}")
    return created_ids

# --- Helper Function for Creating Baccarat Rounds --- 
def create_test_baccarat_rounds(client: TestClient, room_id: str, count: int):
    """주어진 방 ID에 대해 지정된 개수의 테스트 바카라 라운드 기록을 생성합니다."""
    created_ids = []
    headers = {"Host": "localhost"} # Baccarat round creation is unauthenticated
    for i in range(count):
        data = {
            "room_id": room_id,
            "player_cards": [f"H{i+1}", f"S{i+2}"],
            "banker_cards": [f"C{i+3}", f"D{i+4}"],
            "player_score": (i+1 + i+2) % 10,
            "banker_score": (i+3 + i+4) % 10,
            "result": random.choice(["Player Win", "Banker Win", "Tie"]),
            "shoe_number": 1 + (i // 52), # Example shoe number logic
            # API schema might require timestamp, add if needed
            # "timestamp": time.time()
        }
        response = client.post("/history/baccarat/rounds", json=data, headers=headers)
        if response.status_code not in [200, 201]:
            print(f"Warning: Failed to create test baccarat round {i+1}/{count} for room {room_id}. Status: {response.status_code}, Response: {response.text}")
        else:
             created_ids.append(response.json().get("id"))
    print(f"Created {len(created_ids)} baccarat rounds for room {room_id}")
    return created_ids

# --- Test Functions --- 

@pytest.mark.parametrize("game_type, bet_amount, result, room_id, bet_type, payout", [
    ("baccarat", 100.0, "win", "bacc_room_1", "player", 100.0),
    ("blackjack", 50.5, "loss", "bljk_room_vip", "main", -50.5),
    ("roulette", 10.0, "win", "roul_eu_1", "red", 10.0),
])
def test_create_general_game_history(client: TestClient, game_type, bet_amount, result, room_id, bet_type, payout):
    """(독립적) 일반 게임 기록 생성 테스트. 테스트용 플레이어 및 토큰을 함수 내에서 생성."""
    test_name = f"기록 생성 - {game_type} {result}"
    print(f"\n===== {test_name} ======")

    # 테스트용 플레이어 ID 및 토큰 생성
    test_player_id = f"create_hist_user_{str(uuid.uuid4())[:8]}"
    try:
        token = get_auth_token_for_player(client, test_player_id)
    except RuntimeError as e:
        pytest.fail(f"Failed to get token for {test_player_id}: {e}")

    headers = {"Authorization": f"Bearer {token}", "Host": "localhost"}
    data = {
        "user_id": test_player_id, # 생성된 플레이어 ID 사용
        "game_type": game_type,
        "room_id": room_id,
        "bet_amount": bet_amount,
        "bet_type": bet_type,
        "result": result,
        "payout": payout,
        "game_data": {"details": "some game details", "round_id": generate_unique_id("round")}
    }

    response = client.post("/history", json=data, headers=headers)
    print_response(response, f"{test_name} 응답")

    assert response.status_code in [200, 201], f"{test_name} - Expected 200 or 201, got {response.status_code}"
    response_data = response.json()
    assert response_data["user_id"] == test_player_id

@pytest.mark.parametrize("total_records, page, page_size, expected_count", [
    (7, 1, 5, 5), # 첫 페이지
    (7, 2, 5, 2), # 두 번째 페이지 (나머지)
    (12, 1, 10, 10), # 한 페이지에 다 들어감
    (12, 2, 10, 2),
    (3, 1, 5, 3), # 전체 개수보다 페이지 크기가 큼
    (0, 1, 5, 0), # 기록이 없는 경우
])
def test_get_user_game_history(client: TestClient, total_records, page, page_size, expected_count):
    """(독립적) 사용자 게임 기록 조회 및 페이지네이션 테스트. 함수 내에서 플레이어 및 기록 생성."""
    test_name = f"기록 조회 - 페이지네이션 (Total: {total_records}, Page: {page}, Size: {page_size})"
    print(f"\n===== {test_name} ======")

    # 테스트용 플레이어 ID 및 토큰 생성
    test_player_id = f"get_hist_user_{str(uuid.uuid4())[:8]}"
    try:
        token = get_auth_token_for_player(client, test_player_id)
    except RuntimeError as e:
        pytest.fail(f"Failed to get token for {test_player_id}: {e}")

    # 필요한 만큼 테스트 기록 생성
    if total_records > 0:
        create_test_history(client, token, test_player_id, total_records)

    headers = {"Authorization": f"Bearer {token}", "Host": "localhost"}
    params = {"page": page, "page_size": page_size}

    response = client.get(f"/history/user/{test_player_id}", params=params, headers=headers)
    print_response(response, f"{test_name} 응답")

    assert response.status_code == 200, f"{test_name} - Expected 200, got {response.status_code}"
    data = response.json()
    assert "total" in data
    assert data.get("page") == page
    assert data.get("page_size") == page_size
    assert "results" in data
    assert data["total"] == total_records # 생성한 기록 개수와 일치하는지 확인
    assert len(data["results"]) == expected_count # 해당 페이지의 기록 개수 확인
    # 모든 결과의 user_id가 생성한 플레이어 ID와 일치하는지 확인 (선택적)
    for record in data["results"]:
        assert record["user_id"] == test_player_id

    print(f"조회된 기록 수: {len(data['results'])}, 전체: {data['total']}\n")

# --- Unauthorized/Not Found Tests (Refactored for Independence) ---

def test_get_user_game_history_unauthorized(client: TestClient):
    """(독립적) 다른 사용자의 게임 기록 접근 시도 (403 Forbidden 예상)"""
    test_name = f"기록 조회 - 권한 없음 시나리오"
    print(f"\n===== {test_name} ======")

    # 사용자 A 생성 및 토큰 획득
    user_a_id = f"auth_user_a_{str(uuid.uuid4())[:8]}"
    try:
        user_a_token = get_auth_token_for_player(client, user_a_id)
    except RuntimeError as e:
        pytest.fail(f"Failed to get token for {user_a_id}: {e}")

    # 사용자 B ID 정의 (생성할 필요는 없음)
    user_b_id = f"auth_user_b_{str(uuid.uuid4())[:8]}"

    expected_lang = "ko"
    headers = {
        "Authorization": f"Bearer {user_a_token}", # 사용자 A 토큰 사용
        "Accept-Language": expected_lang,
        "Host": "localhost"
    }
    expected_error_message = "이 작업을 수행할 권한이 없습니다." # Based on ko/errors.json

    # 사용자 A의 토큰으로 사용자 B의 기록 조회 시도
    response = client.get(f"/history/user/{user_b_id}", headers=headers)
    print_response(response, f"{test_name} 응답 (User A token requesting User B history)")

    assert response.status_code == 403, f"{test_name} - Expected 403, got {response.status_code}"
    response_data = response.json()
    assert "detail" in response_data
    print(f"실제 반환된 메시지: {response_data['detail']} (예상: {expected_error_message})")
    assert response_data["detail"] == expected_error_message, f"{test_name} - Error message mismatch"

@pytest.mark.parametrize("lang", ["ko", "en"])
def test_get_user_game_history_not_found_i18n(client: TestClient, lang):
    """(독립적) 존재하지 않는 사용자의 게임 기록 조회 시 권한 오류(403) 및 번역된 메시지 확인"""
    test_name = f"기록 조회 - 사용자 없음/권한 없음 시나리오 [{lang.upper()}]"
    print(f"\n===== {test_name} ======")

    # 테스트용 사용자 생성 및 토큰 획득 (호출자)
    caller_user_id = f"auth_caller_{str(uuid.uuid4())[:8]}"
    try:
        caller_token = get_auth_token_for_player(client, caller_user_id)
    except RuntimeError as e:
        pytest.fail(f"Failed to get token for {caller_user_id}: {e}")

    # 존재하지 않는 사용자 ID 정의
    non_existent_player_id = f"non_existent_player_{str(uuid.uuid4())[:8]}"

    headers = {
        "Authorization": f"Bearer {caller_token}",
        "Accept-Language": lang,
        "Host": "localhost"
    }

    try:
        response = client.get(f"/history/user/{non_existent_player_id}", headers=headers)
        print_response(response, f"{test_name} 응답")

        expected_status_code = 403 # API가 404 대신 403을 반환하는 현재 로직 기준
        assert response.status_code == expected_status_code
        response_data = response.json()
        assert "detail" in response_data

        if lang == "ko":
            expected_error_message = "이 작업을 수행할 권한이 없습니다."
        elif lang == "en":
            expected_error_message = "You do not have permission to perform this action."
        else:
             expected_error_message = "Unknown language error message"

        print(f"실제 반환된 메시지 [{lang.upper()}]: {response_data['detail']} (예상: {expected_error_message})")
        assert response_data["detail"] == expected_error_message, f"{test_name} - Error message mismatch for {lang}"

        print(f"테스트 [{test_name}] 성공 (예상된 {expected_status_code} 및 번역 메시지 확인)")

    except Exception as e:
         pytest.fail(f"{test_name} 중 오류 발생: {e}")

# --- Baccarat Tests (Refactored for Independence) ---

@pytest.mark.parametrize("room_id_suffix, round_details", [
    ("player_win", {"player_cards": ["S2", "H5"], "banker_cards": ["D10", "CK"], "player_score": 7, "banker_score": 0, "result": "Player Win"}),
    ("banker_win", {"player_cards": ["HA", "S8"], "banker_cards": ["C9", "D9", "S3"], "player_score": 9, "banker_score": 1, "result": "Banker Win"}),
    ("tie", {"player_cards": ["D6", "H6"], "banker_cards": ["S6", "C6"], "player_score": 2, "banker_score": 2, "result": "Tie"}),
])
def test_create_baccarat_round_history(client: TestClient, room_id_suffix, round_details):
    """(독립적) 바카라 라운드 기록 생성 테스트. 고유한 방 ID 사용."""
    # Generate a unique room ID for each test execution within the parameterization
    test_room_id = f"bacc_create_{room_id_suffix}_{str(uuid.uuid4())[:8]}"
    test_name = f"바카라 라운드 생성 - Room: {test_room_id}, Result: {round_details['result']}"
    print(f"\n===== {test_name} ======")

    data = {
        "room_id": test_room_id, # Use unique room ID
        "player_cards": round_details["player_cards"],
        "banker_cards": round_details["banker_cards"],
        "player_score": round_details["player_score"],
        "banker_score": round_details["banker_score"],
        "result": round_details["result"],
        "shoe_number": 1,
        # "timestamp": time.time() # Add if required by API
    }
    headers = {"Host": "localhost"}

    response = client.post("/history/baccarat/rounds", json=data, headers=headers)
    print_response(response, f"{test_name} 응답")

    assert response.status_code in [200, 201], f"{test_name} - Expected 200 or 201, got {response.status_code}"
    response_data = response.json()
    assert response_data["room_id"] == test_room_id
    # ... other assertions ...
    assert response_data["result"] == round_details["result"]

@pytest.mark.parametrize("total_rounds, page, page_size, expected_count", [
    (7, 1, 5, 5),
    (7, 2, 5, 2),
    (12, 1, 10, 10),
    (12, 2, 10, 2),
    (3, 1, 5, 3),
    (0, 1, 5, 0),
])
def test_get_baccarat_round_history(client: TestClient, total_rounds, page, page_size, expected_count):
    """(독립적) 바카라 라운드 기록 조회 및 페이지네이션 테스트. 함수 내에서 기록 생성."""
    # Generate a unique room ID for this specific test run
    test_room_id = f"bacc_get_{str(uuid.uuid4())[:8]}"
    test_name = f"바카라 라운드 조회 - Room: {test_room_id} (Total: {total_rounds}, Page: {page}, Size: {page_size})"
    print(f"\n===== {test_name} ======")

    # 필요한 만큼 테스트 바카라 라운드 기록 생성
    if total_rounds > 0:
        create_test_baccarat_rounds(client, test_room_id, total_rounds)

    headers = {"Host": "localhost"}
    params = {"page": page, "page_size": page_size}

    response = client.get(f"/history/baccarat/rounds/{test_room_id}", params=params, headers=headers)
    print_response(response, f"{test_name} 응답")

    assert response.status_code == 200, f"{test_name} - Expected 200, got {response.status_code}"
    data = response.json()
    assert "total" in data
    assert data.get("page") == page
    assert data.get("page_size") == page_size
    assert "results" in data
    assert data["total"] == total_rounds
    assert len(data["results"]) == expected_count
    # 모든 결과의 room_id가 생성한 방 ID와 일치하는지 확인
    for record in data["results"]:
        assert record["room_id"] == test_room_id

    print(f"조회된 라운드 수: {len(data['results'])}, 전체: {data['total']}\n")

# --- Test Runner Logic (if needed, or use pytest directly) ---
# def run_game_history_tests():
#     print("\n===== 게임 기록 API 테스트 시작 =====")
#     reset_test_results()
#     # Call test functions here
#     print_test_summary()

# if __name__ == "__main__":
#     run_game_history_tests()
#     # Exit based on test results if needed 