import os
from groq import AsyncGroq
import logging
import json
import re 
from bot import config
from ap_units import AP_UNITS_DATA

log = logging.getLogger(__name__)

client: AsyncGroq = None

def initialize_groq_client():
    """
    Initializes the Groq API client with the API key from environment variables.
    Raises a ValueError if the API key is not found or an Exception if client initialization fails.
    """
    global client
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        log.error("GROQ_API_KEY not found in environment variables.")
        raise ValueError("GROQ_API_KEY is not set.")
    try:
        client = AsyncGroq(api_key=api_key)
        log.info("Groq client initialized.")
    except Exception as e:
        log.error(f"Failed to initialize Groq client: {e}", exc_info=True)
        raise

async def generate_text(prompt: str, model: str = config.GROQ_DEFAULT_MODEL):
    """
    Generates general text content using the Groq API.
    Raises a RuntimeError if the Groq client has not been initialized.
    """
    if client is None:
        log.error("Groq client not initialized. Call initialize_groq_client() first.")
        raise RuntimeError("Groq client not initialized.")
    
    try:
        chat_completion = await client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model=config.GROQ_DEFAULT_MODEL,
            temperature=config.GROQ_DEFAULT_TEMPERATURE,
            max_tokens=config.GROQ_DEFAULT_MAX_TOKENS,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        log.error(f"Error generating text with Groq: {e}", exc_info=True)
        return "An error occurred while generating text."

async def generate_question_json(unit_number: int, skill_id: str, question_type: str = "MCQ", difficulty: str = "Medium", calculator_active: bool = False):
    """
    Generates an AP Calculus BC question in a strict JSON format using the Groq API.
    Includes comprehensive validation of the generated JSON against the expected schema and parameters.
    """
    if client is None:
        log.error("Groq client not initialized. Call initialize_groq_client() first.")
        raise RuntimeError("Groq client not initialized.")
    
    unit_data = AP_UNITS_DATA.get(unit_number)
    skill_name = unit_data.get('skills', {}).get(skill_id, f"Skill {skill_id}") if unit_data else f"Skill {skill_id}"

    # Defines the strict JSON schema to guide the LLM and for post-generation validation.
    json_schema = {
        "type": "object",
        "properties": {
            "question_id": {"type": "string", "pattern": f"^{unit_number}-{skill_id}-" + "[0-9A-Fa-f]{8,}$"},
            "unit_number": {"type": "integer", "const": unit_number},
            "skill_id": {"type": "string", "const": skill_id},
            "question_text": {"type": "string", "min_length": 20},
            "options": {"type": "array", "items": {"type": "string"}, "min_items": 4, "max_items": 4} if question_type == "MCQ" else {"type": "null"},
            "correct_answer": {"type": "string"},
            "explanation": {"type": "string", "min_length": 50},
            "representation_type": {"type": "string", "enum": ["MCQ", "FRQ"]},
            "difficulty": {"type": "string", "enum": ["Easy", "Medium", "Hard"]},
            "calculator_active": {"type": "boolean"}
        },
        "required": ["question_id", "unit_number", "skill_id", "question_text", "correct_answer", "explanation", "representation_type", "difficulty", "calculator_active"]
    }
    if question_type == "MCQ":
        json_schema["required"].append("options")

    prompt = f"""
    You are an expert AP Calculus BC teacher. Your task is to generate a single, highly accurate and concise AP Calculus BC question in strict JSON format.
    The question must precisely match the specified unit, skill, type, difficulty, and calculator status. 

    Unit: {unit_number} (Topic: {unit_data.get('name', 'N/A')})
    Skill ID: {skill_id} (Description: {skill_name})
    Question Type: {question_type}
    Difficulty: {difficulty}
    Calculator Active: {calculator_active}

    For 'MCQ' questions:
    - Provide exactly four distinct options in the 'options' array. Each option MUST be a string containing ONLY the option text, without any leading letters (e.g., "A. ", "B. ") or additional formatting.
    - The 'correct_answer' for MCQ should be the letter (e.g., "A", "B", "C", "D") corresponding to the correct option based on their alphabetical order, not the option text itself.

    For 'FRQ' questions:
    - The 'options' field should be explicitly `null`.
    - The 'correct_answer' for FRQ should be the numerical or analytical correct value/expression.

    The 'explanation' must be a detailed, VERY concise, and accurate step-by-step reasoning for the correct answer, sufficient for a student to understand. It must be at least 50 characters long.
    The 'question_id' must follow the format 'UNIT-SKILL-RANDOMSTRING', for example '1-1.1A-abcdef1234567890'.
    The 'skill_id' field in the JSON MUST be a string, exactly matching the requested skill_id: '{skill_id}'. It must NOT be an array or list of choices.
    The 'correct_answer' should be concise.

    DO NOT include any conversational text, markdown outside the JSON, or comments. Respond ONLY with the JSON object.

    Example JSON structure for MCQ:
    ```json
    {{
        "question_id": "{unit_number}-{skill_id}-" + "YOUR_UNIQUE_RANDOM_PART",
        "unit_number": {unit_number},
        "skill_id": "{skill_id}",
        "question_text": "What is the limit of f(x) as x approaches 0?",
        "options": ["0", "1", "-1", "Does Not Exist"],
        "correct_answer": "A",
        "explanation": "To find the limit, apply L'Hopital's Rule or algebraic simplification. The detailed steps lead to the answer.",
        "representation_type": "MCQ",
        "difficulty": "{difficulty}",
        "calculator_active": {str(calculator_active).lower()}
    }}
    ```
    Example JSON structure for FRQ:
    ```json
    {{
        "question_id": "{unit_number}-{skill_id}-" + "YOUR_UNIQUE_RANDOM_PART",
        "unit_number": {unit_number},
        "skill_id": "{skill_id}",
        "question_text": "Find the derivative of f(x) = x^3 + 2x.",
        "options": null,
        "correct_answer": "3x^2 + 2",
        "explanation": "Apply the power rule for derivatives: d/dx(x^n) = nx^(n-1). The derivative of x^3 is 3x^2, and the derivative of 2x is 2.",
        "representation_type": "FRQ",
        "difficulty": "{difficulty}",
        "calculator_active": {str(calculator_active).lower()}
    }}
    ```
    """
    
    try:
        log.debug(f"Sending question generation prompt to Groq for U{unit_number} S{skill_id} ({question_type}):\n{prompt}")
        chat_completion = await client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that generates AP Calculus BC questions in a strict JSON format."
                },
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model=config.GROQ_DEFAULT_MODEL,
            temperature=config.GROQ_DEFAULT_TEMPERATURE,
            max_tokens=config.GROQ_DEFAULT_MAX_TOKENS,
            response_format={"type": "json_object"}
        )
        llm_response_text = chat_completion.choices[0].message.content
        log.debug(f"Raw Groq question response: {llm_response_text}")

        try:
            question_data = json.loads(llm_response_text)
        except json.JSONDecodeError as e:
            log.error(f"Failed to decode JSON from Groq question response: {e}. Raw response: {llm_response_text}", exc_info=True)
            raise ValueError(f"Groq returned malformed JSON: {e}")

        # --- Post-generation Validation and Correction ---
        # Ensure generated fields match requested parameters, correcting if necessary.
        if question_data.get('unit_number') != unit_number:
            log.warning(f"Generated unit_number '{question_data.get('unit_number')}' does not match requested '{unit_number}'. Forcing correction.")
            question_data['unit_number'] = unit_number

        if not isinstance(question_data.get('skill_id'), str) or question_data.get('skill_id') != skill_id:
            log.error(f"Groq returned incorrect or malformed 'skill_id': '{question_data.get('skill_id')}'. Expected: '{skill_id}'. Forcing correction.")
            question_data['skill_id'] = skill_id 

        if question_data.get('representation_type') != question_type:
            log.warning(f"Generated representation_type '{question_data.get('representation_type')}' does not match requested '{question_type}'. Forcing correction.")
            question_data['representation_type'] = question_type

        if question_data.get('difficulty') != difficulty:
            log.warning(f"Generated difficulty '{question_data.get('difficulty')}' does not match requested '{difficulty}'. Forcing correction.")
            question_data['difficulty'] = difficulty
        
        if question_data.get('calculator_active') != calculator_active:
            log.warning(f"Generated calculator_active '{question_data.get('calculator_active')}' does not match requested '{calculator_active}'. Forcing correction.")
            question_data['calculator_active'] = calculator_active

        # Validate options for MCQ and FRQ
        if question_type == "MCQ":
            options = question_data.get('options')
            if not isinstance(options, list) or len(options) != 4 or not all(isinstance(opt, str) for opt in options):
                log.error(f"Groq returned malformed 'options' for MCQ: {options}. Expected a list of 4 strings. Raising error.")
                raise ValueError("Groq returned malformed MCQ options.")
            
            # Ensure correct_answer is a valid letter for MCQs
            if question_data.get('correct_answer') not in ['A', 'B', 'C', 'D', 'a', 'b', 'c', 'd']:
                log.warning(f"MCQ correct_answer '{question_data.get('correct_answer')}' is not a valid letter (A-D).")
                # Attempts to extract letter if format is "A. Option Text"
                if isinstance(question_data.get('correct_answer'), str) and len(question_data['correct_answer']) >= 1:
                    first_char = question_data['correct_answer'][0].upper()
                    if first_char in ['A', 'B', 'C', 'D']:
                        question_data['correct_answer'] = first_char
                        log.info(f"Corrected MCQ correct_answer to '{first_char}'.")
        else: # FRQ
            if question_data.get('options') is not None:
                log.warning(f"Groq returned non-null 'options' for FRQ question: {question_data.get('options')}. Forcing null.")
                question_data['options'] = None

        # Log a warning if the explanation is too short, indicating potential lower quality.
        if len(question_data.get('explanation', '')) < 50:
            log.warning(f"Groq returned a short explanation for question {question_data.get('question_id')}. Length: {len(question_data.get('explanation', ''))}. Consider regenerating or manually editing for better quality.")

        log.info(f"Successfully generated and validated question {question_data.get('question_id')}.")
        return question_data

    except Exception as e:
        log.error(f"Error during question generation for U{unit_number} S{skill_id} ({question_type}): {e}", exc_info=True)
        return None # Indicate failure to generate a valid question

async def grade_free_response_answer(question_text: str, correct_answer: str, user_answer: str, explanation: str) -> dict:
    """
    Grades a Free Response Question (FRQ) answer using the Groq API.
    The AI's feedback will strictly start with "Correct!" or "Incorrect." to signify the assessment THE FEEDBACK SHOULD BE VERY CONCISE.

    Args:
        question_text (str): The full text of the question.
        correct_answer (str): The expected correct answer.
        user_answer (str): The user's submitted answer.
        explanation (str): The detailed explanation for the correct answer.

    Returns:
        dict: A dictionary containing 'feedback' (str), where the first word
              determines correctness.
    """
    if client is None:
        log.error("Groq client not initialized. Call initialize_groq_client() first.")
        raise RuntimeError("Groq client not initialized.")

    grading_prompt = f"""
    You are an expert, precise, and objective grader for a high school math/science bot.
    Your task is to accurately grade a user's free response answer to a question.

    Question: {question_text}
    Official Correct Answer: {correct_answer}
    Official Explanation/Rubric: {explanation}
    ---
    User's Submitted Answer: {user_answer}

    Carefully evaluate the user's answer against the provided Official Correct Answer and Explanation/Rubric.
    Your response MUST start with either "Correct!" or "Incorrect." followed by a space.  Do NOT include any internal thoughts, reasoning processes, or roleplay indicators like <think>. Be concise.
    Then, provide a concise, constructive, and descriptive feedback message. DO NOT HALLUCINATE EITHER.

    - If the user's answer is substantially correct, begin with "Correct!" and then briefly confirm or highlight a key strength of their solution.
    - If the user's answer is incorrect or partially correct, begin with "Incorrect." and then clearly identify what was missed, misunderstood, or incorrect. Provide a hint or suggestion for improvement.

    DO NOT include any other conversational text or formatting. Respond ONLY with the grading feedback string.

    Examples:
    Correct! Your solution accurately applies the fundamental theorem of calculus to find the correct area. Well-structured steps.
    Incorrect. You correctly identified the first step, but remember to consider the chain rule when differentiating the inner function.
    Incorrect. It appears there might be a misunderstanding of the relationship between velocity and acceleration in this context. Review the definition of instantaneous acceleration.
    """

    try:
        chat_completion = await client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful AI assistant that grades free response answers. Your response must strictly follow the format: 'Correct!' or 'Incorrect!' followed by a descriptive feedback message."
                },
                {
                    "role": "user",
                    "content": grading_prompt
                }
            ],
            model=config.GROQ_DEFAULT_MODEL,
            temperature=0.1,
        )
        
        response_content = chat_completion.choices[0].message.content.strip()
        
        log.debug(f"Raw Groq FRQ grading response (first word assessment): {response_content}")
        return {"feedback": response_content}

    except Exception as e:
        log.error(f"Error grading FRQ answer with Groq: {e}", exc_info=True)
        return {"feedback": "An unexpected error occurred while grading your answer. Please try again."}