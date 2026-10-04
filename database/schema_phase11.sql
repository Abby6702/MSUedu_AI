USE msuedu_ai;

CREATE TABLE IF NOT EXISTS topics (
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  subject_id INT UNSIGNED NOT NULL,
  name       VARCHAR(100) NOT NULL,
  level      TINYINT UNSIGNED NOT NULL,        -- 1 = beginner ... 4
  position   TINYINT UNSIGNED NOT NULL,        -- order inside the level
  is_active  TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_topic (subject_id, name),
  KEY idx_topic_order (subject_id, level, position),
  CONSTRAINT fk_topic_subject FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS lessons (
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  topic_id   INT UNSIGNED NOT NULL,
  title      VARCHAR(150) NOT NULL,
  body       TEXT NOT NULL,
  difficulty ENUM('easy','medium','hard') NOT NULL DEFAULT 'easy',
  minutes    TINYINT UNSIGNED NOT NULL DEFAULT 5,
  is_active  TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_lesson (topic_id, title),
  CONSTRAINT fk_lesson_topic FOREIGN KEY (topic_id) REFERENCES topics (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- One row per (student, lesson) completed. The primary key stops duplicates.
CREATE TABLE IF NOT EXISTS lesson_progress (
  user_id      INT UNSIGNED NOT NULL,
  lesson_id    INT UNSIGNED NOT NULL,
  completed_at DATETIME NOT NULL,              -- UTC
  PRIMARY KEY (user_id, lesson_id),
  KEY idx_lp_user_time (user_id, completed_at),
  CONSTRAINT fk_lp_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT fk_lp_lesson FOREIGN KEY (lesson_id) REFERENCES lessons (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------- Sample curriculum: Python Programming (safe to run twice) ----------
INSERT IGNORE INTO subjects (name, category) VALUES ('Python Programming', 'Computing');

INSERT IGNORE INTO topics (subject_id, name, level, position) SELECT id, 'Variables', 1, 1 FROM subjects WHERE name = 'Python Programming';
INSERT IGNORE INTO topics (subject_id, name, level, position) SELECT id, 'Data Types', 1, 2 FROM subjects WHERE name = 'Python Programming';
INSERT IGNORE INTO topics (subject_id, name, level, position) SELECT id, 'Input and Output', 1, 3 FROM subjects WHERE name = 'Python Programming';
INSERT IGNORE INTO topics (subject_id, name, level, position) SELECT id, 'If and Else', 2, 1 FROM subjects WHERE name = 'Python Programming';
INSERT IGNORE INTO topics (subject_id, name, level, position) SELECT id, 'Loops', 2, 2 FROM subjects WHERE name = 'Python Programming';
INSERT IGNORE INTO topics (subject_id, name, level, position) SELECT id, 'Functions', 3, 1 FROM subjects WHERE name = 'Python Programming';
INSERT IGNORE INTO topics (subject_id, name, level, position) SELECT id, 'Lists', 3, 2 FROM subjects WHERE name = 'Python Programming';
INSERT IGNORE INTO topics (subject_id, name, level, position) SELECT id, 'Dictionaries', 3, 3 FROM subjects WHERE name = 'Python Programming';

INSERT IGNORE INTO lessons (topic_id, title, body, difficulty, minutes)
SELECT t.id, 'Variables: naming and storing values', 'A variable is a name that points to a value.

age = 17
name = "Ana"

Use the = sign to store a value. Choose clear lowercase names such as total_score. A variable can be changed later:

age = 18

Try it: make a variable called city, then show it with print(city).', 'easy', 5
FROM topics t JOIN subjects s ON s.id = t.subject_id WHERE s.name = 'Python Programming' AND t.name = 'Variables';

INSERT IGNORE INTO lessons (topic_id, title, body, difficulty, minutes)
SELECT t.id, 'Data types: numbers, text and true/false', 'Every value has a type.

age = 17          (int: a whole number)
price = 12.5      (float: a number with a decimal point)
name = "Ana"      (str: text, written in quotes)
is_student = True (bool: True or False)

type(age) tells you the type of a value. The + sign adds numbers but joins text: "Hi " + "Ana" gives "Hi Ana".

Try it: what does type(3.0) show?', 'easy', 5
FROM topics t JOIN subjects s ON s.id = t.subject_id WHERE s.name = 'Python Programming' AND t.name = 'Data Types';

INSERT IGNORE INTO lessons (topic_id, title, body, difficulty, minutes)
SELECT t.id, 'Input and output with print and input', 'print() shows something on the screen. input() asks the user to type something.

name = input("Your name: ")
print("Hello, " + name)

input() always gives back text. To do maths, convert it first:

age = int(input("Your age: "))
print(age + 1)

Try it: ask for two numbers and print their sum.', 'easy', 6
FROM topics t JOIN subjects s ON s.id = t.subject_id WHERE s.name = 'Python Programming' AND t.name = 'Input and Output';

INSERT IGNORE INTO lessons (topic_id, title, body, difficulty, minutes)
SELECT t.id, 'Making decisions with if, elif and else', 'A program can choose what to do.

score = 75
if score >= 90:
    print("Excellent")
elif score >= 60:
    print("Passed")
else:
    print("Try again")

Python checks the conditions from top to bottom and runs only the first block that is true. The indented lines belong to the condition above them. Comparison signs: == equal, != not equal, <, >, <=, >=.

Try it: write a program that says whether a number is positive, negative or zero.', 'easy', 7
FROM topics t JOIN subjects s ON s.id = t.subject_id WHERE s.name = 'Python Programming' AND t.name = 'If and Else';

INSERT IGNORE INTO lessons (topic_id, title, body, difficulty, minutes)
SELECT t.id, 'Repeating work with for and while loops', 'A loop repeats code.

for i in range(3):
    print(i)

This prints 0, 1, 2. range(3) gives the numbers 0 up to (but not including) 3.

count = 0
while count < 3:
    print(count)
    count = count + 1

A while loop runs as long as its condition is true. Make sure something inside the loop changes the condition, or it never stops.

Try it: print the numbers 1 to 5 using a for loop.', 'medium', 8
FROM topics t JOIN subjects s ON s.id = t.subject_id WHERE s.name = 'Python Programming' AND t.name = 'Loops';

INSERT IGNORE INTO lessons (topic_id, title, body, difficulty, minutes)
SELECT t.id, 'Functions: reusable blocks of code', 'A function is a named block of code you can use again.

def greet(name):
    return "Hello, " + name

message = greet("Ana")
print(message)

def starts a function. The names in brackets are parameters (the inputs). return sends a result back. A function does nothing until you call it, like greet("Ana").

Try it: write a function add(a, b) that returns a + b.', 'medium', 8
FROM topics t JOIN subjects s ON s.id = t.subject_id WHERE s.name = 'Python Programming' AND t.name = 'Functions';

INSERT IGNORE INTO lessons (topic_id, title, body, difficulty, minutes)
SELECT t.id, 'Lists: storing many values', 'A list keeps several values in order.

fruits = ["apple", "banana", "mango"]
print(fruits[0])
fruits.append("grape")
print(len(fruits))

Positions start at 0, so fruits[0] is "apple". append() adds an item and len() counts the items. You can loop over a list:

for fruit in fruits:
    print(fruit)

Try it: make a list of three numbers and print their total.', 'medium', 8
FROM topics t JOIN subjects s ON s.id = t.subject_id WHERE s.name = 'Python Programming' AND t.name = 'Lists';

INSERT IGNORE INTO lessons (topic_id, title, body, difficulty, minutes)
SELECT t.id, 'Dictionaries: values with labels', 'A dictionary stores pairs of a key and a value.

student = {"name": "Ana", "age": 17}
print(student["name"])
student["grade"] = "A"

Use the key in square brackets to read or change a value. Assigning to a new key adds it. You can loop over the pairs:

for key, value in student.items():
    print(key, value)

Try it: make a dictionary about a book with a title and an author, then print both.', 'medium', 8
FROM topics t JOIN subjects s ON s.id = t.subject_id WHERE s.name = 'Python Programming' AND t.name = 'Dictionaries';