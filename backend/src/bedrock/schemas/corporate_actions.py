from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from bedrock.models.corporate_action import CorporateAction


class CorporateActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str  # split / reverse_split
    effective_date: date
    ratio: Decimal  # new shares per old share; a JSON string
    source: str

    @classmethod
    def from_model(cls, action: CorporateAction) -> "CorporateActionOut":
        return cls.model_validate(action)
