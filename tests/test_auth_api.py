#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
인증 API 테스트 스크립트 (Pytest 스타일)
- /ua/v1/{casino_key}/{api_token} 엔드포인트의 인증 로직 및 플레이어 자동 생성 검증
- 각 테스트 케이스를 독립적인 함수로 분리 (자체 플레이어/토큰 생성)
- `assert`를 사용하여 결과 검증
"""

import pytest
import time
import uuid
from datetime import datetime
from fastapi.testclient import TestClient # TestClient 타입 힌트 임포트
from urllib.parse import urlparse, parse_qs # URL 파싱을 위해 추가

# 공통 유틸리티 및 상수 임포트
from tests.test_utils import (
    BASE_URL, TEST_PLAYER_ID, ADMIN_HEADERS,
    print_response,
    generate_unique_id, reset_test_environment
)
# 인증 토큰 생성 헬퍼 임포트 (conftest.py)
from tests.conftest import get_auth_token_for_player

# --- Test Functions (Refactored for Independence) ---

def test_authenticate_default_player(client: TestClient):
    """(독립적) 기본 플레이어 인증 및 토큰 획득 테스트 (/ua/v1/...)"""
    print(f"\n테스트: 기본 플레이어 인증 및 토큰 획득")
    try:
        token = get_auth_token_for_player(client, TEST_PLAYER_ID)
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 10
        print(f"기본 플레이어 ({TEST_PLAYER_ID}) 토큰 획득 성공 확인")
    except RuntimeError as e:
        pytest.fail(f"기본 플레이어 ({TEST_PLAYER_ID}) 토큰 획득 실패: {e}")

def test_authenticate_new_player_auto_creation(client: TestClient):
    """(독립적) 신규 플레이어 정보로 인증 시도 시 자동 생성 및 토큰 반환 확인 (/ua/v1/...)"""
    print(f"\n테스트: 신규 플레이어 자동 생성 및 인증")
    player_id = f"auth_new_auto_{str(uuid.uuid4())[:8]}"
    try:
        token = get_auth_token_for_player(client, player_id)
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 10
        print(f"신규 플레이어 ({player_id}) 자동 생성 및 토큰 획득 성공 확인")
    except RuntimeError as e:
        pytest.fail(f"신규 플레이어 ({player_id}) 자동 생성 또는 토큰 획득 실패: {e}")

def test_authenticate_invalid_key(client: TestClient):
    """(독립적) 잘못된 casino_key로 인증 시도 시 401 오류 확인"""
    print(f"\n테스트: 잘못된 Casino Key 인증 시도")
    player_id = f"auth_invalid_key_{str(uuid.uuid4())[:8]}"
    casino_key = "INVALID_CASINO"
    api_token = "qwqw6171"
    auth_endpoint = f"/ua/v1/{casino_key}/{api_token}"
    auth_data = {
        "uuid": str(uuid.uuid4()),
        "player": {"id": player_id, "firstName": "Test", "lastName": "Key", "country": "KR", "currency": "KRW", "session": {"id": "s1", "ip": "127.0.0.1"}},
        "config": {}
    }
    response = client.post(auth_endpoint, json=auth_data, headers={"Host": "localhost"})
    print_response(response, "잘못된 Casino Key 인증 응답")
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials."
    print("잘못된 Casino Key 인증 시 401 오류 및 메시지 확인")

def test_authenticate_invalid_token(client: TestClient):
    """(독립적) 잘못된 api_token으로 인증 시도 시 401 오류 확인"""
    print(f"\n테스트: 잘못된 API Token 인증 시도")
    player_id = f"auth_invalid_token_{str(uuid.uuid4())[:8]}"
    casino_key = "MY_CASINO"
    api_token = "invalid_token"
    auth_endpoint = f"/ua/v1/{casino_key}/{api_token}"
    auth_data = {
        "uuid": str(uuid.uuid4()),
        "player": {"id": player_id, "firstName": "Test", "lastName": "Token", "country": "KR", "currency": "KRW", "session": {"id": "s1", "ip": "127.0.0.1"}},
        "config": {}
    }
    response = client.post(auth_endpoint, json=auth_data, headers={"Host": "localhost"})
    print_response(response, "잘못된 API Token 인증 응답")
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials."
    print("잘못된 API Token 인증 시 401 오류 및 메시지 확인")

def test_authenticate_missing_player_id(client: TestClient):
    """(독립적) 요청 본문에 player.id 누락 시 422 오류 확인"""
    print(f"\n테스트: Player ID 누락 인증 시도")
    casino_key = "MY_CASINO"
    api_token = "qwqw6171"
    auth_endpoint = f"/ua/v1/{casino_key}/{api_token}"
    auth_data = {
        "uuid": str(uuid.uuid4()),
        "player": { # id 누락
            "firstName": "Missing", "lastName": "ID", "country": "KR", "currency": "KRW", "session": {"id": "s1", "ip": "127.0.0.1"}
        },
        "config": {}
    }
    response = client.post(auth_endpoint, json=auth_data, headers={"Host": "localhost"})
    print_response(response, "Player ID 누락 인증 응답")
    assert response.status_code == 422 # Unprocessable Entity
    print("Player ID 누락 시 422 오류 확인")

# --- External Auth Tests (Placeholder/Example) ---
# These would need similar refactoring if they depended on shared state

# def test_external_auth_success(client: TestClient):
#     """외부 게임 프로바이더 인증 성공 테스트"""
#     # ... (Setup: Ensure player exists and has token)
#     # ... (Call GET /external/auth with necessary query params)
#     # ... (Assert response status and structure)

# def test_external_auth_invalid_game(client: TestClient):
#     """외부 게임 프로바이더 인증 - 잘못된 게임 ID"""
#     # ... (Setup)
#     # ... (Call GET /external/auth with invalid game_id)
#     # ... (Assert expected error status, e.g., 404) 