# backend/scripts/initialize_db.py
import sys
import os
# 프로젝트 루트를 Python 경로에 추가 (backend 디렉토리의 상위 디렉토리)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.models.game import Game
from backend.database import SessionLocal, engine, Base # engine, Base 추가
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def initialize_games_data():
    """Initialize game data in the database."""
    # 데이터베이스 테이블 생성 (없으면)
    try:
        logger.info("Creating database tables if they don't exist...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables checked/created.")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}", exc_info=True)
        return # 테이블 생성 실패 시 중단

    db = SessionLocal()
    try:
        # Check if games already exist
        existing_games = db.query(Game).count()
        if existing_games > 0:
            logger.info(f"{existing_games} games already exist. Skipping initialization.")
            return

        # Define default games using translation keys
        # Note: name and description are now keys for translation
        # Namespace 'games.' is added to the keys to match the file structure
        games_to_add = [
            Game(
                id="baccarat",
                name="games.game.baccarat.name",
                provider="internal",
                type="table",
                thumbnail="/images/games/baccarat.jpg",
                description="games.game.baccarat.description",
                is_active=True
            ),
            Game(
                id="blackjack",
                name="games.game.blackjack.name",
                provider="internal",
                type="table",
                thumbnail="/images/games/blackjack.jpg",
                description="games.game.blackjack.description",
                is_active=True
            ),
            Game(
                id="roulette",
                name="games.game.roulette.name",
                provider="internal",
                type="table",
                thumbnail="/images/games/roulette.jpg",
                description="games.game.roulette.description",
                is_active=True
            ),
            # Add other games as needed following the same pattern
        ]

        # Add game data
        db.add_all(games_to_add)
        db.commit()
        logger.info(f"{len(games_to_add)} games initialized successfully.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error initializing games: {e}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    initialize_games_data() 