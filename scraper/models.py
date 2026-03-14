"""Data models for scraped exercises and catalog output."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ExerciseRecord(BaseModel):
    """Single exercise entry in the catalog."""

    id: str = Field(..., description="Stable exercise identifier")
    exerciseName: str = Field(..., description="Name of the exercise")
    description: str = Field(default="", description="Exercise description or instructions")
    videoUrlOriginal: str = Field(default="", description="Original video URL from source")
    videoPathLocal: str = Field(default="", description="Relative path under data/exercises/")
    sourceExerciseUrl: str = Field(default="", description="URL of the exercise page on hep2go")
    downloadStatus: Literal["success", "skipped", "failed"] = Field(
        default="failed", description="Whether the video was downloaded"
    )
    contentType: str = Field(default="", description="Video MIME type if known")
    fileSizeBytes: int | None = Field(default=None, description="Downloaded file size in bytes")


class Catalog(BaseModel):
    """Top-level catalog written to data/exercises.json."""

    generatedAt: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="ISO timestamp of catalog generation",
    )
    sourcePage: str = Field(..., description="URL of the scraped listing page")
    totalExercises: int = Field(default=0, description="Number of exercise records")
    totalVideos: int = Field(default=0, description="Number of successfully downloaded videos")
    failedDownloads: int = Field(default=0, description="Number of failed or skipped downloads")
    exercises: list[ExerciseRecord] = Field(default_factory=list, description="Exercise records")


class ExtractionReport(BaseModel):
    """Run diagnostics written to data/extraction-report.json."""

    generatedAt: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="ISO timestamp",
    )
    mode: Literal["full", "dry"] = Field(..., description="Scrape mode")
    totalScraped: int = Field(default=0)
    successCount: int = Field(default=0)
    skippedCount: int = Field(default=0)
    failedCount: int = Field(default=0)
    failedItems: list[dict] = Field(default_factory=list, description="id, reason per failure")
    errors: list[str] = Field(default_factory=list, description="Global errors")
