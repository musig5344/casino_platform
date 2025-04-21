from pydantic import BaseModel, constr, Field, field_validator
from typing import Dict

class Player(BaseModel):
    id: constr(min_length=1, max_length=50)
    firstName: constr(min_length=1, max_length=50)
    lastName: constr(min_length=1, max_length=50)
    country: constr(min_length=2, max_length=2)
    currency: constr(min_length=3, max_length=3)
    session: Dict[str, str] = Field(default_factory=dict, description="Session information, e.g., {\"id\": \"session123\", \"ip\": \"192.168.0.1\"}")

    @field_validator('country')
    @classmethod
    def validate_country(cls, v: str) -> str:
        if not v.isupper() or not v.isalpha() or len(v) != 2:
            raise ValueError('Country code must be a 2-letter uppercase ISO 3166 code')
        return v

    @field_validator('currency')
    @classmethod
    def validate_currency(cls, v: str) -> str:
        if not v.isupper() or not v.isalpha() or len(v) != 3:
            raise ValueError('Currency code must be a 3-letter uppercase ISO 4217 code')
        return v

class AuthRequest(BaseModel):
    uuid: constr(min_length=1) = Field(..., description="Unique request ID")
    player: Player
    config: Dict[str, Dict] = Field(default_factory=dict, description="Game configuration, e.g., {\"brand\": {\"id\": \"brand1\"}}")

class AuthResponse(BaseModel):
    entry: str
    entryEmbedded: str 