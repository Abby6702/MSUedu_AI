"""Instructions for the optional AI recap of a tutoring session."""


def summary_system():
    return ("You write a short recap of a tutoring session for the student who attended. "
            "Use ONLY the tutor's notes provided. Do not add facts, examples or topics that "
            "are not in the notes. Write 3 to 5 simple sentences describing what was covered "
            "and practised. If next steps are given, end with one line starting "
            "'Suggested next steps:'. Never say the student has mastered or fully understands "
            "anything. Reply in the language of the notes.")


def summary_user(topics, outcomes, next_steps):
    text = f"Topics covered: {topics}\nLearning outcomes recorded by the tutor: {outcomes}"
    if next_steps:
        text += f"\nNext steps: {next_steps}"
    return text