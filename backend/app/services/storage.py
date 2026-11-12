"""Safe local storage implementation and storage service contract."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Protocol


class StorageService(Protocol):
    """Storage operations required by media APIs and workers."""

    async def save_stream(self, key: str, chunks: AsyncIterable[bytes]) -> int: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    def local_file(self, key: str) -> AbstractAsyncContextManager[Path]: ...

    def open_stream(self, key: str) -> AsyncIterable[bytes]: ...


class LocalStorage:
    """Store generated, relative storage keys under one configured root."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        """Resolve a generated key and reject absolute or traversing paths."""

        relative = PurePosixPath(key)
        if (
            not key
            or "\\" in key
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ValueError("Invalid storage key.")
        path = (self.root / Path(*relative.parts)).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            raise ValueError("Storage key escapes the configured root.") from None
        return path

    async def save_stream(self, key: str, chunks: AsyncIterable[bytes]) -> int:
        """Write a stream atomically and return the number of stored bytes."""

        destination = self.path_for(key)
        temporary = destination.with_name(f".{destination.name}.part")
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        total = 0
        try:
            handle = await asyncio.to_thread(temporary.open, "xb")
            async for chunk in chunks:
                total += len(chunk)
                await asyncio.to_thread(handle.write, chunk)
            await asyncio.to_thread(handle.flush)
            await asyncio.to_thread(handle.close)
            await asyncio.to_thread(os.replace, temporary, destination)
            return total
        except BaseException:
            if "handle" in locals() and not handle.closed:
                await asyncio.to_thread(handle.close)
            await asyncio.to_thread(temporary.unlink, missing_ok=True)
            raise

    async def delete(self, key: str) -> None:
        """Remove a stored object if it exists."""

        path = self.path_for(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def exists(self, key: str) -> bool:
        """Check whether an object exists without blocking the event loop."""

        return await asyncio.to_thread(self.path_for(key).is_file)

    @asynccontextmanager
    async def local_file(self, key: str) -> AsyncIterator[Path]:
        """Expose a local processing path for the duration of a worker operation."""

        yield self.path_for(key)

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        """Stream a stored file in bounded chunks."""

        handle = await asyncio.to_thread(self.path_for(key).open, "rb")
        try:
            while chunk := await asyncio.to_thread(handle.read, 1024 * 1024):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)
