import asyncio
import json
from typing import Any


class JSONStorage:
    def __init__(self, file_name: str, *, loop: asyncio.AbstractEventLoop):
        self.file_name = file_name
        self.loop = loop

        try:
            with open(self.file_name, 'r') as fp:
                self._data = json.load(fp)
        except FileNotFoundError:
            self._data = {}

    def _save(self):
        with open(self.file_name, 'w') as fp:
            json.dump(self._data, fp)

    async def save(self):
        """Saves the data."""
        await self.loop.run_in_executor(None, self._save)

    async def put(self, key: str, value: Any):
        """Puts data."""
        self._data[key] = value
        await self.save()

    def get(self, *args, **kwargs):
        return self._data.get(*args, **kwargs)
