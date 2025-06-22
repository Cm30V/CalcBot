import discord
from discord.ext import commands
import logging

log = logging.getLogger(__name__)

class HelpCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        log.info("HelpCommands cog loaded.")

    @commands.command(name='help', help='Displays a list of all available commands.')
    async def custom_help(self, ctx):
        embed = discord.Embed(
            title="CalcBot Commands",
            description="Here's a list of commands you can use with CalcBot:",
            color=discord.Color.blue()
        )

        # Iterate through all cogs and their commands
        for cog_name, cog in self.bot.cogs.items():
            commands_list = []
            for command in cog.get_commands():
                # Filter out hidden commands if any (e.g., if you add `hidden=True` to a command)
                if not command.hidden:
                    commands_list.append(f"`!{command.name}` - {command.help}")
            
            if commands_list: # Only add field if cog has visible commands
                embed.add_field(
                    name=f"{cog_name} Commands",
                    value="\n".join(commands_list),
                    inline=False
                )
        
        embed.set_footer(text="Use !help <command_name> for more info on a specific command (if available).")
        await ctx.send(embed=embed)
        log.info(f"Help command used by {ctx.author.id}.")

    @custom_help.error
    async def custom_help_error(self, ctx, error):
        if isinstance(error, commands.TooManyArguments):
            await ctx.send("Usage: `!help` or `!help <command_name>`")
        else:
            log.error(f"Error in help command: {error}", exc_info=True)
            await ctx.send("An unexpected error occurred with the help command.")