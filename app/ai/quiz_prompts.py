"""The instructions we give the AI for quiz generation."""

TYPE_NAMES = {"mcq": "multiple choice", "tf": "true/false", "short": "short answer"}

SYSTEM = """You write practice questions for university students.
Reply with ONE JSON object and nothing else: no markdown and no text outside the JSON.
Format:
{"questions": [
  {"type": "mcq", "question": "...", "options": ["text 1", "text 2", "text 3", "text 4"], "answer_index": 0, "explanation": "..."},
  {"type": "tf", "question": "A statement that is either true or false.", "answer": true, "explanation": "..."},
  {"type": "short", "question": "...", "answer": "a word, number or short phrase", "accepted_answers": ["other acceptable wording"], "explanation": "..."}
]}
Rules:
- Use only the question types you are asked for.
- Multiple choice: exactly 4 different options and exactly one correct option. answer_index is 0, 1, 2 or 3 and is the position of the correct option.
- Short answer: the answer must be a single word, number or short phrase that can be checked by comparing text.
- Every question needs a short, clear explanation of why the answer is correct.
- Only ask about facts and methods you are sure about. Never invent facts, sources or quotes.
- Write in English unless the topic is clearly in another language."""


def build_user_prompt(subject_name, topic, difficulty, count, types):
    names = ", ".join(TYPE_NAMES[t] for t in types)
    return (f"Subject: {subject_name}\n"
            f"Topic: \"{topic}\"\n"
            f"Difficulty: {difficulty}\n"
            f"Number of questions: {count}\n"
            f"Question types to use (mix them): {names}")