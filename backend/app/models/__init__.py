"""Database model registry used by API code and Alembic migrations."""

from app.models.character import Character, CharacterReference
from app.models.clip_candidate import ClipCandidate
from app.models.dubbing_project import DubbingProject
from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.project import Project
from app.models.publication import Publication, PublicationRevision
from app.models.scene import EnvironmentReference, Scene, SceneShot
from app.models.timeline import Timeline, TimelineClip, TimelineTrack
from app.models.transcript import Transcript, TranscriptSegment
from app.models.transcript_revision import TranscriptRevision
from app.models.user import User
from app.models.voice_profile import VoiceConsent, VoiceProfile
from app.models.youtube import YouTubeConnection, YouTubeOAuthState

__all__ = [
    "Character",
    "CharacterReference",
    "ClipCandidate",
    "DubbingProject",
    "EnvironmentReference",
    "MediaAsset",
    "ProcessingJob",
    "Project",
    "Publication",
    "PublicationRevision",
    "Scene",
    "SceneShot",
    "Timeline",
    "TimelineClip",
    "TimelineTrack",
    "Transcript",
    "TranscriptRevision",
    "TranscriptSegment",
    "User",
    "VoiceConsent",
    "VoiceProfile",
    "YouTubeConnection",
    "YouTubeOAuthState",
]
