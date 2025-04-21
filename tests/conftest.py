import sys
import os
import pytest
import uuid
from urllib.parse import urlparse, parse_qs
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine
from decimal import Decimal

# 테스트 실행 전에 프로젝트 루트 경로를 sys.path에 추가
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

# 공통 유틸리티 및 상수 임포트
from tests.test_utils import TEST_PLAYER_ID, generate_unique_id, print_response

# --- Database Setup for Testing ---
# 실제 DB 대신 테스트용 DB 사용 권장 (예: SQLite 인메모리 또는 별도 테스트 DB)
# 여기서는 기존 연결 문자열을 사용한다고 가정
# 실제 프로젝트에서는 환경 변수 등을 통해 테스트 DB 연결 문자열을 관리해야 함
from backend.config.settings import settings # 수정된 임포트 경로
from backend.database import Base, get_db # 실제 get_db 와 Base 가져오기

# 테스트용 데이터베이스 엔진 및 세션 메이커 생성
# DATABASE_URL = settings.DATABASE_URL # 기존 설정 사용
# 여기서는 명시적으로 테스트용 URL 사용 예시 (필요시 수정)
# TEST_DATABASE_URL = settings.DATABASE_URL + "_test" if "_test" not in settings.DATABASE_URL else settings.DATABASE_URL
# Docker 환경 등 고려 시, 기존 URL 그대로 사용하거나 환경변수 활용
TEST_DATABASE_URL = settings.DATABASE_URL
print(f"\nUsing Test Database URL: {TEST_DATABASE_URL}")
engine = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- Performance Test Mode Check ---
IS_PERF_TEST_MODE = os.environ.get("PERF_TEST_MODE", "false").lower() == "true"
if IS_PERF_TEST_MODE:
    print("\n*** Running in Performance Test Mode: DB changes will PERSIST! ***")

# 테스트용 DB 테이블 생성 (세션 시작 시 한번)
@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    if not IS_PERF_TEST_MODE:
        print("\nSetting up test database (creating tables if not exist)...")
        try:
            Base.metadata.create_all(bind=engine)
            print("Test database tables checked/created.")
        except Exception as e:
            print(f"Error checking/creating test database tables: {e}")
            pytest.fail(f"Failed to setup test DB tables: {e}")
    else:
        print("\nSkipping DB setup in performance test mode.")
    yield

# --- Function-Scoped Transaction Fixture (Conditional) ---
@pytest.fixture(scope="function")
def db_transaction():
    """(Conditional) Starts transaction, yields session, rolls back unless PERF_TEST_MODE is true."""
    if IS_PERF_TEST_MODE:
        # In perf test mode, yield a session but manage the transaction explicitly
        db = TestingSessionLocal()
        print("\n[Fixture-Perf] Yielding session with EXPLICIT transaction management (COMMIT EXPECTED).")
        transaction = db.begin() # Start transaction explicitly
        try:
            yield db # Provide the session to the test
            # If the test completes without error, commit
            transaction.commit()
            print("[Fixture-Perf] Transaction committed.")
        except Exception:
            # If an exception occurred during the test execution yield db, rollback
            print("[Fixture-Perf] Exception detected during test, rolling back transaction.")
            transaction.rollback()
            raise # Re-raise the exception so pytest knows the test failed
        finally:
            # Always close the session
            print("[Fixture-Perf] Closing session.")
            db.close()
    else:
        # Original rollback logic for functional tests
        connection = engine.connect()
        transaction = connection.begin()
        db = Session(bind=connection)
        print("\n[Fixture] Function-scoped transaction started & session yielded (ROLLBACK ENABLED).")
        try:
            yield db
        finally:
            print("[Fixture] Rolling back function-scoped transaction.")
            db.close()
            transaction.rollback()
            connection.close()

# --- Autouse Fixture for Dependency Override (Conditional) ---
@pytest.fixture(scope="function", autouse=True)
def apply_db_override(db_transaction: Session):
    """(Conditional) Overrides get_db with the session from db_transaction fixture."""
    # Override always happens, but the session yielded by db_transaction differs
    try:
        from backend.main import app
        app.dependency_overrides[get_db] = lambda: db_transaction
        mode = "performance (no rollback)" if IS_PERF_TEST_MODE else "functional (rollback)"
        print(f"[Fixture] Applied function-scoped DB override for {mode} mode.")
        yield
    finally:
        from backend.main import app
        if get_db in app.dependency_overrides:
            del app.dependency_overrides[get_db]
            print("[Fixture] Removed function-scoped DB override.")

# --- Other Fixtures ---

# 세션 스코프 TestClient (오버라이드 없음)
@pytest.fixture(scope="session")
def client(setup_test_database):
    """세션 스코프 TestClient (DB 오버라이드 없음 - 필요시 인증 등에 사용)"""
    try:
        from backend.main import app
        # 여기서 오버라이드하지 않음
        with TestClient(app) as c:
            print("\nSession-scoped TestClient created.")
            yield c
        print("Session-scoped TestClient closed.")
    except Exception as e:
        pytest.fail(f"Session-scoped client 생성 실패: {e}")

# 함수 스코프 TestClient (실제 테스트용)
# 참고: 위 client fixture와 이름이 같으면 pytest가 혼동할 수 있으므로 이름 변경 권장
# 하지만 여기서는 TestClient 인스턴스가 필요한 곳에서 client fixture를 요청하면
# pytest가 스코프(function)에 맞는 것을 찾아 주입할 것으로 기대 (autouse override fixture와 함께)
# 만약 문제가 계속되면 이름을 변경 (예: test_client_function_scope)

# Helper function to get auth token for a specific player
def get_auth_token_for_player(client: TestClient, player_id: str) -> str:
    """주어진 player_id에 대한 인증 토큰을 획득합니다."""
    casino_key = "MY_CASINO"
    api_token = "qwqw6171"
    auth_endpoint = f"/ua/v1/{casino_key}/{api_token}"
    auth_data = {
        "uuid": str(uuid.uuid4()),
        "player": {
            "id": player_id, # Use the provided player_id
            "firstName": "테스트", # Generic first name
            "lastName": player_id.split('_')[-1] if '_' in player_id else player_id, # Use part of ID as last name
            "country": "KR",
            "currency": "KRW",
            "session": {"id": generate_unique_id(f"session_{player_id}"), "ip": "127.0.0.1"}
        },
        "config": {}
    }
    print(f"\n인증 요청 (Player: {player_id}): {auth_endpoint}")
    try:
        response = client.post(auth_endpoint, json=auth_data, headers={"Host": "localhost"})
        print_response(response, f"플레이어 ({player_id}) 인증 응답")
        response.raise_for_status() # Raise exception for bad status codes
        response_data = response.json()
        entry_url = response_data.get("entry")
        if not entry_url:
            raise RuntimeError(f"플레이어 '{player_id}' 인증 실패: 응답에 entry URL 없음")

        parsed_url = urlparse(entry_url)
        query_params = parse_qs(parsed_url.query)
        token = query_params.get("params", [None])[0]
        if not token:
            raise RuntimeError(f"플레이어 '{player_id}' 인증 토큰 획득 실패: entry URL에서 토큰(params) 추출 불가")
        print(f"플레이어 ({player_id}) 인증 토큰 획득 성공")
        return token
    except Exception as e:
        # pytest.fail causes issues when called outside a test function/fixture
        # raise RuntimeError for clarity
        raise RuntimeError(f"플레이어 '{player_id}' 인증 중 오류 발생: {e}")


@pytest.fixture(scope="session")
def default_auth_token(client: TestClient): # 세션 스코프 클라이언트 사용
    """세션 스코프 TestClient를 사용하여 기본 인증 토큰 획득"""
    # Use the new helper function for the default player
    try:
        return get_auth_token_for_player(client, TEST_PLAYER_ID)
    except RuntimeError as e:
        pytest.fail(str(e))

@pytest.fixture(scope="function")
def wallet_headers(default_auth_token: str) -> dict:
    """지갑 API 요청용 기본 헤더를 생성합니다. (함수 스코프) - 주의: default_auth_token 미사용 상태"""
    # This fixture might need rethinking if default_auth_token is truly unused now
    # For now, provide a placeholder or fetch dynamically if needed per test
    # Returning minimal headers, specific tests should fetch their own tokens
    return {
        # "Authorization": f"Bearer {default_auth_token}", # Removed dependency
        "Accept-Language": "ko",
        "Host": "localhost"
    }

# @pytest.fixture(scope="function")
# def test_data() -> WalletTestData:
#     """각 테스트 함수를 위한 독립적인 테스트 데이터 저장소"""
#     return WalletTestData()

@pytest.fixture(scope="module")
def active_game(client: TestClient): # 세션 스코프 클라이언트 사용
    """테스트용 활성 게임 데이터를 DB에 생성하고 객체를 반환하는 fixture (모듈 스코프)"""
    from backend.models.game import Game
    # 모듈 스코프 데이터는 별도 세션으로 관리 (함수 트랜잭션과 분리)
    SessionModule = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionModule()

    game_id_to_create = f"test_game_{uuid.uuid4()}"
    test_game = Game(
        id=game_id_to_create,
        name="Test Baccarat",
        provider="TestProvider",
        type="baccarat",
        thumbnail="/img/test_baccarat.png",
        description="A baccarat game for testing",
        is_active=True
    )
    created_game_id = None
    try:
        existing_game = db.query(Game).filter(Game.name == "Test Baccarat").first()
        if not existing_game:
             db.add(test_game)
             db.commit()
             db.refresh(test_game)
             created_game_id = test_game.id
             print(f"\n[Fixture] 활성 테스트 게임 생성됨 (ID: {created_game_id}) - Module Scope")
             yield test_game
        else:
             print(f"\n[Fixture] 활성 테스트 게임 이미 존재 (Name: Test Baccarat)")
             yield existing_game
    finally:
        if created_game_id is not None:
            # 정리 시에도 별도 세션 사용
            db_cleanup = SessionModule()
            try:
                game_to_delete = db_cleanup.query(Game).filter(Game.id == created_game_id).first()
                if game_to_delete:
                    db_cleanup.delete(game_to_delete)
                    db_cleanup.commit()
                    print(f"\n[Fixture] 테스트 게임 삭제됨 (ID: {created_game_id}) - Module Scope")
            finally:
                db_cleanup.close()
        db.close()

# 테스트 함수 실행 전후로 DB 테이블 초기화하는 fixture
@pytest.fixture(scope="function", autouse=True)
def clean_db_tables():
    """(Conditional) Cleans tables before test if NOT in performance mode."""
    if not IS_PERF_TEST_MODE:
        from backend.models.wallet import Wallet as WalletModel, Transaction as TransactionModel
        print(f"\n[Fixture] Cleaning wallet and transaction table data before functional test...")
        Session = TestingSessionLocal
        db = Session()
        tables_to_clean = [TransactionModel.__table__, WalletModel.__table__] # Add other tables if needed
        try:
            for table in tables_to_clean:
                db.execute(table.delete())
            db.commit()
            print(f"[Fixture] Wallet and transaction table data deleted.")
        except Exception as e:
            db.rollback()
            print(f"[Fixture] Error cleaning tables: {e}")
            pytest.fail(f"Failed to clean DB tables: {e}")
        finally:
            db.close()
    else:
        print(f"\n[Fixture] Skipping table cleaning in performance test mode.")
    yield
    # No cleanup after yield in performance mode
    if not IS_PERF_TEST_MODE:
        print(f"[Fixture] Functional test function finished.") 