from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

IssueLevel = Literal["error", "warning"]

@dataclass(slots=True)
class RequestSpec:
    method: str
    url: str
    params: dict[str, Any] = field(default_factory=dict)
    timeout_sec: int = 30

@dataclass(slots=True)
class ValidationIssue:
    level: IssueLevel
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper()} at '{self.path}': {self.message}"
    
@dataclass(slots=True)
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    def add_error(self, path: str, message: str) -> Node:
        self.issues.append(
            ValidationIssue(level="error", path=path, message=message)
        )
    
    def add_warning(self, path: str, message: str) -> Node:
        self.issues.append(
            ValidationIssue(level="warning", path=path, message=message)
        )
    
    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.level == "error"]
    
    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.level == "warning"]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0
