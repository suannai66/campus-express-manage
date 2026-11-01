from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from ...common import Input, VersionInput


class StatusInput(VersionInput):
    action: Literal["start_pickup", "confirm_pickup", "confirm_delivery"]
    code: str | None = Field(default=None, min_length=1, max_length=50)

    @model_validator(mode="after")
    def check_code(self):
        if self.action == "confirm_pickup":
            if self.code is None:
                raise ValueError("确认取件必须填写取件码")
        elif "code" in self.model_fields_set:
            raise ValueError("此操作不允许提交取件码")
        return self


class CancelInput(VersionInput):
    reason: str = Field(min_length=1, max_length=200)


Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class ReviewInput(Input):
    rating: int = Field(strict=True, ge=1, le=5)
    tags: list[Tag] = Field(default_factory=list, max_length=5)
    comment: str = Field(default="", max_length=500)
