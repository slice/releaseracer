from .cog import Poller


def setup(bot):
    bot.add_cog(Poller(bot))
