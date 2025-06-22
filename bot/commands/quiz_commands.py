import discord
from discord.ext import commands
import logging
import asyncio
import random
import json
import time

import bot.database
from bot import config
from ap_units import AP_UNITS_DATA
from bot import quiz_sessions
from bot import groq_api

log = logging.getLogger(__name__)

def chunk_text(text, max_len=1024):
    """Breaks a long string into a list of strings, each no longer than max_len."""
    if len(text) <= max_len:
        return [text]
    
    chunks = []
    current_chunk = ""
    words = text.split(' ')

    for word in words:
        if len(current_chunk) + len(word) + 1 <= max_len:
            current_chunk += (word + ' ')
        else:
            chunks.append(current_chunk.strip())
            current_chunk = (word + ' ')
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    return chunks

class QuizCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        log.info("QuizCommands cog loaded.")

    async def _send_question(self, channel, quiz_session: quiz_sessions.QuizSession):
        """Sends a formatted question from the current quiz session to the specified channel."""
        question_data = quiz_session.current_question_data
        if not question_data:
            log.error(f"Failed to send question for channel {channel.id}: no current_question_data.")
            await channel.send("An internal error occurred. The quiz has been stopped.")
            quiz_sessions.clear_quiz_session(channel.id)
            return

        embed = discord.Embed(
            title=f"Question (ID: {question_data['question_id']})",
            description=question_data['question_text'],
            color=discord.Color.blue()
        )

        options_text = ""
        options_map = quiz_session.current_options_map

        if question_data.get('options'):
            if options_map:
                for letter, option_text in options_map.items():
                    options_text += f"**{letter.upper()}**. {option_text}\n"
                embed.add_field(name="Options", value=options_text, inline=False)
                embed.set_footer(text=f"Type your answer (e.g., A, B, C, D) using `!answer <your_choice>`\n"
                                       f"Report a question anytime: `!reportquestion <question_id> <reason>`")
            else:
                embed.add_field(name="Options", value="Error loading options.", inline=False)
                embed.set_footer(text=f"Type your answer using `!answer <your_answer>`\n"
                                       f"Report a question anytime: `!reportquestion <question_id> <reason>`")
        else:
            embed.set_footer(text=f"Type your answer using `!answer <your_answer>`\n"
                                   f"Report a question anytime: `!reportquestion <question_id> <reason>`")

        embed.add_field(name="Details", value=(
            f"Unit: {question_data['unit_number']} | Skill: `{question_data['skill_id']}`\n"
            f"Difficulty: {question_data['difficulty']} | Type: {question_data['representation_type']}\n"
            f"Calculator: {'Yes' if question_data['calculator_active'] else 'No'}"
        ), inline=False)

        quiz_sessions.set_quiz_session(channel.id, quiz_session)

        await channel.send(embed=embed)
        log.info(f"Question {question_data['question_id']} sent to channel {channel.id}.")

    async def _ask_next_question(self, channel):
        """Fetches, sets, and sends the next question in the quiz session."""
        session = quiz_sessions.get_quiz_session(channel.id)
        if not session:
            log.warning(f"No active quiz session for channel {channel.id} when asking next question.")
            return

        if session.is_complete():
            await self._end_quiz(channel)
            return

        try:
            current_question_index = session.questions_asked_count
            if current_question_index >= len(session.all_quiz_questions):
                log.warning(f"No more questions in quiz list for channel {channel.id}. Ending quiz.")
                await self._end_quiz(channel)
                return

            question_data = session.all_quiz_questions[current_question_index]

            options_map = None
            correct_letter = None
            
            raw_options = question_data.get('options')
            if raw_options and isinstance(raw_options, list):
                options = raw_options
                shuffled_options_with_indices = [(opt, i) for i, opt in enumerate(options)]
                random.shuffle(shuffled_options_with_indices)
                options_map = {}
                for i, (option_text, original_index) in enumerate(shuffled_options_with_indices):
                    letter = chr(65 + i)
                    options_map[letter.lower()] = option_text
                    if question_data['representation_type'] == 'MCQ' and option_text == question_data['correct_answer']:
                        correct_letter = letter
            else:
                if not raw_options:
                    log.warning(f"Options are missing for question {question_data['question_id']}.")
                elif not isinstance(raw_options, list):
                    log.warning(f"Options for question {question_data['question_id']} are not a list (type: {type(raw_options)}).")
                options_map = None
                correct_letter = None

            session.set_current_question(question_data, options_map, correct_letter)
            session.questions_asked_count += 1

            await self._send_question(channel, session)
            
        except Exception as e:
            log.error(f"Error asking next question for channel {channel.id}: {e}", exc_info=True)
            await channel.send("An error occurred while preparing the next question. The quiz has ended.")
            quiz_sessions.clear_quiz_session(channel.id)

    async def _end_quiz(self, channel):
        """Ends the quiz session and provides a summary."""
        session = quiz_sessions.get_quiz_session(channel.id)
        if session:
            await channel.send(
                f"🎉 Quiz complete! You answered {session.correct_answers_count} out of {session.questions_asked_count} questions correctly."
            )
            log.info(f"Quiz ended in channel {channel.id} for user {session.user_id}. Score: {session.correct_answers_count}/{session.questions_asked_count}")
            quiz_sessions.clear_quiz_session(channel.id)
        else:
            await channel.send("The quiz has ended (no active session found to summarize).")
            log.info(f"Attempted to end quiz in channel {channel.id} but no session found.")

    @commands.command(
        name='quiz', 
        help='Starts a multi-question quiz. '
             'Usage: `!quiz <unit_number_or_range> <num_questions>`\n'
             'Example: `!quiz 1 5` (5 questions from Unit 1)\n'
             'Example: `!quiz 1-3 10` (10 questions from Units 1, 2, and 3)'
    )
    async def quiz(self, ctx, units_param: str, num_questions: int = config.DEFAULT_QUIZ_QUESTION_COUNT):
        """Starts a quiz with a specified number of questions from single or multiple units."""
        if quiz_sessions.get_quiz_session(ctx.channel.id):
            await ctx.send("A quiz is already active in this channel. Please finish it or use `!stopquiz`.")
            return

        if num_questions <= 0:
            await ctx.send("Please provide a positive number of questions.")
            return
        if num_questions > config.MAX_QUIZ_QUESTIONS:
            await ctx.send(f"Please limit the number of questions to {config.MAX_QUIZ_QUESTIONS} or fewer.")
            num_questions = config.MAX_QUIZ_QUESTIONS

        selected_unit_numbers = []
        if '-' in units_param:
            try:
                start_unit, end_unit = map(int, units_param.split('-'))
                if not (1 <= start_unit <= len(AP_UNITS_DATA) and 1 <= end_unit <= len(AP_UNITS_DATA) and start_unit <= end_unit):
                    await ctx.send(f"Invalid unit range. Units must be between 1 and {len(AP_UNITS_DATA)}, and the start unit must be less than or equal to the end unit.")
                    return
                selected_unit_numbers = list(range(start_unit, end_unit + 1))
            except ValueError:
                await ctx.send("Invalid unit range format. Please use `start_unit-end_unit` (e.g., `1-3`).")
                return
        else:
            try:
                single_unit = int(units_param)
                if single_unit not in AP_UNITS_DATA:
                    await ctx.send(f"Unit {single_unit} not found. Available units: {', '.join(map(str, AP_UNITS_DATA.keys()))}. Please pick a valid unit or range.")
                    return
                selected_unit_numbers = [single_unit]
            except ValueError:
                await ctx.send("Invalid unit number format. Please provide a single unit number (e.g., `1`) or a range (e.g., `1-3`).")
                return

        await bot.database.add_user(ctx.author.id, ctx.author.name)
        all_available_questions = await bot.database.get_questions_by_unit_list(selected_unit_numbers)

        if not all_available_questions:
            unit_display = units_param if '-' not in units_param else f"Units {units_param}"
            await ctx.send(f"Sorry, I couldn't find any questions for {unit_display}. Please ask an admin to generate questions for these units.")
            log.warning(f"No questions found for {unit_display} in channel {ctx.channel.id}.")
            return
        
        questions_for_quiz = random.sample(all_available_questions, min(num_questions, len(all_available_questions)))
        
        if len(questions_for_quiz) < num_questions:
            await ctx.send(f"I could only find {len(questions_for_quiz)} questions for {units_param}. Starting a quiz with these questions.")
            log.warning(f"Requested {num_questions} questions for {units_param}, but only found {len(questions_for_quiz)}.")

        await ctx.send(f"Starting a {len(questions_for_quiz)}-question quiz from {units_param}. Good luck!")
        log.info(f"Starting quiz in channel {ctx.channel.id} for {units_param} ({len(questions_for_quiz)} questions).")
        
        session = quiz_sessions.QuizSession(
            user_id=ctx.author.id,
            channel_id=ctx.channel.id,
            unit_number=None,
            skill_id=None,
            num_questions=len(questions_for_quiz),
            all_quiz_questions=questions_for_quiz
        )
        quiz_sessions.set_quiz_session(ctx.channel.id, session)
        await self._ask_next_question(ctx.channel)

    @commands.command(name='skillquiz', help='Starts a quiz with N questions from a specific Skill ID. Usage: `!skillquiz <skill_id> [num_questions]`\nExample: `!skillquiz 1.3 5` (Starts a 5-question quiz on Skill 1.3)')
    async def skill_quiz(self, ctx, skill_id: str, num_questions: int = config.DEFAULT_QUIZ_QUESTION_COUNT):
        """Starts a quiz for a specific skill."""
        if quiz_sessions.get_quiz_session(ctx.channel.id):
            await ctx.send("A quiz is already active in this channel. Please finish it or wait for it to time out (`!stopquiz` to force end).")
            return

        if num_questions > config.MAX_QUIZ_QUESTIONS:
            await ctx.send(f"You can request a maximum of {config.MAX_QUIZ_QUESTIONS} questions per quiz.")
            num_questions = config.MAX_QUIZ_QUESTIONS

        try:
            unit_number = int(skill_id.split('.')[0])
        except (ValueError, IndexError):
            await ctx.send(f"Invalid `skill_id` format: `{skill_id}`. Expected format like `U.S` (e.g., `1.3`).")
            return

        if unit_number not in AP_UNITS_DATA or skill_id not in AP_UNITS_DATA[unit_number]['skills']:
            await ctx.send(f"Invalid Unit Number or Skill ID. Use `{self.bot.command_prefix}listskills` to see available skills.")
            return

        await ctx.send(f"Starting a {num_questions}-question quiz on Skill {skill_id}: {AP_UNITS_DATA[unit_number]['skills'][skill_id]}.")
        log.info(f"User {ctx.author.id} starting a {num_questions}-question quiz on Skill {skill_id} in channel {ctx.channel.id}.")
        
        try:
            all_skill_questions = await self.bot.database.get_questions_by_skill(unit_number, skill_id)
            if not all_skill_questions:
                await ctx.send(f"Sorry, no questions found for Skill {skill_id} in Unit {unit_number}.")
                log.warning(f"No questions found in DB for Skill {skill_id}, Unit {unit_number}.")
                return

            if len(all_skill_questions) > num_questions:
                selected_questions = random.sample(all_skill_questions, num_questions)
            else:
                selected_questions = all_skill_questions
                await ctx.send(f"Note: Only {len(selected_questions)} questions available for this skill. Starting quiz with all of them.")

            session = quiz_sessions.QuizSession(
                user_id=ctx.author.id,
                channel_id=ctx.channel.id,
                unit_number=unit_number,
                skill_id=skill_id,
                num_questions=len(selected_questions),
                all_quiz_questions=selected_questions
            )
            quiz_sessions.set_quiz_session(ctx.channel.id, session)
            await self._ask_next_question(ctx.channel)
        except Exception as e:
            log.error(f"Error starting skill quiz: {e}", exc_info=True)
            await ctx.send("An error occurred while trying to start the skill quiz. Please try again later.")

    @commands.command(name='answer', help='Submit your answer for the current quiz question. Usage: `!answer <your_answer>`')
    async def answer(self, ctx, *user_answer_parts):
        """Handles user submissions for quiz answers."""
        if not user_answer_parts:
            await ctx.send("Please provide an answer. Usage: `!answer <your_answer>`")
            return

        session = quiz_sessions.get_quiz_session(ctx.channel.id)
        if not session or not session.current_question_data:
            await ctx.send("There is no active quiz question to answer in this channel. Start a quiz with `!quiz` or `!skillquiz`.")
            return

        user_answer = " ".join(user_answer_parts).strip()
        channel_id = ctx.channel.id
        current_q_data = session.current_question_data
        is_correct = False
        ai_raw_feedback = ""

        session.last_activity_time = time.time()
        quiz_sessions.set_quiz_session(channel_id, session)

        if current_q_data['representation_type'] == 'MCQ':
            normalized_user_answer = user_answer.lower().strip().replace('.', '')

            if session.current_options_map and normalized_user_answer in session.current_options_map:
                if normalized_user_answer.upper() == session.correct_letter:
                    is_correct = True
                    ai_raw_feedback = "Correct! Your multiple-choice answer is spot on."
                else:
                    is_correct = False
                    ai_raw_feedback = "Incorrect. That's not the right option."
            else:
                matched_letter = None
                for letter, text in session.current_options_map.items():
                    if user_answer.lower() == text.lower():
                        matched_letter = letter.upper()
                        break
                
                if matched_letter and matched_letter == session.correct_letter:
                    is_correct = True
                    ai_raw_feedback = "Correct! You got the right answer by typing the option text."
                else:
                    is_correct = False
                    ai_raw_feedback = "Incorrect. Please choose one of the options (e.g., 'A' or the full option text)."

        elif current_q_data['representation_type'] == 'FRQ':
            await ctx.send("Evaluating your free-response answer, please wait...")
            try:
                grading_result = await groq_api.grade_free_response_answer(
                    question_text=current_q_data['question_text'],
                    correct_answer=current_q_data['correct_answer'],
                    user_answer=user_answer,
                    explanation=current_q_data['explanation']
                )
                
                ai_raw_feedback = grading_result.get('feedback', 'AI grading failed to provide feedback.')
                
                if ai_raw_feedback.lower().startswith("correct!"):
                    is_correct = True
                elif ai_raw_feedback.lower().startswith("incorrect."):
                    is_correct = False
                else:
                    log.warning(f"AI feedback for FRQ did not start with 'Correct!' or 'Incorrect.': {ai_raw_feedback}")
                    is_correct = False
                    ai_raw_feedback = f"Incorrect. The AI could not process your answer clearly. Raw response: {ai_raw_feedback}"

            except Exception as e:
                log.error(f"Error grading FRQ answer for question {current_q_data['question_id']}: {e}", exc_info=True)
                await ctx.send("An error occurred while evaluating your answer. Please try again.")
                return

        await bot.database.record_answer(
            user_id=ctx.author.id,
            question_id=current_q_data['question_id'],
            is_correct=is_correct,
            user_answer=user_answer
        )

        feedback_embed = discord.Embed(
            title=f"Question {current_q_data['question_id']} - Result",
            color=discord.Color.green() if is_correct else discord.Color.red()
        )
        feedback_embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else discord.Embed.Empty)

        ai_feedback_chunks = chunk_text(ai_raw_feedback)
        for i, chunk in enumerate(ai_feedback_chunks):
            field_name = "AI Feedback"
            if len(ai_feedback_chunks) > 1:
                field_name = f"AI Feedback (Part {i+1})"
            feedback_embed.add_field(name=field_name, value=chunk, inline=False)

        if is_correct:
            session.correct_answers_count += 1
        else:
            session.incorrect_answers_count += 1

        if not is_correct or current_q_data['representation_type'] == 'FRQ': 
            full_explanation_text = ""
            if current_q_data['representation_type'] == 'MCQ':
                correct_answer_display = current_q_data['correct_answer']
                if session.current_options_map and session.correct_letter:
                    correct_answer_display = f"{session.correct_letter}. {session.current_options_map.get(session.correct_letter.lower(), current_q_data['correct_answer'])}"

                full_explanation_text = f"The correct answer was: ||{correct_answer_display}||\n\nExplanation: {current_q_data['explanation']}"
            else:
                full_explanation_text = f"The correct answer was: ||{current_q_data['correct_answer']}||\n\nExplanation: {current_q_data['explanation']}"

            explanation_chunks = chunk_text(full_explanation_text)
            for i, chunk in enumerate(explanation_chunks):
                feedback_embed.add_field(name=f"Detailed Explanation{' (cont.)' if i > 0 else ''}", value=chunk, inline=False)

        await ctx.send(embed=feedback_embed)

        log.info(f"User {ctx.author.id} answered question {current_q_data['question_id']}. Correct: {is_correct}. "
                 f"Asked: {session.questions_asked_count}/{session.num_questions}. "
                 f"Correct count: {session.correct_answers_count}")

        quiz_sessions.set_quiz_session(channel_id, session)

        if session.is_complete():
            await asyncio.sleep(1)
            await self._end_quiz(ctx.channel)
        else:
            await asyncio.sleep(1)
            await self._ask_next_question(ctx.channel)

    @commands.command(name='stopquiz', help='Stops the current active quiz in this channel.')
    async def stop_quiz(self, ctx):
        """Stops any active quiz session in the current channel."""
        session = quiz_sessions.get_quiz_session(ctx.channel.id)
        if session:
            if ctx.author.id == session.user_id or ctx.author.guild_permissions.manage_channels:
                await ctx.send(f"🚫 Quiz stopped! You answered {session.correct_answers_count} out of {session.questions_asked_count} questions correctly.")
                log.info(f"Quiz in channel {ctx.channel.id} manually stopped by {ctx.author.id}. Score: {session.correct_answers_count}/{session.questions_asked_count}")
                quiz_sessions.clear_quiz_session(ctx.channel.id)
            else:
                await ctx.send("You can only stop quizzes that you started, or if you have 'Manage Channels' permission.")
        else:
            await ctx.send("There is no active quiz in this channel to stop.")
            log.info(f"Attempted to stop quiz in channel {ctx.channel.id} but no active session found.")

async def setup(bot):
    await bot.add_cog(QuizCommands(bot))