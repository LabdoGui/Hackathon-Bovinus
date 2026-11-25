from pydantic import BaseModel

from app.core.enums import CameraMode, DatabaseMode, Environment, RecognitionMode, ScaleMode


class Modes(BaseModel):
    scale: ScaleMode
    camera: CameraMode
    recognition: RecognitionMode
    database: DatabaseMode


class HealthRead(BaseModel):
    status: str
    app: str
    version: str
    environment: Environment
    database: str
    modes: Modes
