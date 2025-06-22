import discord
from discord.ext import commands
import logging

from ap_units import AP_UNITS_DATA 
import bot.database

log = logging.getLogger(__name__)

class InfoCommands(commands.Cog):
    """
    A cog containing informational commands for users, such as listing AP skills
    and retrieving question details.
    """
    def __init__(self, bot):
        self.bot = bot
        log.info("InfoCommands cog loaded.")

    @commands.command(name='listskills', aliases=['skills', 'allskills'], 
                      help='Lists all AP Units and their associated Skill IDs.')
    async def list_skills(self, ctx):
        """
        Displays a comprehensive list of all AP Calculus BC Units and their
        corresponding Skill IDs and descriptions.
        """
        log.info(f"User {ctx.author.id} ({ctx.author.name}) requested skill list.")

        embed = discord.Embed(
            title="AP Calculus BC Units & Skills",
            description="Here's a breakdown of the AP Calculus BC curriculum by Unit and Skill ID.",
            color=discord.Color.gold()
        )

        for unit_number, unit_data in AP_UNITS_DATA.items():
            unit_name = unit_data.get("name", f"Unit {unit_number}")
            skills = unit_data.get("skills", {})
            
            if skills:
                skill_list = [f"`{skill_id}` - {skill_name}" for skill_id, skill_name in skills.items()]
                
                current_skills_text = "\n".join(skill_list)
                # Splits skills into multiple embed fields if the text exceeds Discord's limit.
                if len(current_skills_text) > 1024:
                    chunks = [current_skills_text[i:i+1024] for i in range(0, len(current_skills_text), 1024)]
                    for i, chunk in enumerate(chunks):
                        field_name = f"{unit_name} Skills (Part {i+1})"
                        embed.add_field(name=field_name, value=chunk, inline=False)
                else:
                    embed.add_field(
                        name=f"{unit_name} Skills",
                        value=current_skills_text,
                        inline=False
                    )
            else:
                embed.add_field(
                    name=f"{unit_name} Skills",
                    value="No skills defined for this unit.",
                    inline=False
                )
        
        await ctx.send(embed=embed)

    @commands.command(name='getquestion', aliases=['q'], help='Retrieves a specific question by its ID.')
    async def get_question_command(self, ctx, question_id: str):
        """
        Fetches and displays the details of a specific question from the database
        using its unique ID.
        Example: !getquestion 1-1.1A-abcdef1234567890
        """
        log.info(f"User {ctx.author.id} ({ctx.author.name}) requested question {question_id}.")
        question_data = await bot.database.get_question(question_id.strip())

        if not question_data:
            await ctx.send(f"❌ Question with ID `{question_id}` not found.")
            return

        embed = discord.Embed(
            title=f"Question (ID: {question_data['question_id']})",
            description=question_data['question_text'],
            color=discord.Color.green()
        )
        embed.add_field(name="Details", value=(
            f"**Unit:** {question_data['unit_number']}\n"
            f"**Skill:** {question_data['skill_id']}\n"
            f"**Type:** {question_data['representation_type']}\n"
            f"**Difficulty:** {question_data['difficulty']}\n"
            f"**Calculator Active:** {'Yes' if question_data['calculator_active'] else 'No'}\n"
            f"**Disabled:** {'Yes' if question_data['is_disabled'] else 'No'}"
        ), inline=False)

        if question_data['options']:
            options_text = "\n".join([f"{chr(65 + i)}. {option}" for i, option in enumerate(question_data['options'])])
            embed.add_field(name="Options", value=options_text, inline=False)
        
        # Shows answer and explanation only to administrators.
        if ctx.author.guild_permissions.administrator:
            embed.add_field(name="Correct Answer", value=f"||{question_data['correct_answer']}||", inline=False)
            embed.add_field(name="Explanation", value=question_data['explanation'], inline=False)
        else:
            embed.set_footer(text="Answer and explanation are for admin view only.")

        await ctx.send(embed=embed)

    @commands.command(name='reportquestion', aliases=['report'], 
                      help='Report a question for review. Usage: !reportquestion <question_id> <reason>')
    async def report_question_command(self, ctx, question_id: str, *, reason: str = None):
        """
        Allows users to report a question they believe is incorrect, unclear, or problematic
        for review by administrators.
        Example: !reportquestion 1-1.1A-abcdef1234567890 The answer seems incorrect.
        """
        if not reason:
            await ctx.send("❌ Please provide a reason for reporting this question.\n"
                           "Usage: `!reportquestion <question_id> <reason>`\n"
                           "Example: `!reportquestion Q123456789 The answer seems incorrect`")
            return

        question_data = await bot.database.get_question(question_id.strip())
        if not question_data:
            await ctx.send(f"❌ Question with ID `{question_id}` not found in the database.")
            return

        await bot.database.add_user(ctx.author.id, ctx.author.name)

        success = await bot.database.report_question(
            question_id=question_id.strip(),
            user_id=ctx.author.id,
            reason=reason.strip()
        )

        if success:
            await ctx.send(f"✅ Question `{question_id}` has been reported for review. "
                           "Thank you for helping improve the question bank!")
            log.info(f"User {ctx.author.id} ({ctx.author.name}) reported question {question_id} with reason: {reason}")
        else:
            await ctx.send(f"❌ Failed to report question `{question_id}`. Please try again later.")
            log.error(f"Failed to report question {question_id} by user {ctx.author.id}")

    @commands.command(name='questionoverview', aliases=['qlist', 'recentq'], help='Displays an overview of recently added questions. (Admin only)')
    async def question_overview_command(self, ctx, limit: int = 10, unit_number: int = None, skill_id: str = None):
        """
        Provides administrators with a paginated overview of recently added questions,
        with options to filter by limit, unit number, and skill ID.
        Examples:
        !questionoverview (shows 10 most recent)
        !questionoverview 20 (shows 20 most recent)
        !questionoverview 10 1 (shows 10 most recent from Unit 1)
        !questionoverview 5 1 1.1A (shows 5 most recent from Unit 1, Skill 1.1A)
        """
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You do not have administrative permissions to use this command.")
            log.warning(f"Unauthorized `questionoverview` attempt by {ctx.author.id} ({ctx.author.name}) in guild {ctx.guild.id}.")
            return
        
        log.info(f"User {ctx.author.id} ({ctx.author.name}) requested question overview for Unit: {unit_number}, Skill: {skill_id}.")

        questions = await bot.database.get_recent_questions_overview(limit=limit, unit_number=unit_number, skill_id=skill_id)
        total_questions_count = await bot.database.get_total_question_count()

        if not questions:
            await ctx.send(f"No questions found matching the criteria (Limit: {limit}, Unit: {unit_number if unit_number else 'Any'}, Skill: {skill_id if skill_id else 'Any'}).")
            return
        
        title_suffix = ""
        if unit_number:
            title_suffix += f" (Unit {unit_number}"
            if skill_id:
                title_suffix += f", Skill {skill_id}"
            title_suffix += ")"
        elif skill_id:
            title_suffix += f" (Skill {skill_id})"
        
        embed = discord.Embed(
            title=f"Question Bank Overview{title_suffix}",
            description=f"Showing the latest {len(questions)} questions matching your criteria:",
            color=discord.Color.blue()
        )

        questions_text = ""
        for i, q in enumerate(questions):
            entry = f"{i+1}. `{q['question_id']}` (U{q['unit_number']}/S{q['skill_id']}): {q['question_text_snippet']}\n"
            
            # Ensures embed field value does not exceed Discord's limit.
            if len(questions_text) + len(entry) > 1024:
                embed.add_field(name="Questions (cont.)", value=questions_text, inline=False)
                questions_text = entry
            else:
                questions_text += entry
        
        if questions_text:
            embed.add_field(name="Questions", value=questions_text, inline=False)
        
        embed.set_footer(text=f"Use !getquestion <ID> for full details. Total questions in DB: {total_questions_count}.")
        await ctx.send(embed=embed)


async def setup(bot):
    """Adds the InfoCommands cog to the bot."""
    await bot.add_cog(InfoCommands(bot))