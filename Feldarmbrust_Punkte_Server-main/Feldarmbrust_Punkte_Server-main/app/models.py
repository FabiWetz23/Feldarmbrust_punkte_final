from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    FIELD_CROSSBOW = "field_crossbow"


from typing import Optional

class Shooter(BaseModel):
    id: str = Field(..., description="Unique shooter ID")
    name: str = Field(..., description="Shooter name")
    country: Optional[str] = Field(None, description="Shooter's country")
    start_number: Optional[str] = Field(None, description="Shooter's start number (No)")

    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class Shot(BaseModel):
    shot_number: int = Field(..., ge=1, description="Shot number (1-based)")
    score: float = Field(..., ge=0, le=11, description="Score value (0-11, 11=Inner Ten)")
    timestamp: datetime = Field(default_factory=datetime.now, description="Timestamp")
    
    @validator('score')
    def validate_score(cls, v):
        # Allow 0.5 steps for field crossbow (e.g. 8.5, 9.0, 9.5, 10.0)
        if v * 2 != int(v * 2):
            raise ValueError('Score value must be in 0.5 steps')
        return v


class Series(BaseModel):
    id: str = Field(..., description="Unique series ID")
    shooter_id: str = Field(..., description="ID of the shooter")
    round_number: int = Field(..., ge=-1, description="End number (-1/0=Sighting, 1+=Match)")
    shots_per_series: int = Field(default=6, ge=1, description="Number of shots per end")
    shots: List[Shot] = Field(default_factory=list, description="Shots in the series")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")
    
    @validator('shots')
    def validate_shots_count(cls, v, values):
        if 'shots_per_series' in values and len(v) > values['shots_per_series']:
            raise ValueError(f'Maximum {values["shots_per_series"]} shots allowed')
        return v
    
    def get_series_sum(self) -> float:
        """Calculates sum of all shots in end"""
        return sum(shot.score for shot in self.shots)
    
    def is_complete(self) -> bool:
        """Checks if end is complete"""
        return len(self.shots) == self.shots_per_series


class Competition(BaseModel):
    name: str = Field(default="Field Crossbow Competition", description="Name of the competition")
    event_type: EventType = Field(default=EventType.FIELD_CROSSBOW, description="Type of competition")
    shooters: Dict[str, Shooter] = Field(default_factory=dict, description="All shooters")
    series: Dict[str, Series] = Field(default_factory=dict, description="All series")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")
    
    def get_shooter_series(self, shooter_id: str) -> List[Series]:
        """Returns all series of a shooter"""
        return [s for s in self.series.values() if s.shooter_id == shooter_id]
    
    def get_shooter_total_score(self, shooter_id: str) -> float:
        """Calculates the total score of a shooter (only match ends >= 1)"""
        shooter_series = self.get_shooter_series(shooter_id)
        # Filter sighting rounds
        match_series = [s for s in shooter_series if s.round_number >= 1]
        return sum(series.get_series_sum() for series in match_series)
    
    def get_leaderboard(self) -> List[Dict[str, Any]]:
        """Creates a leaderboard"""
        leaderboard = []
        for shooter_id, shooter in self.shooters.items():
            total_score = self.get_shooter_total_score(shooter_id)
            # Count only match series
            match_series = [s for s in self.get_shooter_series(shooter_id) if s.round_number >= 1]
            series_count = len(match_series)
            
            leaderboard.append({
                "shooter": shooter,
                "total_score": total_score,
                "series_count": series_count,
                "average_score": total_score / series_count if series_count > 0 else 0
            })
        return sorted(leaderboard, key=lambda x: x["total_score"], reverse=True)


# Request/Response Modelle
class ShooterCreate(BaseModel):
    id: str
    name: str
    country: Optional[str] = None
    start_number: Optional[str] = None


class ShooterUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    start_number: Optional[str] = None


class SeriesCreate(BaseModel):
    id: str
    shooter_id: str
    round_number: int
    shots_per_series: int = 6


class ShotCreate(BaseModel):
    shot_number: int
    score: float = Field(..., ge=0, le=11)
    is_inner_circle: bool = False

    @validator('score')
    def validate_score(cls, v):
        if v * 2 != int(v * 2):
            raise ValueError('Score value must be in 0.5 steps')
        return v


class CompetitionState(BaseModel):
    competition: Competition
    leaderboard: List[Dict[str, Any]] = Field(default_factory=list, description="Leaderboard")
    statistics: Dict[str, Any] = Field(default_factory=dict, description="Statistics")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
