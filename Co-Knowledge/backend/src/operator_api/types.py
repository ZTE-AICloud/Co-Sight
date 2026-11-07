"""Result types shared by custom operators."""

from __future__ import annotations

from typing import TypedDict


class ChunkMetadata(TypedDict, total=False):
    """Metadata accepted by the ingestion pipeline.

    ``source`` is the display name and ``content_expand`` an optional expanded
    body.  Additional keys are preserved.
    """

    source: str
    content_expand: str


class Chunk(TypedDict):
    """One operator output chunk."""

    content: str
    metadata: ChunkMetadata


#: ``file_split`` / ``file_parse`` operators return a list of chunks.
OperatorResult = list[Chunk]
