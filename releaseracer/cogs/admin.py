import logging

import discord
from discord import Embed, Color
from discord.ext.commands import command, is_owner, Context, Paginator

from releaseracer.bot import ReleaseRacer


class Admin:
    def __init__(self, bot: ReleaseRacer):
        self.bot = bot
        self.log = logging.getLogger(__name__)

    @command(hidden=True)
    @is_owner()
    async def die(self, ctx: Context):
        """Makes me shut down."""
        self.log.info('%s made me shut down', ctx.author)
        await ctx.bot.logout()

    @command()
    async def about(self, ctx: Context):
        """Views some info about me."""

        def format_description(description: str) -> str:
            return description.replace('A bot', "Hey there! I'm a bot")

        embed = Embed(title='Heyo!', description=format_description(self.bot.description), color=Color.blurple())
        embed.set_thumbnail(url=self.bot.user.avatar_url)

        owner: discord.User = (await ctx.bot.application_info()).owner
        embed.add_field(name='Owner', value=f'{owner} (`{owner.id}`)')

        await ctx.send(embed=embed)

    @command(hidden=True)
    @is_owner()
    async def reload(self, ctx: Context):
        """Reloads all cogs."""

        # make a copy of the extension list, because we will be iterating over it and modifying it due to the
        # load and unload calls
        extensions = self.bot.extensions.copy()

        log = Paginator()

        # unload and load everything
        for extension_name, _module in extensions.items():
            try:
                self.log.info('reloading "%s"', extension_name)
                self.bot.unload_extension(extension_name)
                self.bot.load_extension(extension_name)
            except Exception:
                self.log.exception('failed extension load (%s):', extension_name)
                log.add_line(f'\N{CROSS MARK} Failed to reload extension `{extension_name}`.')

        if not log.pages:
            await ctx.send('\N{OK HAND SIGN}')
        else:
            for page in log.pages:
                await ctx.send(page)


def setup(bot: ReleaseRacer):
    bot.add_cog(Admin(bot))
