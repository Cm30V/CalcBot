import time
import logging

log = logging.getLogger(__name__)

# Stores active quiz sessions, keyed by channel ID.
# This allows for one active quiz per channel.
active_quiz_sessions = {} # Example: {channel_id: QuizSession_object}

class QuizSession:
    """
    Manages the state and progress of a single quiz session for a user in a specific channel.
    """
    def __init__(self, user_id: int, channel_id: int, unit_number: int, skill_id: str, num_questions: int, all_quiz_questions: list):
        self.user_id = user_id
        self.channel_id = channel_id
        self.unit_number = unit_number
        self.skill_id = skill_id
        self.num_questions = num_questions
        self.questions_asked_count = 0
        self.correct_answers_count = 0
        self.incorrect_answers_count = 0
        self.all_quiz_questions = all_quiz_questions # The complete list of questions for this quiz
        self.questions_history = []                  # IDs of questions already presented
        self.current_question_data = None            # Full data for the question currently being asked
        self.current_options_map = None              # Maps option letters (e.g., 'a') to option text for MCQs
        self.correct_letter = None                   # The correct option letter for the current MCQ
        self.start_time = time.time()                # When the quiz session began
        self.last_activity_time = time.time()        # Timestamp of the last user interaction, used for timeouts

    def set_current_question(self, question_data: dict, options_map: dict = None, correct_letter: str = None):
        """Sets the details of the question currently being presented to the user."""
        self.current_question_data = question_data
        self.current_options_map = options_map
        self.correct_letter = correct_letter
        self.last_activity_time = time.time()

    def clear_current_question(self):
        """Resets the current question data, typically after an answer is received or quiz ends."""
        self.current_question_data = None
        self.current_options_map = None
        self.correct_letter = None
        self.last_activity_time = time.time()

    def is_complete(self) -> bool:
        """Checks if the quiz has reached its specified number of questions."""
        return self.questions_asked_count >= self.num_questions

    def is_timed_out(self, timeout_seconds: int) -> bool:
        """Checks if the quiz session has timed out due to inactivity."""
        return (time.time() - self.last_activity_time) > timeout_seconds

def get_quiz_session(channel_id: int):
    """
    Retrieves an active quiz session for a given channel ID.
    Updates the session's last activity time upon retrieval.
    """
    session = active_quiz_sessions.get(channel_id)
    if session:
        session.last_activity_time = time.time()
    return session

def set_quiz_session(channel_id: int, session: QuizSession):
    """
    Stores a new or updates an existing quiz session for a specific channel.
    """
    active_quiz_sessions[channel_id] = session
    log.debug(f"Quiz session set for channel {channel_id}. Active quiz sessions: {len(active_quiz_sessions)}")

def clear_all_quiz_sessions():
    """
    Removes all active quiz sessions from every channel.
    """
    active_quiz_sessions.clear()
    log.debug("All active quiz sessions cleared.")


def clear_quiz_session(channel_id: int):
    """
    Removes a quiz session from the active sessions dictionary.
    """
    if channel_id in active_quiz_sessions:
        del active_quiz_sessions[channel_id]
        log.debug(f"Quiz session cleared for channel {channel_id}. Active quiz sessions: {len(active_quiz_sessions)}")

def get_timed_out_quiz_sessions(timeout_seconds: int) -> list:
    """
    Identifies and returns a list of quiz sessions that have exceeded the inactivity timeout.
    """
    timed_out_sessions = []
    current_time = time.time()
    for channel_id, session in active_quiz_sessions.items():
        if (current_time - session.last_activity_time) > timeout_seconds:
            timed_out_sessions.append((channel_id, session)) # Return both ID and session object
    return timed_out_sessions