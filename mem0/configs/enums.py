from enum import Enum


class MemoryType(Enum):
    SEMANTIC = "semantic_memory"
    EPISODIC = "episodic_memory"
    PROCEDURAL = "procedural_memory"


class FeedbackStatus(Enum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    INCORRECT = "incorrect"
    OUTDATED = "outdated"
    NEEDS_REVIEW = "needs_review"
