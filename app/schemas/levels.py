from pydantic import BaseModel, ConfigDict


class LevelStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    level: int
    xp: int
    xp_into_level: int
    xp_for_next_level: int
