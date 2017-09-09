import logging

import discord

from releaseracer.bot import ReleaseRacer
from releaseracer.cogs.poller import ReleaseBuildInfo


class Notifier:
    def __init__(self, bot: ReleaseRacer):
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.feeds = bot.cfg.get('feeds', {})

        self.log.info('feeds: %s', self.feeds)

    async def on_new_build(self, release: ReleaseBuildInfo):
        # wait until ready before notifying channels
        await self.bot.wait_until_ready()

        self.log.info('new build! %s', release.release_build)

        for channel_id, channels in self.feeds.items():
            channel = self.bot.get_channel(int(channel_id))

            if not channel:
                self.log.warning('feed channel "%d" not found, ignoring', channel_id)
                continue

            if release.channel.name.lower() not in channels:
                continue

            self.log.info('notifying channel %s of new release (%s, %s)',
                          channel_id, release.release_build, str(release.channel))

            try:
                await channel.send(embed=release.embed)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                self.log.warning('inaccessible feed channel id "%d", ignoring', channel_id)


def setup(bot: ReleaseRacer):
    bot.add_cog(Notifier(bot))
