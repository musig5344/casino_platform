from fastapi import APIRouter, Depends, HTTPException, Body, Query, Path, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import asyncio
from functools import lru_cache

from backend.api.deps import get_db, get_current_user
from backend.models.user import Player
from backend.models.game import Game
from backend.schemas.api import GameLaunchRequest, GameLaunchResponse
from backend.schemas.game_history import BaccaratStats
from backend.games.baccarat import get_baccarat_game, BaccaratGame
from backend.database import get_db
from backend.config.settings import get_settings
from backend.cache import redis_client, CacheTier, cached
import secrets
import hashlib
import time
import json
from backend.i18n import Translator, get_translator
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/games",
    tags=["Games"],
    responses={404: {"description": "Not found"}},
)

@router.post("/baccarat/{room_id}/play", response_model=Dict[str, Any])
async def play_baccarat(
    room_id: str = Path(..., description="방 ID"),
    player_bet: float = Query(0, description="플레이어 베팅 금액"),
    banker_bet: float = Query(0, description="뱅커 베팅 금액"),
    tie_bet: float = Query(0, description="타이 베팅 금액"),
    user_id: Optional[str] = Query(None, description="사용자 ID"),
    translator: Translator = Depends(get_translator)
):
    """바카라 게임을 진행하고 결과를 반환합니다. (i18n 적용, payout 포함)"""
    if player_bet < 0 or banker_bet < 0 or tie_bet < 0: # 0 이하 베팅 허용하지 않음
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=translator('errors.error.invalid_bet_amount')
        )
    if player_bet == 0 and banker_bet == 0 and tie_bet == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=translator('errors.error.no_bet_placed') # 베팅 없는 경우 명시적 오류
        )
    
    try:
        game: BaccaratGame = get_baccarat_game(room_id)
        # 참고: 현재 play_round()는 베팅 금액을 인자로 받지 않음.
        # 만약 게임 로직 내에서 베팅 처리 및 결과 저장이 필요하다면 play_round 수정 필요.
        # 여기서는 API 레벨에서 payout만 계산하여 추가하는 것으로 가정.
        game_result = game.play_round()
        
        # payout 계산 로직 추가
        winner = game_result.get('result')
        bet_amount = 0
        bet_type = None
        
        # 어떤 베팅 유형으로 이겼는지 확인
        if winner == 'player' and player_bet > 0:
            bet_amount = player_bet
            bet_type = 'player'
        elif winner == 'banker' and banker_bet > 0:
            bet_amount = banker_bet
            bet_type = 'banker'
        elif winner == 'tie' and tie_bet > 0:
            bet_amount = tie_bet
            bet_type = 'tie'
        
        payout = 0
        if bet_type and bet_amount > 0:
            # calculate_payout 함수 사용
            payout = game.calculate_payout(bet_type, bet_amount)
            
        game_result['payout'] = payout # 계산된 payout 추가
        game_result['winning_bet_type'] = bet_type # 어떤 베팅으로 이겼는지 정보 추가 (선택 사항)

        logger.info(f"Baccarat round played in room {room_id} by user {user_id or 'guest'}. Winner: {winner}, BetType: {bet_type}, BetAmount: {bet_amount}, Payout: {payout}")
        return game_result
    except Exception as e:
        logger.error(f"Error playing baccarat in room {room_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error')
        )

@router.get("/baccarat/{room_id}/stats", response_model=BaccaratStats)
@cached(key_prefix="baccarat_stats", ttl=30)
async def get_baccarat_stats(
    room_id: str = Path(..., description="방 ID"),
    translator: Translator = Depends(get_translator)
):
    """바카라 게임의 통계 정보를 반환합니다. (i18n 적용)"""
    try:
        game = get_baccarat_game(room_id)
        stats_data = game.get_stats_and_recent_results()

        required_keys = ["statistics", "total_games", "player_win_percentage", "banker_win_percentage", "tie_percentage", "last_shoe_results"]
        if not all(key in stats_data for key in required_keys) or not isinstance(stats_data["statistics"], dict):
             logger.error(f"Unexpected stats data structure from get_baccarat_game for room {room_id}")
             raise HTTPException(status_code=500, detail=translator('errors.error.internal_server_error'))

        response_data = {
            "player_wins": stats_data["statistics"].get("player_wins", 0),
            "banker_wins": stats_data["statistics"].get("banker_wins", 0),
            "tie_wins": stats_data["statistics"].get("tie_wins", 0),
            "total_rounds": stats_data["total_games"],
            "player_win_percentage": stats_data["player_win_percentage"],
            "banker_win_percentage": stats_data["banker_win_percentage"],
            "tie_percentage": stats_data["tie_percentage"],
            "last_shoe_results": stats_data["last_shoe_results"]
        }
        logger.debug(f"Fetched baccarat stats for room {room_id}")
        return response_data

    except Exception as e:
        logger.error(f"Error getting baccarat stats for room {room_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error')
        )

@router.get("/", response_model=List[dict])
async def get_games(
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """사용 가능한 게임 목록 조회 (번역 적용)"""
    try:
        games = db.query(Game).filter(Game.is_active == True).all()

        translated_games = []
        for game in games:
            translated_games.append({
                "id": game.id,
                "name": translator(f"games.{game.provider.lower()}.{game.type.lower()}.name", game.name),
                "provider": game.provider,
                "type": game.type,
                "thumbnail": game.thumbnail,
                "description": translator(f"games.{game.provider.lower()}.{game.type.lower()}.description", game.description),
                "is_active": game.is_active
            })

        logger.debug(f"Fetched {len(translated_games)} active games.")
        return translated_games
    except Exception as e:
        logger.error(f"Error fetching game list: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error')
        )

@router.post("/launch", response_model=GameLaunchResponse)
async def launch_game(
    request: GameLaunchRequest,
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator),
    current_user: Player = Depends(get_current_user)
):
    """게임 실행 URL 생성 (i18n 적용)"""
    if request.player_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=translator('errors.error.user_id_mismatch')
        )

    try:
        game = db.query(Game).filter(Game.id == request.game_id, Game.is_active == True).first()
        if not game:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translator('errors.error.game_not_found', game_id=request.game_id)
            )

        settings = get_settings()
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(8)
        token_string = f"{current_user.id}:{request.game_id}:{timestamp}:{nonce}:{settings.SECRET_KEY}"
        launch_token = hashlib.sha256(token_string.encode()).hexdigest()

        game_url_str = f"{settings.GAMEPROVIDER_LAUNCH_URL}/{game.provider}/{game.type}/{request.game_id}?token={launch_token}&lang={translator.locale}&player_id={current_user.id}"

        logger.info(f"Generated launch URL for game {request.game_id} for player {current_user.id}")
        return GameLaunchResponse(success=True, game_url=game_url_str)

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"Error launching game {request.game_id} for player {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error')
        ) 