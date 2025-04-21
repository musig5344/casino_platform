from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from backend.schemas.user import AuthRequest, AuthResponse
from backend.models.user import Player as PlayerModel
from backend.models.wallet import Wallet as WalletModel
from backend.database import get_db
from backend.config.database import settings
from backend.api.deps import get_current_player_id, get_current_user
from backend.cache import redis_client
import jwt
import uuid
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import secrets
import hmac
import hashlib
import time
import json
from fastapi import status
import os
from backend.models.game_history import GameHistory
from backend.schemas.api import GameLaunchRequest, GameLaunchResponse
from backend.i18n import Translator, get_translator

router = APIRouter(
    prefix="/ua/v1",
    tags=["Authentication"]
)

logger = logging.getLogger(__name__)

# 유효한 카지노 키와 API 토큰 정의
VALID_CASINO_KEY = "MY_CASINO"
VALID_API_TOKEN = "qwqw6171"

# 외부 게임 제공자 통합 설정
GAMEPROVIDER_API_KEY = settings.GAMEPROVIDER_API_KEY
GAMEPROVIDER_API_SECRET = settings.GAMEPROVIDER_API_SECRET
GAMEPROVIDER_LAUNCH_URL = settings.GAMEPROVIDER_LAUNCH_URL

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

@router.post("/{casino_key}/{api_token}", response_model=AuthResponse)
async def authenticate_player(
    request: AuthRequest,
    casino_key: str,
    api_token: str,
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """
    Authenticate a player, find or create them in the database, and return game launch URLs with a JWT token.
    Handles i18n for potential error messages.

    - **casino_key**: Casino identifier (path parameter)
    - **api_token**: API token for authentication (path parameter)
    - **request body**: Contains player and config details.

    Returns:
        AuthResponse: Contains game launch URLs (entry and entryEmbedded).

    Raises:
        HTTPException 400: If casino_key or api_token is invalid (basic check).
        HTTPException 422: If request body validation fails.
        HTTPException 500: If JWT creation or other internal process fails.
    """
    # Validate casino key and API token
    # Use specific keys for error messages
    if casino_key.lower() != VALID_CASINO_KEY.lower():
        logger.warning(f"Authentication failed: Invalid casino_key - {casino_key}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=translator('errors.error.invalid_credentials'))

    if api_token != VALID_API_TOKEN:
        logger.warning(f"Authentication failed: Invalid api_token - {api_token}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=translator('errors.error.invalid_credentials'))

    player_data_from_request = request.player
    session_info = player_data_from_request.session or {}

    try:
        # Find player in the database
        db_player = db.query(PlayerModel).filter(PlayerModel.id == player_data_from_request.id).first()

        player_created = False
        if not db_player:
            # Player not found, create new player and wallet
            logger.info(f"Player {player_data_from_request.id} not found. Creating new player.")
            db_player = PlayerModel(
                id=player_data_from_request.id,
                first_name=player_data_from_request.firstName,
                last_name=player_data_from_request.lastName,
                country=player_data_from_request.country,
                currency=player_data_from_request.currency
                # Add other fields if necessary, ensure defaults or nullables are handled
            )
            db.add(db_player)

            # Create wallet for the new player
            db_wallet = WalletModel(
                player_id=db_player.id,
                balance=0.0, # Initial balance, adjust as needed
                currency=db_player.currency
            )
            db.add(db_wallet)
            player_created = True
            # Commit changes for new player and wallet
            db.commit()
            db.refresh(db_player)
            logger.info(f"New player {db_player.id} and wallet created successfully.")
        elif hasattr(player_data_from_request, 'update') and player_data_from_request.update:
            # Update existing player if requested
            logger.info(f"Updating player {db_player.id} information.")
            db_player.first_name = player_data_from_request.firstName
            db_player.last_name = player_data_from_request.lastName
            # Update other fields if necessary
            db.commit()
            db.refresh(db_player)
            logger.info(f"Player {db_player.id} updated successfully.")

        # Create JWT payload
        access_token_payload = {
            "sub": db_player.id,
            "sessionId": session_info.get("id", ""), # Ensure session ID is included if available
            "firstName": db_player.first_name,
            "country": db_player.country,
            "currency": db_player.currency,
            "reqUuid": request.uuid # Include request UUID for traceability
        }
        access_token = create_access_token(data=access_token_payload)

        # Generate JSESSIONID (consider if this is still needed or handled differently)
        jsession_id = str(uuid.uuid4())

        # Base URL should come from configuration
        # settings = get_settings() # Assuming settings are loaded
        # base_entry_path = settings.GAME_ENTRY_BASE_URL or "/entry"
        base_entry_path = "/entry" # Placeholder

        entry_url = f"{base_entry_path}?params={access_token}&JSESSIONID={jsession_id}"
        entry_embedded = f"{entry_url}&embedded=true"

        logger.info(f"Authentication successful for player_id={db_player.id}, casino_key={casino_key}")
        return AuthResponse(entry=entry_url, entryEmbedded=entry_embedded)

    except jwt.PyJWTError as e:
        logger.error(f"JWT error during authentication: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=translator('errors.error.internal_server_error'))
    except Exception as e:
        # Rollback database changes if any error occurs during the process
        db.rollback()
        logger.error(f"Database or unexpected error during authentication: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=translator('errors.error.internal_server_error'))

@router.post("/external/auth", response_model=GameLaunchResponse)
async def external_auth(
    request: GameLaunchRequest = None,
    player_id: str = Depends(get_current_player_id),
    game_id: str = Query(None, description="외부 게임 ID"),
    table_id: str = Query(None, description="특정 테이블 ID (선택 사항)"),
    language: str = Query("ko", description="언어 설정"),
    db: Session = Depends(get_db)
):
    """
    외부 게임 프로바이더 인증 및 게임 URL 생성 API
    
    - player_id: 플레이어 ID (현재 인증된 사용자)
    - game_id: 시작할 게임 ID
    - table_id: 특정 테이블 ID (선택 사항, 라이브 게임용)
    - language: 언어 설정 (기본값: 한국어)
    
    외부 게임 프로바이더에 접속하기 위한 인증된 URL을 반환합니다.
    """
    # 플레이어 정보 조회
    player = db.query(PlayerModel).filter(PlayerModel.id == player_id).first()
    if not player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player {player_id} not found"
        )
    
    # 지갑 정보 조회
    wallet = db.query(WalletModel).filter(WalletModel.player_id == player_id).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wallet not found for player {player_id}"
        )
    
    # 외부 게임 통합 설정 (환경 변수에서 로드)
    api_key = os.getenv("EXTERNAL_GAME_API_KEY", GAMEPROVIDER_API_KEY)
    api_secret = os.getenv("EXTERNAL_GAME_API_SECRET", GAMEPROVIDER_API_SECRET)
    launch_url = os.getenv("EXTERNAL_GAME_LAUNCH_URL", GAMEPROVIDER_LAUNCH_URL)
    casino_id = os.getenv("EXTERNAL_GAME_CASINO_ID", "demo_casino")
    
    # 타임스탬프 및 유니크 값 생성
    timestamp = int(time.time())
    nonce = secrets.token_hex(8)
    session_id = str(uuid.uuid4())
    
    # 파라미터 준비
    params = {
        "token": player_id,
        "uuid": f"ext_{player_id}_{timestamp}_{nonce}",
        "player": {
            "id": player_id,
            "firstName": player.first_name,
            "lastName": player.last_name,
            "country": player.country,
            "language": language,
            "currency": wallet.currency,
            "session": {
                "id": f"session_{timestamp}_{nonce}",
                "ip": "127.0.0.1"  # 실제 구현 시 클라이언트 IP 사용
            }
        },
        "casino": {
            "id": casino_id,
            "apiKey": api_key
        }
    }
    
    # 게임 정보 추가
    if game_id:
        params["game"] = game_id
    if table_id:
        params["table"] = table_id
    
    # 서명 생성
    data_to_sign = json.dumps(params, separators=(',', ':'))
    signature = hmac.new(
        api_secret.encode(),
        data_to_sign.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # 최종 URL 생성
    encoded_params = urlencode({"params": data_to_sign, "signature": signature})
    game_url = f"{launch_url}?{encoded_params}"
    
    # 캐시에 세션 정보 저장 (선택 사항)
    session_key = f"external:session:{player_id}"
    session_data = {
        "game_id": game_id,
        "table_id": table_id,
        "timestamp": timestamp,
        "currency": wallet.currency,
        "balance": float(wallet.balance)
    }
    redis_client.set(session_key, session_data, ttl=3600)  # 1시간 세션 캐싱
    
    # 세션 정보 데이터베이스에 저장 (선택적)
    db_session = GameHistory(
        id=int(hash(session_id) % 2147483647),  # Integer 범위 내의 값으로 변환
        user_id=player_id,
        game_type=game_id or "external",
        room_id=table_id or "default",
        bet_amount=0.0,  # 초기 베팅 금액은 0
        bet_type="none",  # 초기 베팅 타입
        result="pending",  # 초기 결과
        payout=0.0,  # 초기 지불금액
        game_data={
            "language": language,
            "table_id": table_id,
            "session_id": session_id,
            "provider": "external",
            "status": "active",
            "expires_at": (datetime.now() + timedelta(hours=4)).isoformat()
        }
    )
    db.add(db_session)
    db.commit()
    
    return GameLaunchResponse(
        success=True,
        game_url=game_url,
        session_id=session_id,
        token=player_id,
        expires_at=datetime.now().isoformat()
    )