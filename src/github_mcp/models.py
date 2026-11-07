"""Output models: the trimmed shape of GitHub data we hand back to the model.

GitHub's repository JSON has ~100 fields, most of them URLs. Sending all of it
wastes the model's context window, so each model keeps only what is useful.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RepoSummary(BaseModel):
    full_name: str
    description: str | None
    url: str
    stars: int
    language: str | None
    updated_at: datetime

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "RepoSummary":
        return cls(
            full_name=data["full_name"],
            description=data.get("description"),
            url=data["html_url"],
            stars=data["stargazers_count"],
            language=data.get("language"),
            updated_at=data["updated_at"],
        )


class Repository(RepoSummary):
    default_branch: str
    forks: int
    open_issues: int
    topics: list[str]
    license: str | None
    is_private: bool
    is_archived: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Repository":
        return cls(
            **RepoSummary.from_api(data).model_dump(),
            default_branch=data["default_branch"],
            forks=data["forks_count"],
            open_issues=data["open_issues_count"],
            topics=data.get("topics", []),
            license=(data.get("license") or {}).get("spdx_id"),
            is_private=data["private"],
            is_archived=data["archived"],
        )


class RepoSearchResult(BaseModel):
    total_count: int
    items: list[RepoSummary]


class DirectoryEntry(BaseModel):
    name: str
    path: str
    type: str  # "file", "dir", "symlink" or "submodule"
    size: int


class DirectoryListing(BaseModel):
    repository: str
    path: str
    entries: list[DirectoryEntry]


class FileContents(BaseModel):
    repository: str
    path: str
    size: int
    is_binary: bool
    truncated: bool
    content: str | None


class IssueSummary(BaseModel):
    number: int
    title: str
    state: str
    author: str | None
    labels: list[str]
    comments: int
    created_at: datetime
    updated_at: datetime
    url: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "IssueSummary":
        return cls(
            number=data["number"],
            title=data["title"],
            state=data["state"],
            author=(data.get("user") or {}).get("login"),
            labels=[label["name"] for label in data.get("labels", [])],
            comments=data.get("comments", 0),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            url=data["html_url"],
        )


class IssueList(BaseModel):
    repository: str
    state: str
    returned: int
    has_more: bool
    items: list[IssueSummary]


class PullRequestSummary(BaseModel):
    number: int
    title: str
    state: str
    author: str | None
    draft: bool
    head: str
    base: str
    created_at: datetime
    updated_at: datetime
    url: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "PullRequestSummary":
        return cls(
            number=data["number"],
            title=data["title"],
            state=data["state"],
            author=(data.get("user") or {}).get("login"),
            draft=data.get("draft", False),
            head=data["head"]["ref"],
            base=data["base"]["ref"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            url=data["html_url"],
        )


class PullRequestList(BaseModel):
    repository: str
    state: str
    returned: int
    has_more: bool
    items: list[PullRequestSummary]
