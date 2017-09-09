from typing import Dict, Any

import discord
from discord.ext import commands
from discord.ext.commands import Bot


class ReleaseRacer(Bot):
    def __init__(self, cfg: Dict[Any, Any]):
        super().__init__(
            command_prefix=commands.when_mentioned_or(*cfg['prefixes']),
            description=cfg.get('description', 'ReleaseRacer'),
            game=discord.Game(name=cfg.get('game', 'with Discord builds!'))
        )

        #: The configuration dict.
        self.cfg = cfg

        # load all cogs
        for cog in self.cfg.get('cogs', []):
            self.load_extension('releaseracer.cogs.' + cog)
