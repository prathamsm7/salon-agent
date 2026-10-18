"""Raised when a voice action does not belong to the signed-in customer."""


class VoiceDenied(Exception):
    """The caller asked for a chat or appointment their account cannot change."""
