import discord
from discord.ext import commands, tasks
import logging
import os
from dotenv import load_dotenv
import asyncio

# Load environment variables from .env file
load_dotenv()

# Set up logging for the bot
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Import bot modules
from bot import config
from bot import database
from bot import groq_api
from bot import quiz_sessions
from ap_units import AP_UNITS_DATA

# Import cogs (command extensions)
from bot.commands.admin_commands import AdminCommands
from bot.commands.quiz_commands import QuizCommands
from bot.commands.info_commands import InfoCommands

# --- Custom Help Command Class ---
class CustomHelpCommand(commands.DefaultHelpCommand):
    """
    Custom implementation of the default help command to provide richer, embed-based help messages.
    """
    async def send_bot_help(self, mapping):
        """Sends an embed listing all available commands and their categories."""
        embed = discord.Embed(
            title="CalcBot Commands",
            description="Here's a list of commands you can use with CalcBot:",
            color=discord.Color.blue()
        )

        # Add a field for the help commands themselves
        help_commands_text = (
            f"`{self.context.clean_prefix}help` - Displays this message.\n"
            f"`{self.context.clean_prefix}help <command_name>` - Get details about a specific command."
        )
        embed.add_field(name="Help Commands", value=help_commands_text, inline=False)

        # Iterate over cogs to add fields for their commands
        for cog, commands_list in mapping.items():
            if cog is None:
                continue # Skip commands not belonging to a cog (like the default help command)

            # Filter and sort commands visible to the user
            filtered_commands = await self.filter_commands(commands_list, sort=True)
            if not filtered_commands:
                continue # Skip if no visible commands in this cog

            cog_name = getattr(cog, "qualified_name", "No Category")
            commands_text = ""
            for command in filtered_commands:
                # Use command.brief for a short description, fallback to the first line of command.help
                command_description = command.brief or (command.help.split('\n')[0] if command.help else 'No description provided.')
                commands_text += f"`{self.context.clean_prefix}{command.qualified_name}` - {command_description}\n"

            if commands_text:
                embed.add_field(name=f"{cog_name} Commands", value=commands_text.strip(), inline=False)
        
        embed.set_footer(text=self.get_ending_note())
        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command):
        """Sends an embed with detailed help for a specific command."""
        embed = discord.Embed(
            title=f"{self.context.clean_prefix}{command.qualified_name} {command.signature}",
            description=command.help or "No description provided.",
            color=discord.Color.green()
        )
        if command.aliases:
            embed.add_field(name="Aliases", value=", ".join(f"`{self.context.clean_prefix}{a}`" for a in command.aliases), inline=False)
        embed.set_footer(text=self.get_ending_note())
        await self.get_destination().send(embed=embed)

    async def send_group_help(self, group):
        """Sends an embed with detailed help for a command group, including its subcommands."""
        embed = discord.Embed(
            title=f"{self.context.clean_prefix}{group.qualified_name} {group.signature}",
            description=group.help or "No description provided for this group.",
            color=discord.Color.orange()
        )
        if group.aliases:
            embed.add_field(name="Aliases", value=", ".join(f"`{self.context.clean_prefix}{a}`" for a in group.aliases), inline=False)
        
        commands_text = ""
        commands_list = await self.filter_commands(group.commands, sort=True)
        if commands_list:
            for command in commands_list:
                command_description = command.brief or (command.help.split('\n')[0] if command.help else 'No description.')
                commands_text += f"`{self.context.clean_prefix}{command.qualified_name}` - {command_description}\n"
            embed.add_field(name="Subcommands:", value=commands_text.strip(), inline=False)
            
        embed.set_footer(text=self.get_ending_note())
        await self.get_destination().send(embed=embed)


# --- Bot Setup ---
# Define Discord bot intents, crucial for specifying what events your bot needs to listen to.
intents = discord.Intents.default()
intents.message_content = True # Required to read message content from guilds
intents.reactions = True       # Required to read reactions for features like quiz interactions

# Initialize the bot with its command prefix and the custom help command
bot = commands.Bot(command_prefix=config.BOT_PREFIX, intents=intents, help_command=CustomHelpCommand())

@bot.event
async def on_ready():
    """Event that fires when the bot has successfully connected to Discord."""
    log.info(f"Logged in as {bot.user} ({bot.user.id})")
    print(f"Logged in as {bot.user} ({bot.user.id})") # For immediate console visibility
    print('------')

    # Attach common modules to the bot instance for easy access within cogs.
    # This is a recommended pattern for passing shared resources to cogs.
    bot.database = database
    bot.groq_api = groq_api
    bot.config = config
    bot.ap_units_data = AP_UNITS_DATA # Make AP_UNITS_DATA accessible via bot instance

    # Initialize Groq API client
    try:
        groq_api.initialize_groq_client()
        log.info("Groq client initialized successfully.")
    except Exception as e:
        log.critical(f"Failed to initialize Groq client: {e}", exc_info=True)
        log.critical("Groq client failed to initialize. Shutting down bot.")
        await bot.close() # Shut down if a critical dependency fails
        return # Prevent further execution

    # Initialize the database connection and schema
    try:
        await database.initialize_db()
        log.info("Database initialized successfully.")
        # await database.populate_units_table() # Uncomment if unit data needs to be populated on startup
    except Exception as e:
        log.critical(f"Failed to initialize database: {e}", exc_info=True)
        log.critical("Database failed to initialize. Shutting down bot.")
        await bot.close() # Shut down if a critical dependency fails
        return # Prevent further execution

    # Load cogs (command extensions) into the bot
    cogs_to_load = [
        AdminCommands,
        QuizCommands,
        InfoCommands,
    ]

    for cog_class in cogs_to_load:
        try:
            await bot.add_cog(cog_class(bot))
            log.info(f"{cog_class.__name__} cog loaded.")
        except Exception as e:
            log.error(f"Failed to load {cog_class.__name__} cog: {e}", exc_info=True)

    # Start the background task for cleaning up timed-out quiz sessions
    if not cleanup_quiz_sessions.is_running():
        cleanup_quiz_sessions.start()
        log.info("Started cleanup_quiz_sessions background task.")

    log.info("Bot is fully ready and operational!")

@tasks.loop(minutes=config.QUIZ_TIMEOUT_CHECK_INTERVAL_MINUTES)
async def cleanup_quiz_sessions():
    """Background task to periodically clean up quiz sessions that have timed out due to inactivity."""
    timeout_seconds = bot.config.QUIZ_SESSION_TIMEOUT_SECONDS
    timed_out_sessions = quiz_sessions.get_timed_out_quiz_sessions(timeout_seconds)

    for channel_id, session in timed_out_sessions:
        log.info(f"Quiz session in channel {channel_id} (user {session.user_id}) timed out due to inactivity.")
        channel = bot.get_channel(channel_id)
        if channel:
            try:
                # Notify the user in the channel that their quiz has timed out
                await channel.send(
                    f"Your quiz in this channel has timed out due to inactivity. "
                    f"You answered {session.correct_answers_count} out of {session.questions_asked_count} questions correctly."
                )
            except discord.Forbidden:
                log.warning(f"Could not send timeout message to channel {channel_id} (Forbidden permissions).")
            except Exception as e:
                log.error(f"Error sending timeout message to channel {channel_id}: {e}", exc_info=True)
        
        # Clear the session from active memory
        quiz_sessions.clear_quiz_session(channel_id)

@cleanup_quiz_sessions.before_loop
async def before_cleanup_quiz_sessions():
    """Waits for the bot to be ready before starting the quiz cleanup loop."""
    await bot.wait_until_ready()
    log.info("Cleanup quiz sessions loop waiting for bot to be ready...")

@bot.event
async def on_disconnect():
    """Event that fires when the bot disconnects from Discord."""
    log.warning("Bot disconnected from Discord.")
    # Attempt to close the database connection cleanly on disconnect
    try:
        await database.close_db_connection() 
        log.info("Database connection closed on disconnect.")
    except Exception as e:
        log.error(f"Error closing database on disconnect: {e}", exc_info=True)

@bot.event
async def on_command_error(ctx, error):
    """
    Global error handler for commands. This catches exceptions raised by commands
    and provides user-friendly feedback.
    """
    if isinstance(error, commands.CommandNotFound):
        # Silently ignore command not found errors, as it's common for users to mistype
        log.debug(f"Command not found: {ctx.message.content}")
        return
    
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"You're missing a required argument. Usage: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`")
        log.warning(f"Missing argument in {ctx.command.qualified_name} by {ctx.author}: {error}")
    
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"Invalid argument provided: {error}. Please check the command usage.")
        log.warning(f"Bad argument in {ctx.command.qualified_name} by {ctx.author}: {error}")
    
    elif isinstance(error, commands.NotOwner):
        await ctx.send("You don't have permission to use this command.")
        log.warning(f"Unauthorized access attempt by {ctx.author.id} to {ctx.command.qualified_name}")
    
    elif isinstance(error, commands.CheckFailure):
        # Handles general check failures (e.g., custom decorators, role checks)
        await ctx.send(f"You don't have permission to use this command here or now.")
        log.warning(f"Check failed for {ctx.author.id} on {ctx.command.qualified_name}: {error}")
    
    elif isinstance(error, commands.CommandInvokeError):
        # This wraps exceptions raised inside your command logic.
        original_error = error.original
        log.error(f"Error in command '{ctx.command.qualified_name}' by {ctx.author.id}: {original_error}", exc_info=True)
        # Send a user-friendly error message, but log the full traceback for debugging
        await ctx.send(f"An internal error occurred while executing this command. Please try again later. "
                       f"Error: `{original_error}`")
    
    else:
        # Catch any other unexpected errors not specifically handled
        log.error(f"An unhandled error occurred: {error}", exc_info=True)
        await ctx.send(f"An unexpected error occurred: `{error}`")

# --- Main Execution ---
def run_bot():
    """Retrieves the bot token and starts the Discord bot."""
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        log.critical("DISCORD_BOT_TOKEN not found in environment variables. Please set it.")
        return

    try:
        # Use asyncio.run() to manage the event loop for the bot's blocking start method.
        asyncio.run(bot.start(token))
    except KeyboardInterrupt:
        log.info("Bot manually stopped via KeyboardInterrupt.")
    except Exception as e:
        log.critical(f"Bot failed to run: {e}", exc_info=True)
    finally:
        # Ensure database is closed cleanly even if bot.start() crashes or is interrupted.
        log.info("Ensuring database connection is closed during final shutdown.")
        asyncio.run(database.close_db_connection())

if __name__ == "__main__":
    run_bot()