import discord
from discord.ext import commands
import logging
import random
import json

import bot.database
from bot import groq_api
from ap_units import AP_UNITS_DATA

log = logging.getLogger(__name__)

class AdminCommands(commands.Cog):
    """
    A cog containing administrative commands for managing the bot's database and content.
    These commands are restricted to users with administrator permissions in the Discord guild.
    """
    def __init__(self, bot):
        self.bot = bot
        log.info("AdminCommands cog loaded.")

    async def cog_check(self, ctx):
        """
        A check that ensures only users with administrator permissions can use commands
        within this cog.
        """
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You do not have administrative permissions to use this command.")
            log.warning(f"Unauthorized admin command attempt by {ctx.author.id} ({ctx.author.name}) in guild {ctx.guild.id}: {ctx.command.name}.")
            return False
        return True

    @commands.command(name="populatedb", help="Populates the database with AP Calculus BC questions for a specified unit. (Admin only)")
    async def populate_db(self, ctx, unit_number: int, num_questions: int):
        """
        Generates and adds a specified number of AP Calculus BC questions for a given unit
        to the bot's database using the Groq API.
        Example: !populatedb 1 5 (generates 5 questions for Unit 1)
        """
        if groq_api.client is None:
            try:
                groq_api.initialize_groq_client()
            except Exception as e:
                await ctx.send(f"❌ Groq client not initialized. Cannot generate questions. Error: {e}")
                log.error(f"Failed to initialize Groq client for populate_db: {e}", exc_info=True)
                return

        if unit_number not in AP_UNITS_DATA:
            await ctx.send(f"❌ Invalid unit number: {unit_number}. Please choose from {list(AP_UNITS_DATA.keys())}.")
            return

        if num_questions <= 0:
            await ctx.send("❌ Number of questions must be positive.")
            return

        await ctx.send(f"⏳ Generating {num_questions} questions for Unit {unit_number}. This may take a while...")
        log.info(f"Admin {ctx.author.name} initiated database population for Unit {unit_number} (x{num_questions}).")

        skills_in_unit = list(AP_UNITS_DATA[unit_number]['skills'].keys())
        if not skills_in_unit:
            await ctx.send(f"❌ No skills defined for Unit {unit_number}.")
            log.error(f"No skills found for Unit {unit_number} during populate_db.")
            return

        successful_generations = 0
        for i in range(num_questions):
            skill_id = random.choice(skills_in_unit)
            question_type = random.choice(["MCQ", "FRQ"])
            difficulty = random.choice(["Easy", "Medium", "Hard"])
            calculator_active = random.choice([True, False])

            try:
                question_data = await groq_api.generate_question_json(
                    unit_number=unit_number,
                    skill_id=skill_id,
                    question_type=question_type,
                    difficulty=difficulty,
                    calculator_active=calculator_active
                )
                if question_data and await bot.database.add_question(question_data):
                    successful_generations += 1
                    await ctx.send(f"✅ Generated and added question {i+1}/{num_questions} for skill `{skill_id}`.")
                else:
                    await ctx.send(f"⚠️ Failed to add question {i+1}/{num_questions} (possibly a duplicate or generation error).")
            except Exception as e:
                log.error(f"Error generating/adding question {i+1}/{num_questions}: {e}", exc_info=True)
                await ctx.send(f"❌ An error occurred generating question {i+1}/{num_questions}. Check logs for details.")
                
        await ctx.send(f"🎉 Database population complete for Unit {unit_number}! Successfully added {successful_generations} questions.")
        log.info(f"Database population for Unit {unit_number} completed. Added {successful_generations} questions.")

    @commands.command(name="viewreports", help="Views all active question reports. (Admin only)")
    async def view_reports_command(self, ctx):
        """
        Displays a list of all active question reports submitted by users.
        Reports are grouped by question ID for clarity.
        Example: !viewreports
        """
        reports = await bot.database.get_active_reports()

        if not reports:
            await ctx.send("✅ No active question reports at this time.")
            log.info(f"Admin {ctx.author.name} viewed active reports - none found.")
            return

        embed = discord.Embed(
            title="Active Question Reports",
            description=f"Found {len(reports)} active report(s).",
            color=discord.Color.red()
        )

        # Group reports by question_id for better readability in the embed.
        reports_by_question = {}
        for report in reports:
            q_id = report['question_id']
            if q_id not in reports_by_question:
                reports_by_question[q_id] = []
            reports_by_question[q_id].append(report)
        
        for q_id, q_reports in reports_by_question.items():
            report_details = []
            for r in q_reports:
                user = self.bot.get_user(r['user_id'])
                username = user.name if user else f"User ID: {r['user_id']}"
                report_details.append(f"• By {username} on {r['report_date']}: {r['reason']}")
            
            value = "\n".join(report_details)
            # Truncate if too long for a single embed field.
            if len(value) > 1024:
                value = value[:1020] + "..."
            
            embed.add_field(
                name=f"Reported Question: `{q_id}` ({len(q_reports)} reports)",
                value=value,
                inline=False
            )

        embed.set_footer(text="Use !clearreport <Question ID> to clear a report. Use !disablequestion <Question ID> to disable a question.")
        await ctx.send(embed=embed)
        log.info(f"Admin {ctx.author.name} viewed active reports.")

    @commands.command(name="clearreport", help="Clears reports for a specific question ID. (Admin only)")
    async def clear_report_command(self, ctx, question_id: str):
        """
        Clears all active reports associated with a given question ID.
        This command does not disable the question itself.
        Example: !clearreport Q123456789
        """
        clear_success = await bot.database.clear_report(question_id)

        if clear_success:
            await ctx.send(f"✅ Reports for question `{question_id}` have been cleared.")
            log.info(f"Admin {ctx.author.name} cleared reports for question {question_id}.")
        else:
            await ctx.send(f"⚠️ No active reports found to clear for question `{question_id}`.")
            log.info(f"Admin {ctx.author.name} tried to clear reports for {question_id}, but none were found.")

    @commands.command(name="disablequestion", help="Disables or enables a question by ID, preventing it from appearing in quizzes. (Admin only)")
    async def disable_question_command(self, ctx, question_id: str, disable: bool = True):
        """
        Sets the active status of a question in the database. Disabled questions
        will not be selected for quizzes.
        Example: !disablequestion Q123456789 true (disables)
        Example: !disablequestion Q123456789 false (enables)
        """
        question_exists = await bot.database.get_question(question_id)
        if not question_exists:
            await ctx.send(f"❌ Question `{question_id}` not found in the database.")
            return

        success = await bot.database.disable_question(question_id, disable)

        action = "disabled" if disable else "enabled"
        if success:
            await ctx.send(f"✅ Question `{question_id}` has been successfully {action}.")
            log.info(f"Admin {ctx.author.name} {action} question {question_id}.")
        else:
            await ctx.send(f"❌ An error occurred while trying to {action} question `{question_id}`.")
            log.error(f"Admin {ctx.author.name} failed to {action} question {question_id}.")
            
    @commands.command(name="deleteall", help="Deletes ALL questions from the database instantly. (Admin only)", hidden=True)
    async def delete_all_command(self, ctx):
        """
        Deletes all questions from the database without requiring confirmation.
        This command is hidden from the public help list due to its destructive nature.
        Example: !deleteall
        """
        await ctx.send("🔥 **Executing !deleteall:** Deleting all questions from the database now...")
        log.warning(f"Admin {ctx.author.name} executed !deleteall command in {ctx.guild.name} ({ctx.channel.name}). No confirmation required.")

        success = await bot.database.delete_all_questions()

        if success:
            await ctx.send("✅ All questions have been successfully deleted from the database.")
            log.info(f"Admin {ctx.author.name} successfully deleted all questions from the database.")
        else:
            await ctx.send("❌ An error occurred while trying to delete all questions.")
            log.error(f"Admin {ctx.author.name} failed to delete all questions.")

async def setup(bot):
    """Adds the AdminCommands cog to the bot."""
    await bot.add_cog(AdminCommands(bot))