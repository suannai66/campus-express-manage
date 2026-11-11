from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from ...common import Input, VersionInput


class StatusInput(VersionInput):
    action: Literal["start_pickup", "confirm_pickup", "confirm_delivery", "confirm_receipt"]


class CancelInput(VersionInput):
    reason: str = Field(min_length=1, max_length=200)


Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class ReviewInput(Input):
    rating: int = Field(strict=True, ge=1, le=5)
    tags: list[Tag] = Field(default_factory=list, max_length=5)
    comment: str = Field(default="", max_length=500)
