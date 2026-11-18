USE msuedu_ai;

-- Starter curriculum for every built-in subject. INSERT IGNORE keeps this safe to rerun.
INSERT IGNORE INTO topics (subject_id, name, level, position)
SELECT s.id, curriculum.topic_name, curriculum.curriculum_level, curriculum.topic_position
FROM subjects s
JOIN (
  SELECT 'College Algebra' AS subject_name, 'Expressions and Real Numbers' AS topic_name, 1 AS curriculum_level, 1 AS topic_position
  UNION ALL SELECT 'College Algebra', 'Linear Equations and Inequalities', 1, 2
  UNION ALL SELECT 'College Algebra', 'Functions and Graphs', 2, 1
  UNION ALL SELECT 'Calculus 1', 'Functions and Limits', 1, 1
  UNION ALL SELECT 'Calculus 1', 'Limits and Continuity', 1, 2
  UNION ALL SELECT 'Calculus 1', 'Derivatives', 2, 1
  UNION ALL SELECT 'Calculus 1', 'Derivatives:', 2, 2
  UNION ALL SELECT 'Calculus 1', 'Applications of Derivatives', 3, 1
  UNION ALL SELECT 'Calculus 1', 'Integrals', 3, 1
  UNION ALL SELECT 'Statistics', 'Describing Data', 1, 1
  UNION ALL SELECT 'Statistics', 'Probability', 2, 1
  UNION ALL SELECT 'Statistics', 'Sampling and Inference', 3, 1
  UNION ALL SELECT 'General Physics', 'Motion and Vectors', 1, 1
  UNION ALL SELECT 'General Physics', 'Forces and Newton''s Laws', 2, 1
  UNION ALL SELECT 'General Physics', 'Work, Energy and Momentum', 3, 1
  UNION ALL SELECT 'General Chemistry', 'Atoms and Periodic Trends', 1, 1
  UNION ALL SELECT 'General Chemistry', 'Bonding and Molecular Structure', 2, 1
  UNION ALL SELECT 'General Chemistry', 'Chemical Reactions and Stoichiometry', 3, 1
  UNION ALL SELECT 'Programming Fundamentals', 'Algorithms and Pseudocode', 1, 1
  UNION ALL SELECT 'Programming Fundamentals', 'Variables and Control Flow', 2, 1
  UNION ALL SELECT 'Programming Fundamentals', 'Functions and Testing', 3, 1
  UNION ALL SELECT 'Data Structures', 'Arrays and Linked Lists', 1, 1
  UNION ALL SELECT 'Data Structures', 'Stacks and Queues', 2, 1
  UNION ALL SELECT 'Data Structures', 'Trees and Hash Tables', 3, 1
  UNION ALL SELECT 'English Composition', 'Purpose and Audience', 1, 1
  UNION ALL SELECT 'English Composition', 'Paragraphs and Evidence', 2, 1
  UNION ALL SELECT 'English Composition', 'Drafting and Revision', 3, 1
  UNION ALL SELECT 'Python Programming', 'Modules and Imports', 4, 1
  UNION ALL SELECT 'Python Programming', 'Files and Data', 4, 2
  UNION ALL SELECT 'Python Programming', 'Errors and Exceptions', 4, 3
) AS curriculum ON curriculum.subject_name = s.name;

INSERT IGNORE INTO lessons (topic_id, title, body, difficulty, minutes)
SELECT t.id, curriculum.lesson_title, curriculum.lesson_body, 'easy', curriculum.minutes
FROM topics t
JOIN subjects s ON s.id = t.subject_id
JOIN (
  SELECT 'College Algebra' AS subject_name, 'Expressions and Real Numbers' AS topic_name,
         'An expression combines numbers, variables and operations. In 3x + 5, x is a variable, 3 is its coefficient and 5 is a constant. Like terms have the same variable part: 2x + 4x = 6x. Use the distributive property to expand 3(x + 2) as 3x + 6. Real numbers include rational numbers, such as 1/2, and irrational numbers, such as square root of 2. Try it: simplify 4a + 3 - 2a + 5.' AS lesson_body,
         'Expressions and Real Numbers: simplify and evaluate' AS lesson_title, 7 AS minutes
  UNION ALL SELECT 'College Algebra', 'Linear Equations and Inequalities',
         'An equation says two expressions have equal values. To solve 2x + 3 = 11, subtract 3 from both sides, then divide by 2, giving x = 4. Whatever operation you apply to one side must also be applied to the other. Inequalities use <, >, <= or >=; multiplying or dividing both sides by a negative number reverses the inequality sign. Try it: solve 3x - 4 = 14, then write the solutions to x + 2 < 7.'
         , 'Linear Equations: solve and check', 8
  UNION ALL SELECT 'College Algebra', 'Functions and Graphs',
         'A function assigns exactly one output to each allowed input. In f(x) = 2x + 1, f(3) = 7. The input values form the domain and possible outputs form the range. A graph displays input-output pairs as points (x, f(x)); a straight-line function has a constant rate of change. Try it: make a table for f(x) = x + 2 when x is -1, 0 and 2, then plot the points.'
         , 'Functions: inputs, outputs and graphs', 8
  UNION ALL SELECT 'Calculus 1', 'Functions and Limits',
         'A limit describes the value a function approaches as its input gets close to a number. For f(x) = x + 2, as x approaches 3, f(x) approaches 5. When a function is continuous at that point, direct substitution often finds the limit. A limit can still exist when the function value is missing or different at that point. Try it: estimate the limit of x squared as x approaches 2 by evaluating nearby inputs.'
         , 'Limits: approach and continuity', 8
  UNION ALL SELECT 'Calculus 1', 'Limits and Continuity',
         'A function is continuous at x = a when f(a) exists, the limit as x approaches a exists, and that limit equals f(a). For example, polynomials are continuous for every real input. A removable discontinuity is a hole; a jump has different one-sided limits; a vertical asymptote can indicate an unbounded limit. To check a limit at a point, compare the left-hand and right-hand behavior. Try it: for f(x) = (x squared - 1)/(x - 1), simplify for x not equal to 1 and find the limit as x approaches 1. Is f continuous at 1 if its value is not defined there?'
         , 'Continuity: limits and types of discontinuity', 9
  UNION ALL SELECT 'Calculus 1', 'Derivatives',
         'The derivative measures an instantaneous rate of change and the slope of a curve at a point. For f(x) = x squared, the power rule gives f''(x) = 2x, so the slope at x = 3 is 6. A derivative can describe speed when position changes over time. Check that the power rule turns x to the n into n times x to the (n - 1). Try it: find the derivative of 3x squared + 4x.'
         , 'Derivatives: rate of change and the power rule', 9
  UNION ALL SELECT 'Calculus 1', 'Derivatives:',
         'The derivative at x = a is the limit of the average rate of change over a smaller and smaller interval: f''(a) = lim as h approaches 0 of [f(a + h) - f(a)]/h. It is the slope of the tangent line when this limit exists. For f(x) = x squared, the difference quotient simplifies to 2a + h, so the limit is 2a. This definition explains what a derivative means before using shortcut rules. Try it: use the definition to find the derivative of f(x) = 3x at x = 2.'
         , 'The Derivative: definition and tangent slope', 10
  UNION ALL SELECT 'Calculus 1', 'Applications of Derivatives',
         'Derivatives help describe how a function behaves. Where f''(x) is positive, the function is increasing; where it is negative, the function is decreasing. Candidate local maxima and minima occur at critical points, where the derivative is zero or undefined, and must be checked in context. Derivatives also support optimization when a quantity must be made largest or smallest under constraints. Try it: use the sign of f''(x) = 2x to describe where f(x) = x squared is increasing.'
         , 'Using derivatives to analyze functions', 9
  UNION ALL SELECT 'Calculus 1', 'Integrals',
         'An antiderivative reverses differentiation: if F''(x) = f(x), then F is an antiderivative of f. The indefinite integral includes a constant because derivatives of constants are zero; for example, the integral of 2x is x squared + C. A definite integral accumulates signed area over an interval. The Fundamental Theorem of Calculus connects the two: evaluate an antiderivative at the upper and lower bounds and subtract. Try it: find an antiderivative of 3x squared, then check by differentiating your answer.'
         , 'Integrals: antiderivatives and accumulation', 10
  UNION ALL SELECT 'Statistics', 'Describing Data',
         'Statistics summarizes data so patterns are easier to see. The mean is the sum divided by the number of values; the median is the middle value after sorting. The range is maximum minus minimum. A histogram shows how often values fall into intervals, while a bar chart compares categories. Outliers can shift the mean more than the median. Try it: for 2, 3, 3, 4 and 18, find the mean and median and compare them.'
         , 'Descriptive Statistics: center and spread', 8
  UNION ALL SELECT 'Statistics', 'Probability',
         'Probability measures how likely an event is, from 0 (impossible) to 1 (certain). If outcomes are equally likely, probability is the number of favorable outcomes divided by the total number of outcomes. For a fair six-sided die, the probability of rolling an even number is 3/6, or 1/2. For independent events, multiply their probabilities to find the chance both occur. Try it: find the probability of drawing a heart from a standard 52-card deck.'
         , 'Probability: events and simple models', 8
  UNION ALL SELECT 'Statistics', 'Sampling and Inference',
         'A sample is a subset used to learn about a larger population. Random selection helps reduce bias, and a larger well-chosen sample generally gives more precise estimates. A confidence interval expresses a range of plausible values for a population quantity under a method with a stated long-run coverage rate. Statistical evidence describes uncertainty; it does not prove a claim with certainty. Try it: explain why asking only one classroom about campus-wide study habits may produce a biased sample.'
         , 'Sampling: representativeness and uncertainty', 9
  UNION ALL SELECT 'General Physics', 'Motion and Vectors',
         'Position tells where an object is; displacement describes its change in position. Average velocity is displacement divided by elapsed time, while speed uses total distance. Vectors have both size and direction, so a direction such as east matters. With constant acceleration, velocity changes by the same amount each second. Try it: a student walks 12 m east, then 5 m west. Find the total distance and the displacement, including direction.'
         , 'Motion: distance, displacement and velocity', 8
  UNION ALL SELECT 'General Physics', 'Forces and Newton''s Laws',
         'A force is an interaction that can change motion. Newton''s first law describes inertia: without a net external force, velocity stays constant. The second law relates net force, mass and acceleration with F = ma. The third law says interacting objects exert equal and opposite forces on each other; these forces act on different objects. Try it: find the acceleration of a 2 kg cart pushed by a net force of 6 N.'
         , 'Forces: Newton''s laws', 9
  UNION ALL SELECT 'General Physics', 'Work, Energy and Momentum',
         'Work transfers energy when a force causes displacement in its direction. Kinetic energy is energy of motion, given by one-half mass times speed squared. Momentum is mass times velocity. In an isolated system, total energy and total momentum are conserved, though energy may change form. Try it: compare the kinetic energy of the same object moving at 2 m/s and 4 m/s; consider how squaring speed changes the result.'
         , 'Energy and Momentum: conservation ideas', 9
  UNION ALL SELECT 'General Chemistry', 'Atoms and Periodic Trends',
         'Atoms contain protons and neutrons in a nucleus, with electrons around it. The atomic number equals the number of protons and identifies the element. In a neutral atom, electrons equal protons. The periodic table arranges elements by atomic number; elements in a column often have similar chemical behavior because of their outer electrons. Try it: use a periodic table to find the number of protons in carbon and explain why two carbon atoms are the same element even if their neutron counts differ.'
         , 'Atomic Structure: particles and the periodic table', 9
  UNION ALL SELECT 'General Chemistry', 'Bonding and Molecular Structure',
         'Ionic bonding involves attraction between oppositely charged ions, often formed when electrons transfer. Covalent bonding involves atoms sharing electron pairs. A molecule''s shape affects how its bonds are arranged in space and can influence its properties. A chemical formula shows the types and counts of atoms, not the complete shape. Try it: compare the formulas NaCl and H2O and describe what each formula tells you about its particles.'
         , 'Chemical Bonds: ionic and covalent models', 9
  UNION ALL SELECT 'General Chemistry', 'Chemical Reactions and Stoichiometry',
         'A chemical reaction rearranges atoms; it does not create or destroy them. A balanced equation has the same number of each kind of atom on both sides. Coefficients show relative amounts in moles and support stoichiometric calculations. For 2H2 + O2 -> 2H2O, two moles of hydrogen react with one mole of oxygen to form two moles of water. Try it: count hydrogen and oxygen atoms on each side of this equation.'
         , 'Reactions: balancing and mole ratios', 9
  UNION ALL SELECT 'Programming Fundamentals', 'Algorithms and Pseudocode',
         'An algorithm is a finite sequence of clear steps for solving a problem. Before coding, identify the inputs, expected outputs and important cases. Pseudocode expresses logic in plain, structured language without requiring a specific programming syntax. A trace table can follow variable values step by step and reveal mistakes. Try it: write pseudocode that accepts two numbers and outputs the larger one, including what happens if they are equal.'
         , 'Problem Solving: algorithms and pseudocode', 8
  UNION ALL SELECT 'Programming Fundamentals', 'Variables and Control Flow',
         'A variable gives a name to stored data, and its type determines what operations make sense. A sequence runs instructions in order; a selection chooses a path using a condition; iteration repeats steps. Conditions evaluate to true or false. Keep each branch understandable and ensure loops make progress toward stopping. Try it: describe an algorithm that counts from 1 to 5 and then reports whether each number is even or odd.'
         , 'Control Flow: sequence, selection and iteration', 9
  UNION ALL SELECT 'Programming Fundamentals', 'Functions and Testing',
         'A function packages a task behind a name, inputs and (when needed) a returned result. Small functions are easier to understand and test. A test supplies a known input and checks whether the output matches an expected result. Include ordinary cases and boundary cases, such as zero or an empty collection. Try it: specify two tests for a function that returns the larger of two numbers, including a tie.'
         , 'Functions: decomposition and tests', 8
  UNION ALL SELECT 'Data Structures', 'Arrays and Linked Lists',
         'An array stores elements in indexed positions and usually supports fast access by index. Inserting into the middle may require shifting later elements. A linked list stores nodes that refer to the next node; inserting after a known node can be quick, but reaching an item may require following links from the beginning. Choose based on the operations an application needs. Try it: decide which structure fits frequent random lookups and which may suit frequent insertions after a known position.'
         , 'Sequences: arrays and linked lists', 9
  UNION ALL SELECT 'Data Structures', 'Stacks and Queues',
         'A stack uses last-in, first-out order: the most recently added item is removed first. A queue uses first-in, first-out order: the earliest item is removed first. Stacks are useful for undo history and nested operations; queues are useful for waiting work. Common operations include push and pop for stacks, and enqueue and dequeue for queues. Try it: write the removal order when A, B and C are added to a stack and then to a queue.'
         , 'Stacks and Queues: ordering operations', 8
  UNION ALL SELECT 'Data Structures', 'Trees and Hash Tables',
         'A tree connects values in a hierarchy. In a binary search tree, values smaller than a node are stored to its left and larger values to its right, enabling efficient search when the tree stays balanced. A hash table uses a hash function to map keys to storage locations; collisions need a handling strategy. Performance depends on data and implementation. Try it: sketch a search tree for 8, 3 and 10, then trace a search for 10.'
         , 'Trees and Hash Tables: organizing and searching data', 9
  UNION ALL SELECT 'English Composition', 'Purpose and Audience',
         'Effective writing begins with a purpose and a reader. A thesis states the central claim or focus, while audience knowledge helps determine tone, context and which terms need explanation. A focused question can keep a draft from becoming too broad. Claims should be specific enough to support with reasons and evidence. Try it: write one sentence stating a claim about a campus topic and identify one intended reader who might need extra context.'
         , 'Writing: purpose, audience and thesis', 8
  UNION ALL SELECT 'English Composition', 'Paragraphs and Evidence',
         'A focused paragraph develops one main point. A topic sentence signals that point, evidence supports it, and explanation shows how the evidence connects to the claim. Quotations need accurate attribution and context; paraphrases should restate ideas genuinely in your own words and still cite their sources. Try it: choose a claim, name one kind of evidence that could support it, and write a sentence explaining why that evidence is relevant.'
         , 'Writing with evidence: claims and paragraphs', 9
  UNION ALL SELECT 'English Composition', 'Drafting and Revision',
         'Drafting helps develop ideas; revision improves the argument, organization and clarity. Read for larger issues first, such as whether each section supports the thesis, then edit sentences and proofread mechanics. Feedback is most useful when it names a specific reader question or confusing passage. Keep track of sources while drafting to avoid accidental omissions. Try it: revise a paragraph by identifying its main point, removing one unrelated sentence and checking that evidence is explained.'
         , 'Revision: structure, clarity and proofreading', 9
  UNION ALL SELECT 'Python Programming', 'Modules and Imports',
         'A module is a Python file whose definitions can be reused elsewhere. The import statement makes module contents available, such as import math followed by math.sqrt(9). Keep related functions together and use clear names. A script guarded by if __name__ == "__main__": can be imported without automatically running its main program. Try it: import the math module and use math.sqrt to find the square root of 81.'
         , 'Modules: reuse code with imports', 8
  UNION ALL SELECT 'Python Programming', 'Files and Data',
         'Use open() to work with a file, and prefer a with block so it closes the file even if an error occurs. The mode "r" reads, "w" replaces contents and "a" appends. Text files can be read line by line; structured formats such as JSON represent common data types. Handle file paths and decoding carefully. Try it: write pseudocode for opening a text file, reading its lines and counting them.'
         , 'Files: reading and writing safely', 8
  UNION ALL SELECT 'Python Programming', 'Errors and Exceptions',
         'An exception signals that an operation could not proceed normally. Use try and except to handle specific expected problems, such as a ValueError while converting user input. Avoid catching every exception without a plan, because it can hide programming mistakes. A clear error message helps users recover; finally can run cleanup whether an error occurred or not. Try it: outline how to ask for a number again when input cannot be converted to an integer.'
         , 'Exceptions: handling expected errors', 9
) AS curriculum ON curriculum.subject_name = s.name AND curriculum.topic_name = t.name
WHERE t.subject_id = s.id;
