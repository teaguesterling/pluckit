"""Named FTS collection wrapper over fledgling's collection infrastructure."""
from __future__ import annotations


class FtsCollection:
    """A named BM25 full-text search collection.

    Wraps fledgling's ``create_fts_collection`` and ``search_collection``
    methods. Obtain via ``plucker.fts_collection("name")``.
    """

    def __init__(self, con, name: str):
        self._con = con
        self.name = name

    def create(self, source_query: str) -> None:
        """Create or replace this collection from a source query."""
        self._con.create_fts_collection(self.name, source_query)

    def search(self, query: str, limit: int = 20) -> list:
        """BM25 search this collection. Returns (id, text, metadata, score) rows."""
        return self._con.search_collection(self.name, query, limit=limit)
