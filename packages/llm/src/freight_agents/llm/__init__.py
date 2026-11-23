"""Provider-neutral model interface for freight-agents."""

from .cassette import CassetteMiss, RecordingModel, ReplayModel, request_key
from .costs import PRICES, Price, cost_usd
from .fake import ScriptedModel, ScriptExhausted
from .types import (
    ImagePart,
    Message,
    Model,
    ModelTurn,
    Part,
    Stop,
    TextPart,
    ToolCall,
    ToolResult,
    ToolSpec,
    Usage,
)

__version__ = "0.1.0"

__all__ = [
    "PRICES",
    "CassetteMiss",
    "ImagePart",
    "Message",
    "Model",
    "ModelTurn",
    "Part",
    "Price",
    "RecordingModel",
    "ReplayModel",
    "ScriptExhausted",
    "ScriptedModel",
    "Stop",
    "TextPart",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "Usage",
    "__version__",
    "cost_usd",
    "request_key",
]
