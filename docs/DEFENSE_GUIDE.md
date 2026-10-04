# Defense Guide

## Project overview

MSUEdu AI is a student tutoring platform that combines learning materials, a generative AI tutor, peer tutoring, and explainable learning recommendations. It is a student project, not an official Mindanao State University website. The application uses Flask, MySQL, Flask-SocketIO, and WebRTC.

## Generative AI and Agentic AI

Generative AI creates content: the tutor explains concepts, summaries condense supplied notes, and quiz generation drafts questions. Generated output can be wrong; quiz data is validated and graded on the server. Tutor-facing AI output remains a draft for the tutor to review.

The Agentic tutoring coordinator interprets a student's request, then selects from a fixed set of checked tools to find subjects, tutors, availability, or existing requests. It can prepare a booking or cancellation, but a student must confirm. Confirmation repeats the conflict checks; the agent cannot accept a request for a tutor.

The learning agent is rule-based, not a trained model. It uses measured quiz attempts and lesson completion to classify progress and choose a recommendation. It does not read AI conversations. Its thresholds are teaching heuristics, not validated research findings. Recommendations include their reasoning so students can understand why an action was suggested.

## 12-step demonstration

1. Start the application with the configured local environment and database.
2. Run `flask --app run init-db` to create or update the schema.
3. Run `flask --app run seed-demo` to load fictional demonstration accounts and learning data.
4. Sign in as a student and inspect the available subjects and lessons.
5. Open a lesson and record its completion.
6. Take a quiz and inspect the server-graded result.
7. Review the learning profile and its rule-based recommendation.
8. Ask the AI tutor a learning question and discuss its response as generated assistance, not guaranteed fact.
9. Ask the tutoring coordinator to find a suitable human tutor or session time.
10. Inspect the proposed booking and explain that no request is created before student confirmation.
11. Sign in as a tutor to review the student request and demonstrate the live-session tools where configured.
12. Close by distinguishing the measured-data learning agent from generative features, and discuss the security and deployment limits in `SECURITY.md` and `DEPLOYMENT.md`.

## Important limitations

Use fictional seed data for demonstrations. Do not present AI output or quiz scores as proof of mastery. A production deployment needs HTTPS, protected production secrets, a configured database and AI provider, persistent upload storage, and a single application worker for the in-memory real-time features. Review `ARCHITECTURE.md`, `SECURITY.md`, and `DEPLOYMENT.md` before describing implementation details or deployment readiness.
