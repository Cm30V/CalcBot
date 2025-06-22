import time
import logging
from ap_units import AP_UNITS_DATA

log = logging.getLogger(__name__)

active_quiz_sessions = {}

class UserSession:
    def __init__(self, user_id, channel_id, question_id, unit=None, difficulty=None, skill_num=None):
        self.user_id = user_id
        self.channel_id = channel_id
        self.question_id = question_id
        self.start_time = time.time()
        self.question_message_id = None
        self.initial_unit = unit
        self.initial_difficulty = difficulty
        self.initial_skill_num = skill_num
        self.waiting_for_next = False

    def set_question_message_id(self, message_id):
        self.question_message_id = message_id

    def is_timed_out(self, timeout_seconds):
        return (time.time() - self.start_time) > timeout_seconds

def set_user_session(user_id, session):
    active_quiz_sessions[user_id] = session
    log.debug(f"Session set for user {user_id}. Active sessions: {len(active_quiz_sessions)}")

def get_user_session(user_id):
    session = active_quiz_sessions.get(user_id)
    if session:
        session.start_time = time.time()
    return session

def clear_user_session(user_id):
    if user_id in active_quiz_sessions:
        del active_quiz_sessions[user_id]
        log.debug(f"Session cleared for user {user_id}. Active sessions: {len(active_quiz_sessions)}")

def get_timed_out_sessions(timeout_seconds):
    timed_out = []
    current_time = time.time()
    for user_id, session in list(active_quiz_sessions.items()):
        if (current_time - session.start_time) > timeout_seconds:
            timed_out.append((user_id, session))
    return timed_out

GLOBAL_SKILL_MAP = []
skill_counter = 1
for unit_number, unit_data in AP_UNITS_DATA.items():
    unit_name = unit_data['name']

    for skill_id, skill_full_name in unit_data['skills'].items():
        GLOBAL_SKILL_MAP.append({
            'skill_number': skill_counter,
            'unit_name': f"Unit {unit_number}: {unit_name}",
            'unit_number': unit_number,
            'skill_id': skill_id,
            'skill_full_name': skill_full_name
        })
        skill_counter += 1

log.info(f"Generated GLOBAL_SKILL_MAP with {len(GLOBAL_SKILL_MAP)} skills.")