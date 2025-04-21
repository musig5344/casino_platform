# backend/api/game_history.py
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional

from backend.api.deps import get_db, get_current_user
from backend.models.game_history import GameHistory, BaccaratRound
from backend.models.user import Player # Required for player check
from backend.schemas.game_history import (
    GameHistoryCreate, GameHistoryResponse, UserGameHistoryResponse,
    BaccaratRoundCreate, BaccaratRoundResponse, BaccaratRoundsResponse
)
from backend.cache import redis_client # Assuming redis_client is configured globally
from backend.i18n import Translator, get_translator # For i18n
import logging
import asyncio # For async cache operations

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/history", # Changed prefix to /history
    tags=["Game History"],
    responses={404: {"description": "Not found"}},
)

# Cache related constants/prefixes if needed
HISTORY_CACHE_PREFIX = "game:history"
BACCARAT_ROUNDS_CACHE_PREFIX = "baccarat:rounds"

# --- Helper Functions for Cache Invalidation (Moved from games.py) ---

async def invalidate_user_game_history_cache(user_id: str) -> None:
    """사용자의 게임 기록 관련 캐시를 무효화합니다."""
    # Define the actual cache key pattern based on usage in get_user_game_history
    pattern = f"{HISTORY_CACHE_PREFIX}:user:{user_id}:*"
    logger.debug(f"Invalidating cache for user history pattern: {pattern}")
    # Assuming redis_client has a method like delete_pattern or similar
    # If not, this needs adjustment based on actual cache implementation
    try:
        # This operation can be slow, run in executor if it blocks
        keys = await redis_client.keys(pattern)
        if keys:
            await redis_client.delete(*keys)
            logger.info(f"Invalidated {len(keys)} cache entries for user {user_id} history.")
    except Exception as e:
        logger.error(f"Error invalidating user game history cache for {user_id}: {e}", exc_info=True)


async def invalidate_baccarat_rounds_cache(room_id: str) -> None:
    """특정 방의 바카라 라운드 캐시를 무효화합니다."""
    pattern = f"{BACCARAT_ROUNDS_CACHE_PREFIX}:{room_id}:*"
    logger.debug(f"Invalidating cache for baccarat rounds pattern: {pattern}")
    try:
        keys = await redis_client.keys(pattern)
        if keys:
            await redis_client.delete(*keys)
            logger.info(f"Invalidated {len(keys)} cache entries for baccarat room {room_id} rounds.")
    except Exception as e:
        logger.error(f"Error invalidating baccarat rounds cache for room {room_id}: {e}", exc_info=True)

# --- API Endpoints (Moved from games.py and adapted) ---

@router.post("", response_model=GameHistoryResponse)
async def create_game_history(
    history: GameHistoryCreate,
    db: Session = Depends(get_db),
    # Add translator dependency
    translator: Translator = Depends(get_translator),
    current_user: Player = Depends(get_current_user) # Assuming get_current_user returns Player model
):
    """게임 히스토리를 생성합니다. (i18n 적용)"""
    # Validate user ID consistency if history contains user_id
    if history.user_id != current_user.id:
         raise HTTPException(
             status_code=status.HTTP_403_FORBIDDEN,
             detail=translator('errors.error.user_id_mismatch') # Translate
         )

    # Ensure game exists? (Optional validation)

    try:
        db_history = GameHistory(
            user_id=history.user_id,
            game_type=history.game_type,
            room_id=history.room_id, # Ensure this aligns with GameHistory model
            bet_amount=history.bet_amount,
            bet_type=history.bet_type, # Ensure this aligns with GameHistory model
            result=history.result,
            payout=history.payout,
            game_data=history.game_data # Ensure this aligns with GameHistory model
            # player_id=current_user.id # Set player_id from authenticated user
        )

        db.add(db_history)
        db.commit()
        db.refresh(db_history)

        # Cache invalidation
        await invalidate_user_game_history_cache(history.user_id)

        logger.info(f"Game history created for user {history.user_id}, game: {history.game_type}")
        return db_history
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create game history for user {history.user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error') # Translate
        )


@router.get("/user/{user_id}", response_model=UserGameHistoryResponse)
async def get_user_game_history(
    user_id: str = Path(..., description="사용자 ID"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(10, ge=1, le=100, description="페이지 크기"),
    game_type: Optional[str] = Query(None, description="게임 유형 필터"),
    db: Session = Depends(get_db),
    # Add translator dependency
    translator: Translator = Depends(get_translator),
    current_user: Player = Depends(get_current_user) # Use for authorization check
):
    """사용자의 게임 기록을 조회합니다. (i18n 적용)"""
    # Authorization Check: Ensure the requested user_id matches the authenticated user
    # Or check if the current user has permission to view other users' history (e.g., admin)
    if user_id != current_user.id:
         # Assuming regular users can only see their own history
         raise HTTPException(
             status_code=status.HTTP_403_FORBIDDEN,
             detail=translator('errors.error.authorization_failed') # Translate
         )

    # 캐시 키 생성 (Adjust prefix)
    cache_key = f"{HISTORY_CACHE_PREFIX}:user:{user_id}:type:{game_type or 'all'}:p{page}:s{page_size}"

    try:
        # 캐시된 값이 있으면 반환
        # Make cache access async if redis_client methods are sync
        def _get_cache():
            return redis_client.get_json(cache_key)
        cached_data = await asyncio.get_event_loop().run_in_executor(None, _get_cache)

        if cached_data:
            logger.debug(f"Cache hit for user game history: {cache_key}")
            return UserGameHistoryResponse(**cached_data)
        logger.debug(f"Cache miss for user game history: {cache_key}")

        # DB에서 플레이어 확인 (Authorization already checked, this is redundant?)
        # player = db.query(Player).filter(Player.id == user_id).first()
        # if not player:
        #     # This shouldn't happen if authorization passed, but good as a safeguard
        #     raise HTTPException(
        #         status_code=status.HTTP_404_NOT_FOUND,
        #         detail=translator('errors.error.player_not_found', player_id=user_id) # Translate
        #     )

        # 쿼리 조건 설정
        query = db.query(GameHistory).filter(GameHistory.user_id == user_id)
        if game_type:
            query = query.filter(GameHistory.game_type == game_type)

        # 전체 개수 조회 (Run count in executor)
        def _get_count():
             return query.count()
        total = await asyncio.get_event_loop().run_in_executor(None, _get_count)

        # 페이지네이션 적용 (Run query in executor)
        def _get_results():
            return query.order_by(GameHistory.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        histories = await asyncio.get_event_loop().run_in_executor(None, _get_results)

        # 응답 생성
        # Ensure GameHistory model has a suitable to_dict or similar method, or convert manually
        results_list = []
        for history in histories:
            # Manual conversion example if to_dict doesn't exist or needs adjustment
             results_list.append({
                 "id": history.id,
                 "user_id": history.user_id,
                 "game_type": history.game_type,
                 "room_id": history.room_id,
                 "bet_amount": history.bet_amount,
                 "bet_type": history.bet_type,
                 "result": history.result,
                 "payout": history.payout,
                 "game_data": history.game_data,
                 "created_at": history.created_at.isoformat() # Format datetime
             })

        result_data = {
            "total": total,
            "page": page,
            "page_size": page_size,
            "results": results_list # Use converted list
        }

        # 캐시에 저장 (Run set in executor)
        def _set_cache():
            # Cache the structured dictionary, not the Pydantic model instance directly if using simple JSON cache
            return redis_client.set(cache_key, result_data, ttl=300) # 5분 캐싱

        await asyncio.get_event_loop().run_in_executor(None, _set_cache)
        logger.debug(f"Cached user game history: {cache_key}")

        return result_data
    except Exception as e:
        logger.error(f"Error fetching game history for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error') # Translate
        )


@router.post("/baccarat/rounds", response_model=BaccaratRoundResponse)
async def create_baccarat_round(
    round_data: BaccaratRoundCreate,
    db: Session = Depends(get_db),
    # Add translator dependency
    translator: Translator = Depends(get_translator)
    # Add auth if needed: current_user: Player = Depends(get_current_user)
):
    """바카라 게임 라운드 정보를 기록합니다. (i18n 적용)"""
    # Add validation if needed, e.g., check if room_id exists

    try:
        db_round = BaccaratRound(
            room_id=round_data.room_id,
            player_cards=round_data.player_cards,
            banker_cards=round_data.banker_cards,
            player_score=round_data.player_score,
            banker_score=round_data.banker_score,
            result=round_data.result,
            shoe_number=round_data.shoe_number # Ensure this aligns with model
        )

        db.add(db_round)
        db.commit()
        db.refresh(db_round)

        # Cache invalidation
        await invalidate_baccarat_rounds_cache(round_data.room_id)

        logger.info(f"Baccarat round created for room {round_data.room_id}")
        return db_round
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create baccarat round for room {round_data.room_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error') # Translate
        )


@router.get("/baccarat/rounds/{room_id}", response_model=BaccaratRoundsResponse)
async def get_baccarat_rounds(
    room_id: str = Path(..., description="바카라 방 ID"),
    page: int = Query(1, description="페이지 번호"),
    page_size: int = Query(20, description="페이지당 항목 수"),
    shoe_number: Optional[int] = Query(None, description="슈 번호로 필터링"),
    db: Session = Depends(get_db),
    # Add translator dependency
    translator: Translator = Depends(get_translator)
    # Add auth if needed: current_user: Player = Depends(get_current_user)
):
    """바카라 게임 라운드 기록을 페이지별로 조회합니다. (i18n 적용)"""
    # 캐시 키 생성 (Adjust prefix)
    cache_key = f"{BACCARAT_ROUNDS_CACHE_PREFIX}:{room_id}:p{page}:s{page_size}:shoe{shoe_number or 'all'}"

    try:
        # 캐시된 값이 있으면 반환
        def _get_cache():
            return redis_client.get_json(cache_key)
        cached_data = await asyncio.get_event_loop().run_in_executor(None, _get_cache)

        if cached_data:
            logger.debug(f"Cache hit for baccarat rounds: {cache_key}")
            return BaccaratRoundsResponse(**cached_data) # Ensure response model matches cached data structure
        logger.debug(f"Cache miss for baccarat rounds: {cache_key}")

        # 쿼리 조건 설정
        query = db.query(BaccaratRound).filter(BaccaratRound.room_id == room_id)
        if shoe_number is not None:
            query = query.filter(BaccaratRound.shoe_number == shoe_number)

        # 전체 개수 조회
        def _get_count():
            return query.count()
        total = await asyncio.get_event_loop().run_in_executor(None, _get_count)

        # 페이지네이션 적용
        def _get_results():
            return query.order_by(BaccaratRound.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        rounds = await asyncio.get_event_loop().run_in_executor(None, _get_results)

        # 응답 생성
        # Ensure BaccaratRound model has a suitable to_dict or similar method
        results_list = []
        for round_ in rounds:
             # Manual conversion example
             results_list.append({
                 "id": round_.id,
                 "room_id": round_.room_id,
                 "player_cards": round_.player_cards,
                 "banker_cards": round_.banker_cards,
                 "player_score": round_.player_score,
                 "banker_score": round_.banker_score,
                 "result": round_.result,
                 "shoe_number": round_.shoe_number,
                 "created_at": round_.created_at.isoformat()
             })

        result_data = {
            "total": total,
            "page": page,
            "page_size": page_size,
            "results": results_list
        }

        # 캐시에 저장
        def _set_cache():
            return redis_client.set(cache_key, result_data, ttl=300) # 5분 캐싱

        await asyncio.get_event_loop().run_in_executor(None, _set_cache)
        logger.debug(f"Cached baccarat rounds: {cache_key}")

        return result_data
    except Exception as e:
        logger.error(f"Error fetching baccarat rounds for room {room_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error') # Translate
        ) 