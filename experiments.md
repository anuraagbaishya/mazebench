# Mazebench

## Question

Can current multimodal models read a maze from an image well enough to solve it, and where does the failure happen when they cannot: in reading the image, in planning a route, or in both? The experiments separate the two abilities. Describing a maze isolates perception. Solving a maze needs perception and planning together. Changing the input to text, or adding a navigation tool, tests whether perception is the bottleneck.

## Maze set

- 100 mazes on a 10x10 grid of cells, generated once with a fixed seed and used for every experiment.
- Each maze has exactly one shortest route from start to goal. 85 of the 100 also contain loops, so longer alternative routes exist and a model can solve a maze without finding the shortest route. 15 are perfect mazes with a single route.
- The entry is a gap in the outer wall, with 25 mazes entered from each side. The goal is a random cell anywhere in the grid, including corners, edges and the centre.
- Image rendering: the start cell is filled green and the goal cell red, thick black lines are walls, thin gray lines mark the cell grid. The images are 640x640 pixels.
- The true layout, start, goal and shortest path of every maze are stored as the answer key. Cells are addressed `(row, col)` from the top left.

## Step 1: model selection

The candidate pool is models on OpenRouter that accept image input, were added in the last 6 months, have a fixed price, and come from well-known providers. From the pool:

- Only the newest version of each model line within a provider is considered. A cheaper tier that has not been updated to the provider's latest generation is still the latest model of that tier.
- One model per provider, the cheapest when a provider has several, so the set covers many providers instead of many sizes of one provider. Two kinds of exception are kept alongside the cheapest model of their provider: a model for which a full set of descriptions already exists, and a provider's frontier model when the provider has no cheap tier of that generation.
- At most 15 models in total. A router model with no fixed price is included with its cost left blank, since its cost depends on what it routes to.

The selected models are listed in `models_last_6_months.csv` with release date, price per million input and output tokens, context length and whether they support reasoning.

## Step 2: describing 20 mazes

**What is tested.** Whether a model can read the maze image accurately, independent of any route planning.

**Task.** The model sees one maze image and is told not to solve it. It reports the start cell, the goal cell, and for every pair of neighbouring cells whether a wall separates them. Walls are reported as two grids of 0/1 characters: `right_walls` (10 rows of 9, the wall between a cell and its right neighbour) and `down_walls` (9 rows of 10, the wall between a cell and the cell below). That covers all 180 gaps in the grid. The outer border is not reported. The answer is one JSON object.

**Sample.** The first 20 mazes (`maze_001` to `maze_020`), the same 20 for every model, so scores are directly comparable. Each model sees each maze once with an identical prompt.

**Measures**, each computed against the answer key:

| Measure | Definition |
|---|---|
| start / goal correct | the reported cell is exactly right |
| wall edge accuracy | share of the 180 gaps reported correctly |
| wall recall | share of real walls that were reported |
| wall precision | share of reported walls that are real |
| exact | all 180 gaps correct |

Missing or malformed parts of an answer count as wrong. Only about 36% of the gaps contain walls, so a model that reports no walls at all scores about 63% edge accuracy. That is the baseline for edge accuracy, and recall and precision must be read alongside it, since a high edge accuracy can come from reporting too few walls.

**Reasoning effort.** Reasoning models are run at the provider's default effort, with no cap on response length. The exception is a model that at its default effort reasons until the provider's token limit without ever producing an answer; it runs at low effort. A call that fails because of a connection or provider error is retried and is not counted against the model; a reply that completes without a parseable description is counted as a failure.

**Ranking.** Models are ranked by mean wall edge accuracy over the 20 mazes, with the number of exact descriptions as the tie-break. Per-model start and goal accuracy, recall and precision are reported alongside.

## Step 3: describing all 100 mazes

The 5 highest-ranked models from step 2 repeat the description task on all 100 mazes. 20 mazes is enough to separate strong from weak readers but gives noisy estimates for models that are close, so the larger sample settles the ordering among the best models and shows how accuracy varies with entry side and goal position. A model with a complete set of descriptions already available is evaluated with the same measures. The ranking from this step selects the models for step 4 and for steps 5 and 6.

## Step 4: solving the mazes

**What is tested.** Whether models that can read the maze can also plan a route through it.

**Task.** The top-ranked models from step 3 see the maze image and answer with a move string: one letter per move, `U`, `D`, `L` or `R`, from the start cell to the goal. Each move goes to the adjacent cell and is only allowed if no wall lies between the two cells.

**Grading.** The move string is walked through the true maze:

- **Solved:** every move is legal and the path ends on the goal cell. Step 4.1 counts these.
- **Optimal:** solved in the minimum number of moves. Step 4.2 counts these. Since each maze has exactly one shortest route, an optimal answer is that route.
- **Failed:** the path hits a wall, leaves the grid, stops short of the goal, or is not a valid move string.

A failed answer is also walked to the end as if walls were passable, and three things are recorded: the number of walls the path crossed, which moves crossed them, and whether the path still ends on the goal. A path that is wrong by a single wall is then told apart from one that ignores many. A failure is classed as crossing walls while staying in the grid, leaving the grid, or giving no usable answer.

Each model solves all 100 mazes twice, so that run-to-run variation can be measured, and is scored on how many of the 100 mazes fall in each class. Because 85 mazes have loops, solved and optimal differ: a model can reach the goal by a longer detour. For solved mazes the path length is compared with the shortest length.

**Link to step 3.** A model's solving rate is compared with its description accuracy to test whether failures are mostly perception errors. A model that describes walls almost perfectly but fails to solve has a planning problem; a model that describes poorly and fails to solve is limited by reading the image.

## DEFERRED: Step 5: text maze versus image maze

**What is tested.** Whether the image is the limiting factor. The same maze is given as text, which removes the need to read pixels.

**Models.** The next 5 models after the top 5 in the step 2 ranking. These are run on the solving task in two conditions, so the image condition is a control run for these models and not a reuse of step 4:

- **Image:** the maze picture, as in step 4.
- **Text:** the maze as a 21x21 character drawing in which `#` is a wall, a space is open floor, `S` is the start and `G` is the goal. Cells sit at odd row and column positions and the characters between two cells show a wall or an opening. The task, move format and grading are identical.

**Comparison.** For each model, solved and optimal counts in the two conditions over the same mazes. A clear gain from text means reading the image is what blocks the model; no gain means the model cannot plan the route even when the maze is given exactly. Mazes are the same in both conditions, so the comparison is paired per maze.

## DEFERRED: Step 6: navigation tool

**What is tested.** Whether letting a model move through the maze step by step, with feedback, helps it solve a maze it cannot solve in one attempt.

**Models and mazes.** The same 5 models as step 5, on the same mazes.

**Condition.** Instead of one answer containing the whole route, the model is given a tool that moves a marker through the maze one cell at a time (`U`, `D`, `L`, `R`). After each call the tool reports whether the move was blocked, the new position, and the open directions from the current cell, and the model keeps calling it until it reaches the goal or a step limit is hit. Positions and walls come from the true maze, so the tool supplies feedback that the model would otherwise have to infer from the image.

**Grading.** The path actually walked is graded with the same solved and optimal definitions as step 4. The number of tool calls per maze is recorded, since a model can solve by trial and error rather than by planning.

**Comparison.** Solved and optimal counts for the same models with the tool, against their image and text results from step 5. The harness for this step has not been built yet.

## Validity notes

- In steps 2 and 3 each model sees each maze once, so a score is one sample per maze; differences of a point or two between models are within noise at 20 mazes. In step 4 each model solves each maze twice, and the two runs can disagree on individual mazes, so small differences between models need both runs and some caution.
- Prices listed for a model can differ from what it is billed, so costs are taken from the billed amounts.
- A set of descriptions was produced by hand by an agent reading the images, not through the same API pipeline as the other models, with a prompt whose size placeholders were not filled in, and the use of code to read the images cannot be ruled out. It is a reference point and not a like-for-like result.
- A model with a very high reasoning budget may not finish within the provider's limits; those cases are reported as failures to produce an answer, separately from wrong answers.
- Reasoning effort is the provider's default and is not equalised across models, so cost, latency and accuracy include different amounts of reasoning.
- Latency is wall-clock time per request with several requests in flight, through whichever provider OpenRouter chose, so it reflects load as well as the model.
