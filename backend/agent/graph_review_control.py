"""One active turn's explicit acceptance of a rendered graph preview."""

import asyncio


class GraphReviewControl:
    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._eligible_version: str | None = None
        self._accepted_version: str | None = None
        self._eligible_stage: str | None = None
        self._accepted_stage: str | None = None

    @property
    def accepted_version(self) -> str | None:
        return self._accepted_version

    @property
    def accepted_stage(self) -> str | None:
        return self._accepted_stage

    def open(self, graph_version: str, stage: str = "connections") -> None:
        if (not graph_version or self._eligible_version is not None
                or self._accepted_version is not None or stage not in {"components", "connections"}):
            raise ValueError("a review requires one nonempty candidate version")
        self._eligible_version = graph_version
        self._eligible_stage = stage
        self._accepted_version = None
        self._event.clear()

    def accept(self, graph_version: str) -> bool:
        if not graph_version:
            return False
        if graph_version == self._accepted_version:
            return True
        if graph_version != self._eligible_version:
            return False
        self._accepted_version = graph_version
        self._accepted_stage = self._eligible_stage
        self._event.set()
        return True

    def close(self, graph_version: str) -> None:
        if self._eligible_version == graph_version:
            self._eligible_version = None
            self._eligible_stage = None

    async def wait(self) -> None:
        await self._event.wait()
