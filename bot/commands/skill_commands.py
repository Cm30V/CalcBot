import discord
from discord.ext import commands
import logging
import asyncio
import random
import json
import re

import bot.database
from bot import config, groq_api
from ap_units import AP_UNITS_DATA
from bot import quiz_sessions

log = logging.getLogger(__name__)

class QuizCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        log.info("QuizCommands cog loaded.")

    async def _send_question(self, channel, quiz_session: quiz_sessions.QuizSession):
        """Sends a formatted question from the current quiz session."""
        question_data = quiz_session.current_question_data
        if not question_data:
            log.error(f"Attempted to send question for channel {channel.id} but current_question_data is None.")
            await channel.send("An error occurred while fetching the question. Please try starting a new quiz.")
            quiz_session.clear_current_question() 
            quiz_sessions.set_quiz_session(channel.id, quiz_session)
            return

        embed = discord.Embed(
            title=f"Question (ID: {question_data['question_id']})",
            description=question_data['question_text'],
            color=discord.Color.blue()
        )

        options_text = ""
        current_quiz_state = quiz_session

        current_quiz_state.current_options_map = {}
        current_quiz_state.correct_letter = None

        if question_data['options']:
            if not isinstance(question_data['options'], list):
                log.error(f"Options for {question_data['question_id']} is not a list: {question_data['options']}")
                await channel.send("Error: Question options are malformed. Please report this question.")
                return

            clean_options = [opt.strip() for opt in question_data['options'] if opt and opt.strip()]
            clean_options = list(dict.fromkeys(clean_options))

            if question_data['representation_type'] == 'MCQ' and len(clean_options) < 4:
                log.warning(f"MCQ question {question_data['question_id']} has less than 4 unique options after cleaning: {clean_options}")

            shuffled_options = list(clean_options)
            random.shuffle(shuffled_options)

            for i, option in enumerate(shuffled_options):
                letter = chr(65 + i)
                options_text += f"{letter}. {option}\n"
                current_quiz_state.current_options_map[letter.lower()] = option
                if option == question_data['correct_answer']:
                    current_quiz_state.correct_letter = letter

            embed.add_field(name="Options", value=options_text, inline=False)

        embed.add_field(name="Details", value=(
            f"Unit: {question_data['unit_number']} | Skill: {question_data['skill_id']}\n"
            f"Difficulty: {question_data['difficulty']} | Type: {question_data['representation_type']}\n"
            f"Calculator: {'Yes' if question_data['calculator_active'] else 'No'}"
        ), inline=False)

        embed.set_footer(text=f"Type your answer (e.g., {'A, B, C, D' if question_data['representation_type'] == 'MCQ' else 'your answer'}) using `!answer <your_choice>`\nReport a question anytime: `!reportquestion <question_id> <reason>`")

        await channel.send(embed=embed)
        log.info(f"Question {question_data['question_id']} sent to channel {channel.id}.")

        quiz_session.last_activity_time = asyncio.get_event_loop().time()
        quiz_sessions.set_quiz_session(channel.id, quiz_session)

    async def _ask_next_question(self, channel):
        """Asks the next question in the quiz session."""
        session = quiz_sessions.get_quiz_session(channel.id)
        if not session or session.is_complete():
            await self._end_quiz(channel)
            return

        if not session.questions_to_ask:
            question_data = await bot.database.get_random_question(
                unit_number=session.unit_number,
                skill_id=session.skill_id
            )
            if not question_data:
                await channel.send("I ran out of questions! Please try a different unit/skill or add more questions.")
                await self._end_quiz(channel)
                return
            session.questions_to_ask.append(question_data)

        next_question = session.questions_to_ask.pop(0)
        session.current_question_data = next_question
        session.questions_asked_count += 1
        session.questions_history.append(next_question['question_id'])

        await self._send_question(channel, session)
        session.last_activity_time = asyncio.get_event_loop().time()
        quiz_sessions.set_quiz_session(channel.id, session)
        log.info(f"Question {session.current_question_data['question_id']} asked in channel {channel.id}.")

    async def _end_quiz(self, channel, show_final_score: bool = True):
        """Ends the quiz session and provides a summary."""
        session = quiz_sessions.get_quiz_session(channel.id)
        if session and show_final_score:
            await channel.send(
                f"🎉 Quiz complete! You answered {session.correct_answers_count} out of {session.questions_asked_count} questions correctly."
            )
            log.info(f"Quiz ended in channel {channel.id} for user {session.user_id}. Score: {session.correct_answers_count}/{session.questions_asked_count}")
        elif not session:
            log.info(f"Attempted to end quiz in channel {channel.id} but no session found.")
        quiz_sessions.clear_quiz_session(channel.id)


    @commands.command(name="startquiz", help="Starts a quiz with specified number of questions, unit, and skill.")
    async def start_quiz(self, ctx, num_questions: int = config.DEFAULT_QUIZ_QUESTION_COUNT, unit_number: int = config.DEFAULT_QUIZ_UNIT, skill_id: str = config.DEFAULT_QUIZ_SKILL):
        """Starts a quiz."""
        if ctx.channel.id in quiz_sessions.active_quiz_sessions:
            await ctx.send("A quiz is already active in this channel. Please finish or stop the current quiz (!stopquiz) before starting a new one.")
            return

        if unit_number is not None and unit_number not in AP_UNITS_DATA:
            await ctx.send(f"❌ Invalid unit number: {unit_number}. Please choose a unit from {', '.join(map(str, AP_UNITS_DATA.keys()))}.")
            return
        if skill_id is not None and (unit_number is None or skill_id not in AP_UNITS_DATA[unit_number]["skills"]):
            await ctx.send(f"❌ Invalid skill ID: `{skill_id}` for Unit {unit_number}. Use `!listskills` to see available skills.")
            return

        num_questions = min(num_questions, config.MAX_QUIZ_QUESTIONS)
        if num_questions <= 0:
            await ctx.send("Please specify a positive number of questions for the quiz.")
            return

        questions_data = []
        if unit_number is not None and skill_id is not None:
            all_skill_questions = await bot.database.get_questions_by_skill(unit_number, skill_id)
            if not all_skill_questions:
                await ctx.send(f"No questions found for Unit {unit_number}, Skill {skill_id}.")
                return
            random.shuffle(all_skill_questions)
            questions_data = all_skill_questions[:num_questions]
        elif unit_number is not None:
            all_unit_questions = await bot.database.get_questions_by_unit_list([unit_number])
            if not all_unit_questions:
                await ctx.send(f"No questions found for Unit {unit_number}.")
                return
            random.shuffle(all_unit_questions)
            questions_data = all_unit_questions[:num_questions]
        else:
            total_questions_in_db = await bot.database.get_total_question_count()
            if total_questions_in_db == 0:
                await ctx.send("The database is empty! Please populate it with questions using `!populatedb` (Admin only).")
                return

            fetched_count = 0
            max_attempts = num_questions * 5
            while fetched_count < num_questions and max_attempts > 0:
                q = await bot.database.get_random_question()
                if q and q['question_id'] not in [q_data['question_id'] for q_data in questions_data]:
                    questions_data.append(q)
                    fetched_count += 1
                max_attempts -= 1

            if not questions_data:
                await ctx.send("Could not find enough unique random questions. Try being more specific or add more questions.")
                return

        if not questions_data:
            await ctx.send("Failed to retrieve questions for the quiz. Please try again.")
            return

        session = quiz_sessions.QuizSession(
            user_id=ctx.author.id,
            channel_id=ctx.channel.id,
            unit_number=unit_number,
            skill_id=skill_id,
            num_questions=len(questions_data)
        )
        session.questions_to_ask = questions_data
        quiz_sessions.set_quiz_session(ctx.channel.id, session)

        await ctx.send(f"Starting a {len(questions_data)}-question quiz from {f'Unit {unit_number}' if unit_number else 'any unit'}{f', Skill {skill_id}' if skill_id else ''}. Good luck!")
        log.info(f"Starting quiz in channel {ctx.channel.id} for {len(questions_data)} questions.")

        await self._ask_next_question(ctx.channel)
        session.last_activity_time = asyncio.get_event_loop().time()
        quiz_sessions.set_quiz_session(ctx.channel.id, session)

    @commands.command(name="stopquiz", help="Stops the current quiz in the channel.")
    async def stop_quiz(self, ctx):
        """Stops the current quiz."""
        if ctx.channel.id not in quiz_sessions.active_quiz_sessions:
            await ctx.send("There is no active quiz in this channel.")
            return

        await self._end_quiz(ctx.channel, show_final_score=True)
        log.info(f"Quiz in channel {ctx.channel.id} stopped by user {ctx.author.name}.")

    @commands.command(name="answer", help="Submit your answer to the current quiz question.")
    async def answer_command(self, ctx, *, user_answer: str):
        """Submits an answer to the current quiz question."""
        await self._check_answer(ctx.message, user_answer)

    async def _check_answer(self, message, user_answer):
        """Checks the user's answer and provides feedback."""
        channel_id = message.channel.id
        session = quiz_sessions.get_quiz_session(channel_id)

        if not session or not session.current_question_data:
            return

        current_q_data = session.current_question_data

        is_correct = False
        feedback_message = None

        log.debug(f"User {message.author.id} answering question {current_q_data['question_id']} with '{user_answer}'.")

        if current_q_data['representation_type'] == 'MCQ':
            correct_answer_value = current_q_data['correct_answer'].strip().lower()

            if user_answer.strip().lower() in session.current_options_map:
                selected_option_text = session.current_options_map[user_answer.strip().lower()]
                is_correct = (selected_option_text.lower() == correct_answer_value)
                user_answer_for_record = f"Choice {user_answer.strip().upper()}: {selected_option_text}"
            else:
                is_correct = (user_answer.strip().lower() == correct_answer_value)
                user_answer_for_record = user_answer.strip()

        elif current_q_data['representation_type'] == 'FRQ':
            grading_result = await groq_api.grade_frq_answer(
                question=current_q_data['question_text'],
                correct_answer=current_q_data['correct_answer'],
                user_answer=user_answer
            )

            assessment = grading_result.get('assessment', 'Error')
            feedback_message = grading_result.get('feedback', 'Could not get detailed feedback.')

            is_correct = (assessment.lower() == 'correct')
            user_answer_for_record = user_answer.strip()

        # Record the answer in the database
        await bot.database.record_answer(
            message.author.id,
            current_q_data['question_id'],
            is_correct,
            user_answer_for_record
        )

        if is_correct:
            session.correct_answers_count += 1
            await message.channel.send(f"✅ Correct! Well done, {message.author.mention}!")
        else:
            correct_answer_display = current_q_data['correct_answer']
            if current_q_data['representation_type'] == 'MCQ' and session.correct_letter:
                correct_answer_display = f"{session.correct_letter}. {session.current_options_map.get(session.correct_letter.lower(), correct_answer_display)}"

            await message.channel.send(
                f"❌ Incorrect, {message.author.mention}. The correct answer was: ||{correct_answer_display}||.\n"
                f"**Explanation:** {current_q_data['explanation']}"
            )

        if current_q_data['representation_type'] == 'FRQ' and feedback_message:
            await message.channel.send(f"**AI Feedback:** {feedback_message}")

        log.info(f"User {message.author.id} answered question {current_q_data['question_id']}. Correct: {is_correct}. "
                 f"Asked: {session.questions_asked_count}/{session.num_questions}. "
                 f"Correct count: {session.correct_answers_count}")

        quiz_sessions.set_quiz_session(channel_id, session)

        if session.is_complete():
            await asyncio.sleep(1)
            await self._end_quiz(message.channel)
        else:
            await asyncio.sleep(1)
            await self._ask_next_question(message.channel)

    @commands.command(name="reportquestion", help="Reports a question for review.")
    async def report_question_command(self, ctx, question_id: str, *, reason: str):
        """Reports a question for review by administrators."""
        if not re.match(r"^\d+-\d+\.\d+-\d+$", question_id):
            await ctx.send("❌ Invalid question ID format. Please use the format `Unit-Skill.Subskill-QuestionNumber` (e.g., `1-1.3-602512`).")
            log.warning(f"User {ctx.author.name} provided invalid question ID format for reporting: {question_id}.")
            return

        report_success = await bot.database.report_question(question_id, ctx.author.id, reason)

        if report_success:
            await ctx.send(f"✅ Question `{question_id}` has been reported for review. Thank you for your feedback!")
            log.info(f"User {ctx.author.name} reported question {question_id} with reason: {reason}.")
        else:
            await ctx.send(f"❌ Failed to report question `{question_id}`. Please check the question ID or try again later.")
            log.error(f"User {ctx.author.name} failed to report question {question_id}.")

async def setup(bot):
    await bot.add_cog(QuizCommands(bot))