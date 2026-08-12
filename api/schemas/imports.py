from decimal import Decimal

from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator, model_validator

from db.models import BudgetBand


class ImportOptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    tier: BudgetBand


class ManualOptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: BudgetBand
    title: str
    description: str | None = None
    category_hint: str | None = None
    price_amount: Decimal | None = None
    price_currency: str | None = None

    @field_validator("description", "category_hint", mode="before")
    @classmethod
    def empty_str_as_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("title")
    @classmethod
    def title_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("title must be non-empty after stripping whitespace")
        return value

    @field_validator("price_currency", mode="before")
    @classmethod
    def currency_normalize(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip().upper()
            return stripped or None
        return value

    @model_validator(mode="after")
    def price_and_currency_together(self) -> "ManualOptionIn":
        has_price = self.price_amount is not None
        has_currency = self.price_currency is not None
        if has_price != has_currency:
            raise ValueError("price_currency must be set iff price_amount is set")
        if self.price_currency is not None and len(self.price_currency) != 3:
            raise ValueError("price_currency must be a 3-letter ISO code")
        return self
