import asyncio
import logging

import aiohttp
from discord.ext.commands import command, is_owner, Context, group

from releaseracer.bot import ReleaseRacer
from releaseracer.formatting import get_traceback
from .types import ReleaseTracker, ReleaseChannel, ReleaseBuildInfo, ReleaseHashes
from .errors import ReleaseExtractorError
from .constants import SCRIPT_TAG_REGEX, RELEASE_BUILD_REGEX


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

        #: The `dict` containing poller tasks for this Poller cog instance.
        self._poller_tasks = {}

    async def on_ready(self):
        """Create pollers upon ready."""
        self.reboot()

    def __unload(self):
        """Called when this extension gets unloaded."""
        self.session.close()
        self._stop_pollers()

    def _stop_pollers(self):
        """Stops all pollers."""
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

    @staticmethod
    def get_login_page(channel: ReleaseChannel) -> str:
        """Returns the login page URL for a channel."""
        base = 'https://{channel_name}discordapp.com/login'

        if channel is ReleaseChannel.STABLE:
            return base.format(channel_name='')
        else:
            return base.format(channel_name=channel.name.lower() + '.')

    @staticmethod
    def get_asset_url(channel: ReleaseChannel, asset_hash: str) -> str:
        """Returns the asset URL for a JS hash."""
        base = 'https://{channel_name}discordapp.com/assets/{hash}.js'

        if channel is ReleaseChannel.STABLE:
            return base.format(channel_name='', hash=asset_hash)
        else:
            return base.format(channel_name=channel.name.lower() + '.', hash=asset_hash)

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
            release_hashes = ReleaseHashes(vendor=hashes[0], main=hashes[1])

            # fetch main js file
            async with self.session.get(self.get_asset_url(channel, release_hashes.main), timeout=10) as resp:
                # read js
                main = await resp.text()

                # get byte size
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
                except asyncio.TimeoutError:
                    # retry upon timeout error
                    self.log.warning('timed out, retrying.')
                    continue
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
    @is_owner()
    async def revive(self, ctx: Context):
        """Kills (if not already dead) then revives the pollers."""
        self.reboot()
        await ctx.send('\N{OK HAND SIGN}')

    @group(invoke_without_command=True)
    async def health(self, ctx: Context):
        """Shows health of the pollers."""
        text = ''

        skull_emoji = '\N{SKULL AND CROSSBONES}'
        thumbs_up_emoji = '\N{THUMBS UP SIGN}'

        for name, task in self._poller_tasks.items():
            text += f'`{name}`: {skull_emoji if task.done() else thumbs_up_emoji}\n'

        await ctx.send(text)

    @health.command()
    async def error(self, ctx: Context, poller):
        """Shows the error of a poller."""
        task = self._poller_tasks.get(poller, None)

        if not task:
            return await ctx.send('Poller not found.')

        try:
            exception = task.exception()
        except asyncio.InvalidStateError:
            return await ctx.send('That poller is fine.')

        await ctx.send('```py\n{}\n```'.format(get_traceback(exception)))

    @health.command()
    async def errors(self, ctx: Context):
        """Shows the errors of the pollers."""
        text = ''

        for name, task in self._poller_tasks.items():
            try:
                text += f'`{name}`: `{task.exception()}`\n'
            except asyncio.InvalidStateError:
                text += f'`{name}`: \N{THUMBS UP SIGN}\n'

        await ctx.send(text or 'All good! \N{THUMBS UP SIGN}')
