"""Define the shared layout evaluation data model used by adapters, loaders, and metrics."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IR_SCHEMA_VERSION = "0.1.0"

Role = Literal["Header", "Data", "Other"]
Source = Literal["harunobu", "deco", "tablesense", "saus"]


class IRBBox(BaseModel):

    first_row: int
    first_col: int
    last_row: int
    last_col: int

    def area(self) -> int:
        return (self.last_row - self.first_row + 1) * (self.last_col - self.first_col + 1)


class IRTable(BaseModel):

    bbox: IRBBox
    header_rows: list[int] = Field(default_factory=list)
    confidence: float | None = None
    abstain: bool = False


class IRCellRole(BaseModel):

    row: int
    col: int
    role: Role


class IRSheet(BaseModel):

    sheet_name: str
    sheet_index: int
    tables: list[IRTable] = Field(default_factory=list)
    cell_roles: list[IRCellRole] = Field(default_factory=list)
    max_row: int | None = None
    max_col: int | None = None


class IRDocument(BaseModel):

    schema_version: str = IR_SCHEMA_VERSION
    file_name: str
    source: Source
    harunobu_version: str | None = None
    config: dict | None = None
    sheets: list[IRSheet] = Field(default_factory=list)

    def sheet_by_name(self, name: str) -> IRSheet | None:
        for s in self.sheets:
            if s.sheet_name == name:
                return s
        return None
