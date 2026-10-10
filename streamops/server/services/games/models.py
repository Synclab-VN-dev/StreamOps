"""Strict Game Manager V1 wire and provider models."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

GameProcessState = Literal["RUNNING","STOPPED","STARTING","STOPPING","FAILED","UNKNOWN"]
GameWindowState = Literal["FOREGROUND","BACKGROUND","NOT_DETECTED","UNKNOWN"]
GameCaptureState = Literal["VERIFIED_ACTIVE","CONFIGURED_ONLY","INACTIVE","ERROR","UNKNOWN"]
GameSelectionState = Literal["SELECTED","NOT_SELECTED","UNKNOWN"]

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class LaunchPolicy(StrictModel):
    strategy: Literal["steam_app"]
    appId: str = Field(pattern=r"^[1-9][0-9]*$")

class DetectionPolicy(StrictModel):
    processNames: tuple[str, ...] = Field(min_length=1)
    @model_validator(mode="after")
    def validate_names(self):
        if any(not name.strip() or "/" in name or "\\" in name for name in self.processNames):
            raise ValueError("process names must be basenames without paths")
        return self

class StopPolicy(StrictModel):
    strategy: Literal["graceful"]
    forceAllowed: Literal[False] = False

class GameDefinition(StrictModel):
    id: str
    provider: Literal["steam"]
    providerGameId: str = Field(pattern=r"^[1-9][0-9]*$")
    name: str = Field(min_length=1, max_length=160)
    enabled: bool
    metadataSource: Literal["static", "steam_local"] = "static"
    launch: LaunchPolicy
    detection: DetectionPolicy
    stop: StopPolicy
    @model_validator(mode="after")
    def validate_identity(self):
        if self.id != f"{self.provider}:{self.providerGameId}" or self.launch.appId != self.providerGameId:
            raise ValueError("canonical id/appId mismatch")
        return self

class Seed(StrictModel):
    schemaVersion: Literal[1]
    games: tuple[GameDefinition, ...]

    @model_validator(mode="after")
    def validate_unique(self):
        ids = [game.id for game in self.games]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate canonical game IDs")
        return self

class ProcessIdentity(StrictModel):
    state: GameProcessState = "UNKNOWN"
    pid: int | None = None
    session_id: int | None = None
    executable: str | None = None
    created_at: str | None = None
    observed_at: str | None = None
    stale: bool = True

class GameObservation(StrictModel):
    owned: bool | None = None
    installed: bool | None = None
    process: ProcessIdentity = Field(default_factory=ProcessIdentity)
    window: GameWindowState = "UNKNOWN"
    obsCapture: GameCaptureState = "UNKNOWN"
    selectedForStream: GameSelectionState = "UNKNOWN"

class GamePolicy(StrictModel):
    launch: LaunchPolicy
    detection: DetectionPolicy
    stop: StopPolicy

class GameRecord(StrictModel):
    id: str
    provider: str
    name: str
    metadataSource: str
    enabled: bool
    observation: GameObservation = Field(default_factory=GameObservation)
    capabilities: dict[str, bool] = Field(default_factory=lambda: {"start": False, "stop": False, "restart": False})
    capability_reason: str | None = "not_verified"
    revision: int = 0

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
