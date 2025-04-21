from sqlalchemy import Column, Integer, String, Boolean, Text
from backend.database import Base

class Game(Base):
    __tablename__ = "games"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    type = Column(String, nullable=False)
    thumbnail = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False) 