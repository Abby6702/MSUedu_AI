# Architecture

## Big picture
```
Browser (HTML, CSS, JavaScript) --HTTPS--> Flask app --SQL--> MySQL
   |                                          |-- AI client --> Ollama (local) or an OpenAI-compatible API
   |                                          |-- Socket.IO: chat, whiteboard, WebRTC setup messages
   '--- WebRTC: video and audio go browser to browser (never through the server)
```
Only the server talks to the database and to the AI. API keys and the AI's address never reach the browser.

## Layers
| Layer | Where | Rule |
|---|---|---|
| Routes | `app/routes` | Check the role, validate input, call a service, render or return JSON. |
| Services | `app/services` | Business rules and all SQL (always with `%s` parameters). |
| AI | `app/ai`, `ai_service`, `tutor_ai_service` | One client file talks to the provider. Output is validated before use. |
| Real time | `app/sockets.py` | Authenticated sockets, validated and rebuilt messages, rate limits. |
| Pure logic | `*_logic.py`, `learning_agent.py`, `chart_logic.py`, `live_logic.py` | No database or network, so every rule is unit-tested. |

## Generative AI in this project
| Feature | What the model does | Control |
|---|---|---|
| AI tutor chat | Explains, gives examples and hints (teaching prompt, not answer-giving) | Labelled as possibly wrong. Conversations are saved per student, private, deletable. |
| Notes summary | Summarizes only the pasted text | Not saved. |
| Quiz generation | Writes questions as JSON | Validated question by question. Unusable output saves nothing. Grading is server-side. |
| Tutor AI panel | Drafts exercises, explanations, quiz, hints, next-lesson pick | Tutor-only draft. Lesson ids must come from the real list. No student name in the prompt. |
| Summary drafts | Fills the structured summary from the tutor's own notes | The tutor edits, then chooses to share. |

## Agentic AI in this project
### 1. The tutoring coordinator (student)
```
Message --> PLAN (model returns a small JSON form) --> ACT (fixed, checked tools)
        --> EXPLAIN (text built from database results) --> CONFIRM (student presses a button)
```
Six tools (list subjects, find tutors, open slots, my requests, prepare request, prepare cancel). Every call
checks the tool name, the role and each argument. The user id comes from the login. Open times are computed
from weekly availability minus confirmed sessions. Nothing is created until **Confirm**, which re-runs every
conflict check. It can never accept a request for a tutor.

### 2. The learning agent (rule-based)
```
Student activity -> collect measured data -> analyse (average, latest, trend) -> classify strong / developing / weak
   -> select action (rules) -> create recommendation with saved reasoning -> notify and update the learning path
```
| Rule | Condition | Action |
|---|---|---|
| R1 | Weak or developing topic, lessons not all finished | Review the next unfinished lesson |
| R2 | Lessons finished, results still low | More practice; difficulty from the latest score |
| R4 | Last 3 quizzes below 60% after the review (or 5 without it) | Suggest a human student tutor |
| Next | No weak topic in a started subject | Next lesson on the path |

It decides only from **measured events** (quiz attempts, lesson completions). It never reads AI chats, and tutor
summaries are shown beside its advice but never feed its rules. **Honest point for examiners:** this agent has no
learned model. It is "agentic" because it observes, decides toward a goal, acts (recommendations, notifications)
and explains itself within guardrails. Its thresholds are teaching heuristics, not validated research values.

## Human-AI collaboration
AI explains, generates and recommends. Humans decide: students confirm bookings, tutors review every AI draft
before anyone else sees it, and administrators approve tutors and curriculum.

## Data model (30 tables)
Accounts: `users`, `student_profiles`, `tutor_profiles`, `audit_logs`, `login_attempts`, `platform_settings` ·
Tutoring: `subjects`, `tutor_subjects`, `tutor_availability`, `tutoring_requests`, `session_messages`,
`session_files`, `session_records`, `session_summaries`, `feedback` · Learning: `topics`, `lessons`,
`lesson_progress`, `quizzes`, `quiz_questions`, `quiz_attempts`, `quiz_answers`, `recommendations` ·
AI: `ai_conversations`, `ai_messages`, `ai_usage_logs`, `agent_proposals`, `agent_action_logs` ·
Notifications: `notifications`, `notification_preferences`.
A booking is the session (one table). Content is hidden, never deleted, so measured history stays valid.

## Real-time design
Rooms, chat relay and whiteboards live in one process's memory, so the server runs **one worker**. The whiteboard
keeps its state only while the room is open. Video goes directly between browsers; the server relays only small,
validated setup messages. Chat text is saved. Files are stored outside `static/` and served after a permission check.