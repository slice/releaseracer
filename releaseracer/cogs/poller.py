import asyncio
import collections
import datetime
import enum
import json
import logging
import re
from typing import Any

import aiohttp
import discord
import pytz
from discord.ext.commands import command, is_owner, Context

from releaseracer.bot import ReleaseRacer

# A regex that processes script tags returned by Discord.
SCRIPT_TAG_REGEX = re.compile(
    r"<script src=\"/assets/([a-f0-9]+)\.js\" [^>]+></script>"
)

# A regex that extracts the release build from the main JS file.
RELEASE_BUILD_REGEX = re.compile(
    r"{environment:\"[a-z]+\",release:\"(\d+)\",ign"
)


class ReleaseChannel(enum.Enum):
    STABLE = enum.auto()
    PTB = enum.auto()
    CANARY = enum.auto()


#: Release build information.
ReleaseHashes = collections.namedtuple('ReleaseHashes', 'vendor i18n main')


HASH_FIELD = """
main    {hashes.main}
vendor  {hashes.vendor}
i18n    {hashes.i18n}
"""


def _format_size(byte_amount: int) -> str:
    return f'{round(byte_amount / (10 ** 6), 2)} MB'


def _format_datetime(dt: datetime.datetime, *, twenty_four=False) -> str:
    return dt.strftime('%d/%m ' + ('%H:%M' if twenty_four else '%I:%M %p'))


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

        embed.add_field(name='Size', value=_format_size(self.size), inline=False)

        california_time = datetime.datetime.now(pytz.timezone('US/Pacific'))
        embed.set_footer(text=f'{_format_datetime(datetime.datetime.utcnow())} UTC'
                              f', {_format_datetime(california_time)} Pacific',
                         icon_url='https://cdn.discordapp.com/emojis/286248029931962368.png')
        return embed


class ReleaseExtractorError(Exception):
    """
    An error thrown by the release extractor.
    """


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


class ReleaseTracker:
    def __init__(self, bot: ReleaseRacer):
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.storage = JSONStorage('releases.json', loop=bot.loop)

    async def track(self, release: ReleaseBuildInfo):
        key = 'last_release' + release.channel.name

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


class Poller:
    def __init__(self, bot: ReleaseRacer):
        self.bot = bot
        self.log = logging.getLogger(__name__)

        #: The tracker that tracks new releases.
        self._tracker = ReleaseTracker(self.bot)

        #: The ``aiohttp`` session to use for downloading.
        self.session = aiohttp.ClientSession(
            loop=bot.loop,
            read_timeout=bot.cfg.get('download_timeout', 10),
            headers=bot.cfg.get('poller_headers', {
                'User-Agent': bot.cfg.get('user_agent', f'ReleaseRacer/1.0 aiohttp/{aiohttp.__version__}'),
                'X-Hey-Discord': "We love you guys <3! We're just here for build notifications, please don't notice us."
            })
        )

        #: The interval at which to poll at (in seconds).
        self.poll_interval = bot.cfg.get('default_poll_interval', 60)

        #: The list of pollers.
        self._poller_tasks = {}

        # create pollers.
        self._create_pollers()

    def __unload(self):
        self.session.close()
        self._stop_pollers()

    def _stop_pollers(self):
        # stop all pollers.
        for task in self._poller_tasks.values():
            task.cancel()

    def reboot(self):
        """Reboots the poller task."""
        self._stop_pollers()
        self._create_pollers()

    def _create_pollers(self):
        """Creates pollers."""
        self.log.info('booting pollers')

        for channel in (ReleaseChannel.CANARY, ReleaseChannel.STABLE, ReleaseChannel.PTB):
            self.log.info('%s: boot', channel)
            self._poller_tasks[channel.name.lower()] = self.bot.loop.create_task(self._make_poller(channel))

    def get_login_page(self, channel: ReleaseChannel) -> str:
        """Returns the login page URL for a channel."""
        base = 'https://{channel_name}discordapp.com/login'

        if channel is ReleaseChannel.STABLE:
            return base.format(channel_name='')
        else:
            return base.format(channel_name=channel.name.lower() + '.')

    def get_asset_url(self, channel: ReleaseChannel, hash: str) -> str:
        """Returns the asset URL for a JS hash."""
        base = 'https://{channel_name}discordapp.com/assets/{hash}.js'

        if channel is ReleaseChannel.STABLE:
            return base.format(channel_name='', hash=hash)
        else:
            return base.format(channel_name=channel.name.lower() + '.', hash=hash)

    async def get_release_build_information(self, channel: ReleaseChannel) -> ReleaseBuildInfo:
        """Extracts release build information from Discord."""

        self.log.info('%s: fetching', channel)

        # fetch the login page
        async with self.session.get(self.get_login_page(channel)) as resp:
            if resp.status != 200:
                self.log.fatal('%s: failed to fetch login page, got http %d (%s)', channel, resp.status, resp.reason)
                raise ReleaseExtractorError(f'{channel}: unexpectedly got http {resp.status} {resp.reason}')

            # read response data.
            body = await resp.text()

            # get some groups...
            hashes = SCRIPT_TAG_REGEX.findall(body)

            if not hashes:
                raise ReleaseExtractorError(f'{channel}: failed to match script tags')

            # extract the js hashes from the groups
            release_hashes = ReleaseHashes(vendor=hashes[0], i18n=hashes[1], main=hashes[2])

            # fetch main js file
            async with self.session.get(self.get_asset_url(channel, release_hashes.main)) as resp:
                main = await resp.text()
                size = len(main)

                # match release build
                build_match = RELEASE_BUILD_REGEX.search(main)

                if not build_match:
                    raise ReleaseExtractorError(f"{channel}: failed to get release build num from main js file")

                release_build = build_match.group(1)

            # return release build info
            return ReleaseBuildInfo(channel=channel, hashes=release_hashes, release_build=release_build, size=size)

    def _make_poller(self, channel: ReleaseChannel):
        """Creates a poller for a specific release channel."""

        async def _poll():
            self.log.info('%s: poll task started', channel)

            while True:
                self.log.info('%s: fetching build information', channel)

                try:
                    info = await self.get_release_build_information(channel)
                    self.log.info('%s: succeeded', channel)

                    # dispatch build_polled event to let all cogs know
                    self.bot.dispatch('build_polled', info)

                    # track this build (potentially dispatches new_build)
                    await self._tracker.track(info)
                except ReleaseExtractorError:
                    self.log.exception('release extractor threw an error:')
                    break
                except aiohttp.ClientError:
                    self.log.exception('aiohttp threw an error:')
                    break

                # sleep for a bit.
                await asyncio.sleep(self.poll_interval)

        return _poll()

    @command()
    @is_owner()
    async def scrape(self, ctx: Context, channel):
        """Scrapes release build information from a release channel, manually."""
        # TODO: Converter.
        if channel not in [ch.name.lower() for ch in ReleaseChannel]:
            return await ctx.send('Unknown release channel.')

        try:
            release_channel = getattr(ReleaseChannel, channel.upper())
            info = await self.get_release_build_information(release_channel)
            await ctx.send(embed=info.embed)
        except ReleaseExtractorError as ree:  # :^)
            await ctx.send(f'Extractor error! — `{ree}`')

    @command()
    async def health(self, ctx: Context):
        """Shows health of the pollers."""
        text = ''

        skull_emoji = '\N{SKULL AND CROSSBONES}'
        thumbs_up_emoji = '\N{THUMBS UP SIGN}'

        for poller_name, poller_task in self._poller_tasks.items():
            text += f'`{poller_name}`: {skull_emoji if poller_task.cancelled() else thumbs_up_emoji}\n'

        await ctx.send(text)


def setup(bot):
    bot.add_cog(Poller(bot))
