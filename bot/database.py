import aiosqlite
import logging
import json
import random
import re
import os
from bot import config

log = logging.getLogger(__name__)

_db_connection = None

async def get_db_connection():
    """
    Establishes and returns a single, global database connection.
    Ensures the database directory exists before connecting.
    """
    global _db_connection
    if _db_connection is None:
        try:
            os.makedirs(config.DB_DIRECTORY, exist_ok=True)
            log.info(f"Ensured database directory exists: {config.DB_DIRECTORY}")
        except OSError as e:
            log.critical(f"Failed to create database directory {config.DB_DIRECTORY}: {e}", exc_info=True)
            raise

        _db_connection = await aiosqlite.connect(config.DATABASE_URL)
        print(f"Connecting to database at: {config.DATABASE_URL}")
        await _db_connection.execute("PRAGMA foreign_keys = ON;")
        log.info("Database connection established and foreign keys enabled.")
    return _db_connection

async def initialize_db():
    """
    Initializes the database by creating necessary tables if they do not already exist.
    Tables include 'users', 'questions', 'reports', and 'answers'.
    """
    conn = await get_db_connection()
    
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            correct_answers INTEGER DEFAULT 0,
            total_answers INTEGER DEFAULT 0,
            registration_date TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    await conn.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            question_id TEXT PRIMARY KEY,
            unit_number INTEGER NOT NULL,
            skill_id TEXT NOT NULL,
            question_text TEXT NOT NULL,
            options TEXT,
            correct_answer TEXT NOT NULL,
            explanation TEXT NOT NULL,
            representation_type TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            calculator_active BOOLEAN NOT NULL,
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_disabled BOOLEAN DEFAULT FALSE
        )
    ''')

    await conn.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            reason TEXT,
            report_date TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions (question_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        )
    ''')

    await conn.execute('''
        CREATE TABLE IF NOT EXISTS answers (
            answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            is_correct BOOLEAN NOT NULL,
            user_answer TEXT NOT NULL,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES questions (question_id) ON DELETE CASCADE
        )
    ''')
    await conn.commit()
    log.info("Database initialized with users, questions, reports, and answers tables.")

async def close_db_connection():
    """Closes the global database connection if it is open."""
    global _db_connection
    if _db_connection:
        await _db_connection.close()
        _db_connection = None
        log.info("Database connection closed.")

async def add_user(user_id: int, username: str):
    """
    Adds a new user to the database if they don't already exist.
    Updates username if user_id exists.
    """
    conn = await get_db_connection()
    await conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (user_id, username)
    )
    await conn.commit()
    log.info(f"User {username} ({user_id}) added or already exists.")

async def add_question(question_data: dict):
    """
    Adds a new question to the database.
    Returns True on success, False if the question already exists or an error occurs.
    """
    conn = await get_db_connection()
    options_json = json.dumps(question_data['options']) if question_data['options'] is not None else None
    try:
        await conn.execute(
            """
            INSERT INTO questions (question_id, unit_number, skill_id, question_text, options, correct_answer, explanation, representation_type, difficulty, calculator_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question_data['question_id'],
                question_data['unit_number'],
                question_data['skill_id'],
                question_data['question_text'],
                options_json,
                question_data['correct_answer'],
                question_data['explanation'],
                question_data['representation_type'],
                question_data['difficulty'],
                question_data['calculator_active']
            )
        )
        await conn.commit()
        log.info(f"Question {question_data['question_id']} added to database.")
        return True
    except aiosqlite.IntegrityError:
        log.warning(f"Question {question_data['question_id']} already exists, skipping.")
        return False
    except Exception as e:
        log.error(f"Error adding question {question_data['question_id']}: {e}", exc_info=True)
        return False

async def get_question(question_id: str):
    """
    Retrieves a single question by its unique ID.
    Returns the question data as a dictionary, or None if not found.
    """
    conn = await get_db_connection()
    cursor = await conn.execute(
        "SELECT question_id, unit_number, skill_id, question_text, options, correct_answer, explanation, representation_type, difficulty, calculator_active, is_disabled FROM questions WHERE question_id = ?",
        (question_id,)
    )
    row = await cursor.fetchone()
    if row:
        question_data = {
            "question_id": row[0],
            "unit_number": row[1],
            "skill_id": row[2],
            "question_text": row[3],
            "options": json.loads(row[4]) if row[4] else None,
            "correct_answer": row[5],
            "explanation": row[6],
            "representation_type": row[7],
            "difficulty": row[8],
            "calculator_active": bool(row[9]),
            "is_disabled": bool(row[10])
        }
        log.debug(f"Fetched question {question_id}.")
        return question_data
    log.debug(f"Question {question_id} not found.")
    return None

async def get_random_question(unit_number: int = None, skill_id: str = None):
    """
    Retrieves a single random question, optionally filtered by unit number and skill ID.
    Only active (non-disabled) questions are considered.
    Returns the question data as a dictionary, or None if no matching questions are found.
    """
    conn = await get_db_connection()
    query = "SELECT question_id, unit_number, skill_id, question_text, options, correct_answer, explanation, representation_type, difficulty, calculator_active FROM questions WHERE is_disabled = FALSE"
    params = []

    if unit_number:
        query += " AND unit_number = ?"
        params.append(unit_number)
    if skill_id:
        query += " AND skill_id = ?"
        params.append(skill_id)

    query += " ORDER BY RANDOM() LIMIT 1"
    
    cursor = await conn.execute(query, params)
    row = await cursor.fetchone()

    if row:
        question_data = {
            "question_id": row[0],
            "unit_number": row[1],
            "skill_id": row[2],
            "question_text": row[3],
            "options": json.loads(row[4]) if row[4] else None,
            "correct_answer": row[5],
            "explanation": row[6],
            "representation_type": row[7],
            "difficulty": row[8],
            "calculator_active": bool(row[9])
        }
        log.debug(f"Fetched random question: {question_data['question_id']}.")
        return question_data
    log.info("No random question found matching criteria.")
    return None

async def get_questions_by_skill(unit_number: int, skill_id: str):
    """
    Retrieves all active questions associated with a specific unit number and skill ID.
    Returns a list of question dictionaries.
    """
    conn = await get_db_connection()
    cursor = await conn.execute(
        "SELECT question_id, unit_number, skill_id, question_text, options, correct_answer, explanation, representation_type, difficulty, calculator_active FROM questions WHERE unit_number = ? AND skill_id = ? AND is_disabled = FALSE",
        (unit_number, skill_id)
    )
    rows = await cursor.fetchall()
    questions = []
    for row in rows:
        questions.append({
            "question_id": row[0],
            "unit_number": row[1],
            "skill_id": row[2],
            "question_text": row[3],
            "options": json.loads(row[4]) if row[4] else None,
            "correct_answer": row[5],
            "explanation": row[6],
            "representation_type": row[7],
            "difficulty": row[8],
            "calculator_active": bool(row[9])
        })
    log.debug(f"Fetched {len(questions)} questions for U{unit_number} S{skill_id}.")
    return questions

async def get_questions_by_unit_list(unit_numbers: list):
    """
    Retrieves all active questions from a given list of unit numbers.
    Returns a list of question dictionaries.
    """
    if not unit_numbers:
        return []

    conn = await get_db_connection()
    placeholders = ','.join(['?'] * len(unit_numbers))
    query = f"SELECT question_id, unit_number, skill_id, question_text, options, correct_answer, explanation, representation_type, difficulty, calculator_active FROM questions WHERE unit_number IN ({placeholders}) AND is_disabled = FALSE"
    
    cursor = await conn.execute(query, unit_numbers)
    rows = await cursor.fetchall()
    questions = []
    for row in rows:
        questions.append({
            "question_id": row[0],
            "unit_number": row[1],
            "skill_id": row[2],
            "question_text": row[3],
            "options": json.loads(row[4]) if row[4] else None,
            "correct_answer": row[5],
            "explanation": row[6],
            "representation_type": row[7],
            "difficulty": row[8],
            "calculator_active": bool(row[9])
        })
    log.debug(f"Fetched {len(questions)} questions for units {unit_numbers}.")
    return questions

async def report_question(question_id: str, user_id: int, reason: str):
    """
    Records a report for a specific question by a user with a given reason.
    Returns True on successful reporting, False otherwise.
    """
    conn = await get_db_connection()
    try:
        await conn.execute(
            "INSERT INTO reports (question_id, user_id, reason) VALUES (?, ?, ?)",
            (question_id, user_id, reason)
        )
        await conn.commit()
        log.info(f"Question {question_id} reported by user {user_id}.")
        return True
    except Exception as e:
        log.error(f"Error reporting question {question_id} by user {user_id}: {e}", exc_info=True)
        return False

async def get_active_reports():
    """
    Retrieves all active question reports from the database, ordered by report date.
    Returns a list of report dictionaries.
    """
    conn = await get_db_connection()
    cursor = await conn.execute(
        "SELECT report_id, question_id, user_id, reason, report_date FROM reports ORDER BY report_date DESC"
    )
    rows = await cursor.fetchall()
    reports = []
    for row in rows:
        reports.append({
            "report_id": row[0],
            "question_id": row[1],
            "user_id": row[2],
            "reason": row[3],
            "report_date": row[4]
        })
    log.debug(f"Fetched {len(reports)} active reports.")
    return reports

async def clear_report(question_id: str):
    """
    Deletes all reports associated with a specific question ID.
    Returns True if any reports were cleared, False otherwise.
    """
    conn = await get_db_connection()
    cursor = await conn.execute(
        "DELETE FROM reports WHERE question_id = ?",
        (question_id,)
    )
    await conn.commit()
    if cursor.rowcount > 0:
        log.info(f"Reports cleared for question {question_id}. Rows affected: {cursor.rowcount}")
        return True
    log.debug(f"No reports found for question {question_id} to clear.")
    return False

async def disable_question(question_id: str, disable: bool = True):
    """
    Sets the 'is_disabled' status of a question.
    If `disable` is True, the question will be marked as disabled. If False, it will be enabled.
    Returns True if the question's status was updated, False if the question was not found.
    """
    conn = await get_db_connection()
    cursor = await conn.execute(
        "UPDATE questions SET is_disabled = ? WHERE question_id = ?",
        (disable, question_id)
    )
    await conn.commit()
    if cursor.rowcount > 0:
        log.info(f"Question {question_id} disabled status set to {disable}.")
        return True
    log.warning(f"Question {question_id} not found for disabling/enabling.")
    return False

async def record_answer(user_id: int, question_id: str, is_correct: bool, user_answer: str):
    """
    Records a user's answer to a question and updates their overall statistics.
    """
    conn = await get_db_connection()
    
    await conn.execute(
        "INSERT INTO answers (user_id, question_id, is_correct, user_answer) VALUES (?, ?, ?, ?)",
        (user_id, question_id, is_correct, user_answer)
    )
    
    await conn.execute(
        "UPDATE users SET total_answers = total_answers + 1, correct_answers = correct_answers + ? WHERE user_id = ?",
        (1 if is_correct else 0, user_id)
    )
    await conn.commit()
    log.debug(f"Answer recorded for user {user_id}, question {question_id}. Correct: {is_correct}.")

async def get_recent_questions_overview(limit: int = 10, unit_number: int = None, skill_id: str = None):
    """
    Retrieves an overview of recently added questions, with options to filter by
    limit, unit number, and skill ID. Excludes disabled questions.
    Returns a list of dictionaries, each containing a question ID, a snippet of the question text,
    unit number, and skill ID.
    """
    conn = await get_db_connection()
    query = "SELECT question_id, question_text, unit_number, skill_id FROM questions WHERE is_disabled = FALSE"
    conditions = []
    params = []

    if unit_number is not None:
        conditions.append("unit_number = ?")
        params.append(unit_number)
    
    if skill_id:
        conditions.append("skill_id = ?")
        params.append(skill_id)

    if conditions:
        query += " AND " + " AND ".join(conditions)
    
    query += " ORDER BY generated_at DESC LIMIT ?"
    params.append(limit)

    log.debug(f"Executing overview query: {query} with params: {params}")
    cursor = await conn.execute(query, params)
    rows = await cursor.fetchall()
    
    questions_overview = []
    for row in rows:
        question_text_snippet = row[1][:150] + "..." if len(row[1]) > 150 else row[1]
        questions_overview.append({
            "question_id": row[0],
            "question_text_snippet": question_text_snippet,
            "unit_number": row[2],
            "skill_id": row[3]
        })
    return questions_overview

async def get_total_question_count():
    """
    Returns the total number of questions stored in the database, including disabled ones.
    """
    conn = await get_db_connection()
    cursor = await conn.execute("SELECT COUNT(*) FROM questions")
    count = (await cursor.fetchone())[0]
    log.debug(f"Total questions in DB: {count}")
    return count

async def delete_all_questions():
    """
    Deletes all questions, associated answers, and reports from the database.
    Foreign key checks are temporarily disabled to allow for mass deletion without constraint issues.
    """
    conn = await get_db_connection()
    try:
        await conn.execute("PRAGMA foreign_keys = OFF;")
        await conn.commit()

        await conn.execute("DELETE FROM answers")
        log.info("All records deleted from 'answers' table.")
        
        await conn.execute("DELETE FROM reports")
        log.info("All records deleted from 'reports' table.")
        
        await conn.execute("DELETE FROM questions")
        log.info("All records deleted from 'questions' table.")

        await conn.commit()

    except Exception as e:
        log.error(f"Error during mass deletion: {e}", exc_info=True)
        return False
    finally:
        try:
            await conn.execute("PRAGMA foreign_keys = ON;")
            await conn.commit()
            log.info("Foreign key constraints re-enabled.")
        except Exception as e:
            log.error(f"Error re-enabling foreign keys: {e}", exc_info=True)
    
    log.info("All questions, answers, and reports successfully deleted from the database.")
    return True