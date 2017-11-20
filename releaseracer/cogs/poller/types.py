import collections
import datetime
import enum
import logging

import discord
import pytz

from releaseracer.bot import ReleaseRacer
from releaseracer.storage import JSONStorage
from releaseracer.formatting import format_size, format_datetime
from .constants import HASH_FIELD


class ReleaseTracker:
    def __init__(self, bot: ReleaseRacer):
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.storage = JSONStorage('releases.json', loop=bot.loop)

    async def track(self, release):
        key = 'last_release_' + release.channel.name.lower()

        # get last release from storage
        last_release = self.storage.get(key, None)

        # new build!
        if last_release is None or last_release != release.release_build:
            self.log.info('detected new build: %s (%s)', release.release_build, release.channel)

            # store this build
            await self.storage.put(key, release.release_build)

            # dispatch
            self.bot.dispatch('new_build', release)
        else:
            # stale
            self.log.info('stale build: %s (%s)', release.release_build, release.channel)


class ReleaseBuildInfo(collections.namedtuple('ReleaseBuildInfo', 'channel hashes release_build size')):
    """Release build information."""

    @property
    def color(self):
        if self.channel is ReleaseChannel.STABLE or self.channel is ReleaseChannel.PTB:
            return discord.Color.blurple()
        elif self.channel is ReleaseChannel.CANARY:
            return discord.Color.gold()

    @property
    def embed(self):
        release_channel_name = self.channel.name.title().replace('Ptb', 'PTB')

        embed = discord.Embed(title=f'{release_channel_name} build `{self.release_build}`', color=self.color)
        embed.description = '`' + HASH_FIELD.format(hashes=self.hashes) + '`'

        embed.add_field(name='Size', value=format_size(self.size), inline=False)

        california_time = datetime.datetime.now(pytz.timezone('US/Pacific'))
        embed.set_footer(text=f'{format_datetime(datetime.datetime.utcnow())} UTC'
                              f', {format_datetime(california_time)} Pacific',
                         icon_url='https://cdn.discordapp.com/emojis/286248029931962368.png')
        return embed


class ReleaseChannel(enum.Enum):
    STABLE = enum.auto()
    PTB = enum.auto()
    CANARY = enum.auto()


#: Release build information.
ReleaseHashes = collections.namedtuple('ReleaseHashes', 'vendor main')
