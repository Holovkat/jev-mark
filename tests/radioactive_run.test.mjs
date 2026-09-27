import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.join(here, "..", "Resources", "Web", "index.html"), "utf8");
const startMarker = "// RADIOACTIVE-RUN-CORE-START";
const endMarker = "// RADIOACTIVE-RUN-CORE-END";
const start = html.indexOf(startMarker);
const end = html.indexOf(endMarker);
assert.ok(start >= 0 && end > start, "core markers not found in index.html");
const core = html.slice(start + startMarker.length, end);

const names = [
  "GRID_DIRECTIONS", "gridKey", "RR_ROWS", "RR_COLUMN_OPTIONS", "RR_DEFAULT_COLUMNS", "RR_START_ROW",
  "rrMulberry32", "rrNormalizeSeed", "rrGenerateBoard", "rrValidateGrid", "rrShortestPath",
  "rrLegalMoves", "rrMoveBudget", "rrCreateRunState", "rrObserve", "rrApplyMove",
  "RR_MEMORY_AIDS",
  "rrMoveFacts", "rrMoveFactText", "rrMoveInstructions",
  "rrRenderKnownMap", "rrBuildMoveContext", "rrMoveCriteria", "rrSummarizeRun", "rrParseMoveValue",
  "rrRecordDecision", "RR_RED_VISITS",
];
const script = `${core}\n;globalThis.__rr = { ${names.join(", ")} };`;
const context = vm.createContext({ Math });
vm.runInContext(script, context);
const rr = context.__rr;

function countWalls(row) {
  return [...row].filter((cell) => cell === "#").length;
}

function boardLooksValid(board) {
  assert.equal(board.wallRows.length, rr.RR_ROWS);
  assert.equal(rr.rrValidateGrid(board.wallRows, board.columns, board.rows), null);
  assert.equal(board.wallRows[rr.RR_START_ROW][0], ".");
  assert.ok(board.wallRows.every((row) => row[row.length - 1] === "."));
  assert.ok(board.shortestPath > 0);
}

test("1. same seed gives identical board, different seeds differ", () => {
  const a = rr.rrGenerateBoard({ seed: 12345, columns: 60 });
  const b = rr.rrGenerateBoard({ seed: 12345, columns: 60 });
  const c = rr.rrGenerateBoard({ seed: 12346, columns: 60 });
  assert.deepEqual(a, b);
  assert.notDeepEqual(a.wallRows, c.wallRows);
  boardLooksValid(a);
  const text = rr.rrGenerateBoard({ seed: "hello world", columns: 40 });
  const text2 = rr.rrGenerateBoard({ seed: "hello world", columns: 40 });
  assert.deepEqual(text, text2);
});

test("2. 200 random seeds pass validation at 40/60/80 columns", () => {
  for (let index = 0; index < 200; index++) {
    const seed = Math.floor(Math.random() * 4294967296);
    const columns = rr.RR_COLUMN_OPTIONS[index % rr.RR_COLUMN_OPTIONS.length];
    const board = rr.rrGenerateBoard({ seed, columns });
    boardLooksValid(board);
  }
});

test("3. legal moves include visited, exclude goo and out-of-bounds", () => {
  const board = rr.rrGenerateBoard({ seed: 7, columns: 40 });
  const run = rr.rrCreateRunState(board);
  // Build a guaranteed corridor scenario: start row 10 col 0, up/down/right candidates.
  const moves = rr.rrLegalMoves(board, run.pos);
  for (const move of moves) {
    assert.ok(move.row >= 0 && move.row < board.rows);
    assert.ok(move.col >= 0 && move.col < board.columns);
    assert.notEqual(board.wallRows[move.row][move.col], "#");
  }
  // Revisit: walk back and force a revisit is legal.
  if (moves.length === 1) {
    rr.rrApplyMove(run, board, moves[0], { forced: true });
    const back = rr.rrLegalMoves(board, run.pos);
    assert.ok(back.some((move) => move.row === rr.RR_START_ROW && move.col === 0), "visited start cell must be a legal target");
  } else {
    assert.ok(moves.length >= 2);
    const corner = rr.rrLegalMoves(board, { row: rr.RR_ROWS - 1, col: 0 });
    assert.ok(corner.every((move) => move.row < rr.RR_ROWS));
  }
  // Never a wall target anywhere.
  for (let row = 0; row < board.rows; row++) {
    for (let col = 0; col < board.columns; col++) {
      if (board.wallRows[row][col] === "#") continue;
      for (const move of rr.rrLegalMoves(board, { row, col })) {
        assert.notEqual(board.wallRows[move.row][move.col], "#");
      }
    }
  }
});

test("4. fog of war radius 1, map symbols", () => {
  const board = rr.rrGenerateBoard({ seed: 99, columns: 60 });
  const run = rr.rrCreateRunState(board);
  // Start cell observed neighbourhood: exactly Chebyshev radius 1.
  assert.equal(run.observed[rr.gridKey(rr.RR_START_ROW, 0)], true);
  assert.equal(run.observed[rr.gridKey(rr.RR_START_ROW - 1, 1)], true);
  assert.equal(run.observed[rr.gridKey(rr.RR_START_ROW - 2, 0)], undefined);
  assert.equal(run.visits[rr.gridKey(rr.RR_START_ROW, 0)], 1);
  // Move somewhere and check observation grows.
  const moves = rr.rrLegalMoves(board, run.pos);
  rr.rrApplyMove(run, board, moves[0], { forced: moves.length === 1 });
  assert.equal(run.observed[rr.gridKey(run.pos.row, run.pos.col)], true);
  const map = rr.rrRenderKnownMap(run, board);
  assert.ok(map.includes("@"));
  assert.ok(map.includes("?"));
  assert.ok(map.includes("#"));
  assert.ok(map.includes("E"));
  assert.ok(map.includes("1"));
  assert.match(map, /Legend:/);
});

test("4b. header columns align with row cells and exit marker", () => {
  const board = rr.rrGenerateBoard({ seed: 4242, columns: 60 });
  const run = rr.rrCreateRunState(board);
  const halfWidth = 4; // force a clipped window
  const mapLines = rr.rrRenderKnownMap(run, board, { halfWidth }).split("\n");
  const fromCol = Math.max(0, run.pos.col - halfWidth);
  const toCol = Math.min(board.columns - 1, run.pos.col + halfWidth);
  const tens = mapLines[1];
  const units = mapLines[2];
  const exitLine = toCol === board.columns - 1 ? mapLines[3] : null;
  for (let col = fromCol; col <= toCol; col++) {
    const cellIndex = 3 + (col - fromCol) * 2;
    assert.equal(units[cellIndex], String((col + 1) % 10), `units digit for column ${col + 1}`);
    const expectedTens = col + 1 >= 10 ? String(Math.floor((col + 1) / 10) % 10) : " ";
    assert.equal(tens[cellIndex], expectedTens, `tens digit for column ${col + 1}`);
  }
  assert.ok(fromCol > 0 || toCol < board.columns - 1, "window should be clipped for this check");
  assert.ok(mapLines[0].includes("(clipped)"));
  if (exitLine) {
    assert.equal(exitLine[3 + (toCol - fromCol) * 2], "E");
    assert.equal(exitLine.trim(), "E");
  } else {
    assert.ok(toCol < board.columns - 1, "exit line omitted only when exit is outside the window");
  }
  // With the full board visible (position near exit) the E line appears at the last column.
  const nearExit = { row: rr.RR_START_ROW, col: board.columns - 1 };
  const exitRun = { ...run, pos: nearExit, observed: { ...run.observed, [rr.gridKey(nearExit.row, nearExit.col)]: true }, visits: { ...run.visits, [rr.gridKey(nearExit.row, nearExit.col)]: 1 } };
  const exitMap = rr.rrRenderKnownMap(exitRun, board, { halfWidth: 15 }).split("\n");
  const exitFromCol = Math.max(0, nearExit.col - 15);
  const lastCellIndex = 3 + (board.columns - 1 - exitFromCol) * 2;
  assert.equal(exitMap[3][lastCellIndex], "E");
});

test("5. context bounded at 7000 chars after 1500 moves, no score wording", () => {
  const board = rr.rrGenerateBoard({ seed: 1234, columns: 80 });
  const run = rr.rrCreateRunState(board);
  run.budget = 1000000; // lift budget so the walk can reach 1500 steps
  let guard = 0;
  while (run.steps.length < 1500 && run.status === "running" && guard < 1600) {
    const legal = rr.rrLegalMoves(board, run.pos);
    const pick = legal[Math.floor(Math.random() * legal.length)];
    rr.rrApplyMove(run, board, pick, { forced: legal.length === 1 });
    guard++;
  }
  assert.ok(run.steps.length >= 1000, `only reached ${run.steps.length} steps`);
  const context = rr.rrBuildMoveContext(run, board);
  assert.ok(context.length <= 7000, `context too long: ${context.length}`);
  assert.ok(!/point/i.test(context));
  assert.ok(!/score/i.test(context));
  assert.ok(context.includes("Goal:"));
  assert.ok(context.includes("Legal moves:"));
  assert.ok(context.includes("Recent steps:"));
});

// Hand-built 20x12 board helpers for memory-aid tests.
function stubBoard() {
  // Corridor on row 10 (index 9) with a one-cell stub above at column 3.
  // Row 10 (index 9): "...." repeated; row 9 (index 8): only col 3 open (stub); rest goo.
  const columns = 12;
  const wallRows = [];
  for (let row = 0; row < rr.RR_ROWS; row++) {
    wallRows.push([..."#".repeat(columns)]);
  }
  for (let col = 0; col < columns; col++) {
    wallRows[rr.RR_START_ROW][col] = ".";
  }
  wallRows[rr.RR_START_ROW - 1][3] = "."; // the stub cell
  return { rows: rr.RR_ROWS, columns, wallRows, shortestPath: columns };
}

function pocketBoard() {
  // Corridor on row 10 (index 9) cols 0-3 only; a 2x2 fully observed pocket
  // above cols 3-4, reachable only through (9,3) -> (8,3). Goo seals the rest.
  const columns = 12;
  const wallRows = [];
  for (let row = 0; row < rr.RR_ROWS; row++) {
    wallRows.push([..."#".repeat(columns)]);
  }
  for (let col = 0; col <= 3; col++) {
    wallRows[rr.RR_START_ROW][col] = ".";
  }
  wallRows[rr.RR_START_ROW - 1][3] = ".";
  wallRows[rr.RR_START_ROW - 1][4] = ".";
  wallRows[rr.RR_START_ROW - 2][3] = ".";
  wallRows[rr.RR_START_ROW - 2][4] = ".";
  return { rows: rr.RR_ROWS, columns, wallRows, shortestPath: columns };
}

function walkTo(run, board, dirs) {
  for (const dir of dirs) {
    const move = rr.rrLegalMoves(board, run.pos).find((item) => item.id === dir);
    assert.ok(move, `expected legal move ${dir} from row ${run.pos.row + 1}, column ${run.pos.col + 1}`);
    rr.rrApplyMove(run, board, move);
  }
}

test("8. dead-end flag only after visiting the stub", () => {
  const board = stubBoard();
  const run = rr.rrCreateRunState(board, { memoryAid: "memory" });
  // Start is (RR_START_ROW, 0). Walk right 3 steps to col 3.
  walkTo(run, board, ["right", "right", "right"]);
  assert.equal(run.pos.col, 3);
  const up = rr.rrLegalMoves(board, run.pos).find((move) => move.id === "up");
  assert.ok(up, "stub move is legal");
  // Before visiting: observed, never visited, single exit back -> not a dead end yet.
  let facts = rr.rrMoveFacts(run, board, up);
  assert.equal(facts.deadEnd, false, "unvisited stub is not a dead end yet");
  // Step in and back out.
  rr.rrApplyMove(run, board, up);
  assert.equal(run.pos.row, rr.RR_START_ROW - 1);
  const back = rr.rrLegalMoves(board, run.pos).find((move) => move.id === "down");
  rr.rrApplyMove(run, board, back);
  assert.equal(run.pos.col, 3);
  facts = rr.rrMoveFacts(run, board, up);
  assert.equal(facts.deadEnd, true, "visited stub with no other exits is a dead end");
  assert.equal(facts.visits, 1);
  assert.equal(facts.unseen, 0);
  assert.equal(facts.otherExits, 0);
  // isPrevious: from col 3 the cell you just came from is the stub.
  assert.equal(facts.isPrevious, true);
  const text = rr.rrMoveFactText(run, board, up);
  assert.ok(text.includes("KNOWN DEAD END"), text);
});

test("9. isPrevious after two moves and when only the start exists", () => {
  const board = stubBoard();
  const run = rr.rrCreateRunState(board, { memoryAid: "memory" });
  const right = rr.rrLegalMoves(board, run.pos).find((move) => move.id === "right");
  // Only one step exists: previous cell is the start cell.
  rr.rrApplyMove(run, board, right);
  const left = rr.rrLegalMoves(board, run.pos).find((move) => move.id === "left");
  const facts = rr.rrMoveFacts(run, board, left);
  assert.equal(facts.isPrevious, true, "start cell is previous when only one step exists");
  assert.equal(run.steps.length, 1);
  // After a second move, previous is the second-last step's cell.
  rr.rrApplyMove(run, board, right);
  assert.equal(run.pos.col, 2);
  const back = rr.rrLegalMoves(board, run.pos).find((move) => move.id === "left");
  assert.equal(rr.rrMoveFacts(run, board, back).isPrevious, true);
  const forward = rr.rrLegalMoves(board, run.pos).find((move) => move.id === "right");
  assert.equal(rr.rrMoveFacts(run, board, forward).isPrevious, false);
});

test("10. pocket detection with and without unobserved neighbours, per memoryAid", () => {
  // 2x2 pocket above cols 3-4, observed by walking through it.
  const board = pocketBoard();
  const buildObserved = (memoryAid) => {
    const run = rr.rrCreateRunState(board, { memoryAid });
    // Walk: right x3, up, right, up, left, down, down -> back at col 3, corridor.
    walkTo(run, board, ["right", "right", "right", "up", "right", "up", "left", "down", "down"]);
    assert.equal(run.pos.col, 3);
    assert.equal(run.pos.row, rr.RR_START_ROW);
    return run;
  };
  const memoryRun = buildObserved("memory");
  const up = rr.rrLegalMoves(board, memoryRun.pos).find((move) => move.id === "up");
  assert.ok(up, "pocket entrance is legal");
  const facts = rr.rrMoveFacts(memoryRun, board, up);
  assert.equal(facts.deadEnd, false, "pocket entrance has other exits");
  assert.equal(facts.pocket, true, "fully observed 2x2 pocket is flagged");
  assert.equal(facts.pocketSize, 4);
  assert.ok(rr.rrMoveFactText(memoryRun, board, up).includes("EXPLORED POCKET: all 4 cell(s)"));
  // Un-observe one pocket neighbour -> the pocket now borders unseen cells.
  const leaky = { ...memoryRun, observed: { ...memoryRun.observed } };
  delete leaky.observed[rr.gridKey(rr.RR_START_ROW - 2, 4)];
  const leakyFacts = rr.rrMoveFacts(leaky, board, up);
  assert.equal(leakyFacts.pocket, false, "pocket with an unobserved neighbour is not flagged");
  assert.ok(!rr.rrMoveFactText(leaky, board, up).includes("EXPLORED POCKET"), "leaky pocket move drops the EXPLORED POCKET tag");
  // Pocket is never computed for "facts" and "map".
  for (const level of ["facts", "map"]) {
    const run = buildObserved(level);
    const move = rr.rrLegalMoves(board, run.pos).find((item) => item.id === "up");
    const levelFacts = rr.rrMoveFacts(run, board, move);
    assert.equal(levelFacts.pocket, false, `pocket unset for ${level}`);
    assert.equal(levelFacts.pocketSize, 0);
  }
  // A move leading to the last column is never a pocket even when fully observed.
  const exitRun = { ...memoryRun, observed: { ...memoryRun.observed } };
  const factsExit = rr.rrMoveFacts(exitRun, board, { id: "right", label: "right", row: rr.RR_START_ROW, col: board.columns - 1 });
  assert.equal(factsExit.pocket, false);
});

test("11. memory context carries aid lines; map context carries none", () => {
  const board = pocketBoard();
  const memoryRun = rr.rrCreateRunState(board, { memoryAid: "memory" });
  walkTo(memoryRun, board, ["right", "right", "right", "up", "down"]);
  const memoryContext = rr.rrBuildMoveContext(memoryRun, board);
  assert.ok(memoryContext.includes("Steps since you last reached a new furthest column:"));
  const factsRun = rr.rrCreateRunState(board, { memoryAid: "facts" });
  walkTo(factsRun, board, ["right", "right", "right", "up", "down"]);
  const factsContext = rr.rrBuildMoveContext(factsRun, board);
  assert.ok(factsContext.includes("Steps since you last reached a new furthest column:"));
  // KNOWN DEAD END appears once the stub has been visited (pocket board has none, use stub board).
  const stub = stubBoard();
  const stubRun = rr.rrCreateRunState(stub, { memoryAid: "memory" });
  walkTo(stubRun, stub, ["right", "right", "right", "up", "down"]);
  const stubContext = rr.rrBuildMoveContext(stubRun, stub);
  assert.ok(stubContext.includes("KNOWN DEAD END"));
  // Map level: no aid strings at all.
  const mapRun = rr.rrCreateRunState(stub, { memoryAid: "map" });
  walkTo(mapRun, stub, ["right", "right", "right", "up", "down"]);
  const mapContext = rr.rrBuildMoveContext(mapRun, stub);
  for (const banned of ["KNOWN DEAD END", "EXPLORED POCKET", "Steps since you last reached", "Loop warning"]) {
    assert.ok(!mapContext.includes(banned), `map context must not contain "${banned}"`);
  }
  // Move criteria wording per level.
  const mapMove = rr.rrLegalMoves(stub, mapRun.pos).find((move) => move.id === "up");
  const mapText = rr.rrMoveCriteria(mapRun, stub, [mapMove])[mapMove.id];
  assert.ok(!mapText.includes("unseen neighbour") && !mapText.includes("other open exit"));
  assert.ok(mapText.includes("visited"));
});

test("12. loop warning after oscillating between two cells", () => {
  const board = stubBoard();
  const run = rr.rrCreateRunState(board, { memoryAid: "memory" });
  walkTo(run, board, ["right", "right"]);
  for (let index = 0; index < 12; index++) {
    walkTo(run, board, [index % 2 === 0 ? "right" : "left"]);
  }
  assert.ok(run.steps.length >= 8);
  const context = rr.rrBuildMoveContext(run, board);
  assert.match(context, /Loop warning: your last \d+ moves covered only \d+ different cells\./);
  // A straight walk on the corridor must not trigger the warning.
  const straight = rr.rrCreateRunState(board, { memoryAid: "memory" });
  walkTo(straight, board, ["right", "right", "right", "right", "right", "right", "right", "right", "right", "right"]);
  assert.ok(!rr.rrBuildMoveContext(straight, board).includes("Loop warning"));
});

test("13. rrMoveInstructions strings per level, cap after 1500 moves for each level", () => {
  const base = "You are navigating a hazardous grid. Choose the single next move that best progresses toward the goal, using the known map and your movement history. The exit is to the right, so Right is forward progress and is usually the best move. When a move is marked FORWARD, choose it. Use Up or Down only when there is no FORWARD move, to get around the goo; use Left only when Right, Up and Down cannot lead anywhere new.";
  assert.equal(rr.rrMoveInstructions("map"), base);
  const colours = "Moves are colour-coded from your history: GREEN = visited 1 to 3 times, ok to use; YELLOW = known dead end, never choose it; RED = visited more than 3 times, been here and done that: back away from it and find another path with no RED, preferring never-visited cells. If every move is RED, choose the one visited least.";
  assert.equal(rr.rrMoveInstructions("facts"), `${base} ${colours}`);
  assert.equal(rr.rrMoveInstructions("memory"), `${base} ${colours} A move marked EXPLORED POCKET leads only to cells you have already fully explored; do not choose it, even if it is Right, unless nothing else is legal.`);
  for (const level of rr.RR_MEMORY_AIDS) {
    const board = rr.rrGenerateBoard({ seed: 1234, columns: 40 });
    const run = rr.rrCreateRunState(board, { memoryAid: level });
    const texts = Object.fromEntries(rr.rrLegalMoves(board, run.pos).map((move) => [move.id, rr.rrMoveFactText(run, board, move)]));
    if (texts.right) assert.ok(texts.right.includes("FORWARD"), texts.right);
    for (const id of ["up", "down"]) if (texts[id]) assert.ok(texts[id].includes("sideways"), texts[id]);
  }
  assert.ok(rr.RR_MEMORY_AIDS.join(",") === "map,facts,memory");
  for (const level of rr.RR_MEMORY_AIDS) {
    const board = rr.rrGenerateBoard({ seed: 1234, columns: 80 });
    const run = rr.rrCreateRunState(board, { memoryAid: level });
    run.budget = 1000000;
    let guard = 0;
    while (run.steps.length < 1500 && run.status === "running" && guard < 1600) {
      const legal = rr.rrLegalMoves(board, run.pos);
      const pick = legal[Math.floor(Math.random() * legal.length)];
      rr.rrApplyMove(run, board, pick, { forced: legal.length === 1 });
      guard++;
    }
    assert.ok(run.steps.length >= 1000, `only reached ${run.steps.length} steps for ${level}`);
    const context = rr.rrBuildMoveContext(run, board);
    assert.ok(context.length <= 7000, `context too long for ${level}: ${context.length}`);
    assert.ok(context.includes("Legal moves:"));
  }
});

test("14. summarize exposes memoryAid; legacy runs default safely", () => {
  const board = rr.rrGenerateBoard({ seed: 77, columns: 40 });
  const run = rr.rrCreateRunState(board, { memoryAid: "map" });
  assert.equal(run.memoryAid, "map");
  assert.equal(run.furthestStep, 0);
  assert.equal(rr.rrSummarizeRun(run, board).memoryAid, "map");
  assert.equal(rr.rrSummarizeRun({ ...run, memoryAid: undefined }, board).memoryAid, null);
  assert.equal(rr.rrCreateRunState(board).memoryAid, "memory");
  assert.equal(rr.rrCreateRunState(board, { memoryAid: "bogus" }).memoryAid, "memory");
  // New flag/decision fields default safely, including on legacy shapes without flags.
  // (Objects from the vm realm have a foreign prototype, so compare copies/keys.)
  assert.deepEqual(JSON.parse(JSON.stringify(rr.rrCreateRunState(board).flags)), { deadEnds: {}, pockets: {} });
  assert.equal(rr.rrCreateRunState(board).lastDecision, null);
  assert.equal(rr.rrCreateRunState(board).flagsIgnored, 0);
  assert.equal(rr.rrCreateRunState(board).flagsUnseen, 0);
  const legacySummary = rr.rrSummarizeRun({ ...run, flags: undefined, flagsIgnored: undefined, flagsUnseen: undefined }, board);
  assert.equal(legacySummary.flagsIgnored, 0);
  assert.equal(legacySummary.flagsUnseen, 0);
  assert.equal(legacySummary.deadEndsFound, 0);
  assert.equal(legacySummary.pocketCellsFound, 0);
});

test("14b. rrRecordDecision flags dead ends and counts ignored vs unseen", () => {
  const board = stubBoard();
  // Enter the stub and come back so it becomes a dead end.
  const probe = rr.rrCreateRunState(board, { memoryAid: "memory" });
  walkTo(probe, board, ["right", "right", "right", "up", "down"]);
  for (const level of ["facts", "memory"]) {
    // Fresh run walks the same path via recorded decisions (all forced until the choice matters).
    const run = rr.rrCreateRunState(board, { memoryAid: level });
    walkTo(run, board, ["right", "right", "right", "up", "down"]);
    const legal = rr.rrLegalMoves(board, run.pos);
    const up = legal.find((move) => move.id === "up");
    rr.rrRecordDecision(run, board, legal, { chosenId: "up", forced: false });
    const decision = run.lastDecision;
    assert.ok(decision, "lastDecision recorded");
    assert.equal(decision.from.row, run.pos.row);
    assert.equal(decision.from.col, run.pos.col);
    assert.equal(decision.chosen, "up");
    const candidate = decision.candidates.find((item) => item.id === "up");
    assert.equal(candidate.flag, "deadEnd");
    assert.equal(candidate.shown, true, `dead end shown at ${level}`);
    assert.ok(run.flags.deadEnds[rr.gridKey(up.row, up.col)], "stub target flagged as dead end");
    assert.equal(run.flagsIgnored, 1, `choosing the flagged stub increments flagsIgnored at ${level}`);
    assert.equal(run.flagsUnseen, 0);
    // Step lands with the flag attached.
    rr.rrApplyMove(run, board, up, { forced: false, flag: candidate.flag });
    assert.equal(run.steps.at(-1).flag, "deadEnd");
  }
  // At "map" the flag exists on the board but was never shown: unseen.
  const mapRun = rr.rrCreateRunState(board, { memoryAid: "map" });
  walkTo(mapRun, board, ["right", "right", "right", "up", "down"]);
  const mapLegal = rr.rrLegalMoves(board, mapRun.pos);
  rr.rrRecordDecision(mapRun, board, mapLegal, { chosenId: "up", forced: false });
  const mapCandidate = mapRun.lastDecision.candidates.find((item) => item.id === "up");
  assert.equal(mapCandidate.flag, "deadEnd");
  assert.equal(mapCandidate.shown, false, "dead end not shown at map level");
  assert.equal(mapRun.flagsIgnored, 0);
  assert.equal(mapRun.flagsUnseen, 1, "choosing an unseen flagged move increments flagsUnseen");
  // Flag summary fields.
  const summary = rr.rrSummarizeRun(mapRun, board);
  assert.equal(summary.flagsIgnored, 0);
  assert.equal(summary.flagsUnseen, 1);
  assert.equal(summary.deadEndsFound, 1);
});

test("14c. rrRecordDecision records pocket cells with forcePocket even at facts level", () => {
  const board = pocketBoard();
  const run = rr.rrCreateRunState(board, { memoryAid: "facts" });
  walkTo(run, board, ["right", "right", "right", "up", "right", "up", "left", "down", "down"]);
  assert.ok(!rr.rrBuildMoveContext(run, board).includes("EXPLORED POCKET"), "facts context must not mention pockets");
  const legal = rr.rrLegalMoves(board, run.pos);
  const up = legal.find((move) => move.id === "up");
  rr.rrRecordDecision(run, board, legal, { chosenId: "right", forced: false });
  const candidate = run.lastDecision.candidates.find((item) => item.id === "up");
  assert.equal(candidate.flag, "pocket");
  assert.equal(candidate.shown, false, "pocket not shown at facts level");
  assert.equal(candidate.probability, null);
  assert.ok(run.flags.pockets[rr.gridKey(up.row, up.col)], "pocket entrance cell recorded");
  // The 2x2 pocket contributes 4 cells; other legal candidates may add their own
  // pocket cells to the same never-removed map, so check membership, not exact size.
  const pocketKeys = Object.keys(run.flags.pockets);
  assert.ok(pocketKeys.includes(rr.gridKey(rr.RR_START_ROW - 1, 4)));
  assert.ok(pocketKeys.includes(rr.gridKey(rr.RR_START_ROW - 2, 4)));
  assert.ok(rr.rrSummarizeRun(run, board).pocketCellsFound >= 4);
  // Isolating the up-candidate shows exactly its 4 pocket cells.
  rr.rrRecordDecision(run, board, [up], { chosenId: "up", forced: false });
  assert.equal(Object.keys(run.flags.pockets).length >= 4, true);
  const isolated = rr.rrCreateRunState(board, { memoryAid: "facts" });
  walkTo(isolated, board, ["right", "right", "right", "up", "right", "up", "left", "down", "down"]);
  rr.rrRecordDecision(isolated, board, [up], { chosenId: "up", forced: false });
  assert.deepEqual([...Object.keys(isolated.flags.pockets)].sort(), [
    rr.gridKey(rr.RR_START_ROW - 1, 3), rr.gridKey(rr.RR_START_ROW - 1, 4),
    rr.gridKey(rr.RR_START_ROW - 2, 3), rr.gridKey(rr.RR_START_ROW - 2, 4),
  ].sort());
  assert.deepEqual([...Object.keys(isolated.flags.deadEnds)], []);
  // facts move fact text still omits the pocket wording.
  assert.ok(!rr.rrMoveFactText(run, board, up).includes("EXPLORED POCKET"));
  // At memory level the pocket is shown.
  const memoryRun = rr.rrCreateRunState(board, { memoryAid: "memory" });
  walkTo(memoryRun, board, ["right", "right", "right", "up", "right", "up", "left", "down", "down"]);
  const memoryLegal = rr.rrLegalMoves(board, memoryRun.pos);
  rr.rrRecordDecision(memoryRun, board, memoryLegal, { chosenId: "up", forced: false, probabilities: { up: 0.5, right: 0.5 } });
  const memoryCandidate = memoryRun.lastDecision.candidates.find((item) => item.id === "up");
  assert.equal(memoryCandidate.shown, true);
  assert.equal(memoryCandidate.probability, 0.5);
  // The only other move (left, back down the sealed corridor) is a pocket too, so nothing unflagged was on offer.
  assert.ok(memoryRun.lastDecision.candidates.every((item) => item.flag));
  assert.equal(memoryRun.flagsIgnored, 0, "no unflagged option existed, so the pocket choice is not counted as ignored");
});

test("14d. rrParseMoveValue probabilities and confidence", () => {
  const parse = (body, ids = ["up", "down"]) => rr.rrParseMoveValue(body, ids);
  const base = { results: [{ fields: { move: { value: "up" } } }] };
  // No probabilities at all -> null, confidence null. (Spread defeats vm-realm prototypes.)
  assert.deepEqual({ ...parse(base) }, { move: "up", confidence: null, probabilities: null });
  // Numeric map: legal ids only, non-finite skipped.
  const withProbabilities = { results: [{ fields: { move: { value: "down", probabilities: { up: 0.25, down: 0.75, teleport: 9, bogus: "x" } } } }] };
  const parsed = parse(withProbabilities);
  assert.deepEqual({ ...parsed.probabilities }, { up: 0.25, down: 0.75 });
  assert.equal(parsed.confidence, 0.75);
  // Array-form probability for the chosen move still sets confidence.
  const arrayForm = { results: [{ fields: { move: { value: "up", probabilities: { up: [0.4], down: [0.6] } } } }] };
  const parsedArray = parse(arrayForm);
  assert.equal(parsedArray.confidence, 0.4);
  assert.deepEqual({ ...parsedArray.probabilities }, { up: 0.4, down: 0.6 });
});

test("6. budget formula and metrics", () => {
  assert.equal(rr.rrMoveBudget(10), 50);
  assert.equal(rr.rrMoveBudget(4), 44);
  const board = rr.rrGenerateBoard({ seed: 555, columns: 40 });
  const run = rr.rrCreateRunState(board);
  assert.equal(run.budget, rr.rrMoveBudget(board.shortestPath));
  // Simulate a revisit: right then left, if legal.
  const legal = rr.rrLegalMoves(board, run.pos);
  const right = legal.find((move) => move.id === "right");
  if (right) {
    rr.rrApplyMove(run, board, right, { confidence: 0.8, ms: 40 });
    const back = rr.rrLegalMoves(board, run.pos).find((move) => move.id === "left");
    rr.rrApplyMove(run, board, back, { forced: true, confidence: 0.9, ms: 100 });
    const summary = rr.rrSummarizeRun(run, board);
    assert.equal(summary.revisits, 1);
    assert.equal(summary.forcedMoves, 1);
    assert.equal(summary.modelDecisions, 1);
    assert.equal(summary.efficiency, null);
    assert.equal(summary.avgDecisionMs, 40);
    assert.equal(summary.avgConfidence, 0.8);
  }
  // Illegal move throws.
  assert.throws(() => rr.rrApplyMove(run, board, { id: "teleport" }));
});

test("7. full simulated run with random policy terminates within budget", () => {
  const board = rr.rrGenerateBoard({ seed: 31337, columns: 60 });
  const run = rr.rrCreateRunState(board);
  let forcedOk = true;
  while (run.status === "running") {
    const legal = rr.rrLegalMoves(board, run.pos);
    if (legal.length === 1) {
      rr.rrApplyMove(run, board, legal[0], { forced: true });
    } else {
      const pick = legal[Math.floor(Math.random() * legal.length)];
      rr.rrApplyMove(run, board, pick);
      forcedOk = forcedOk && true;
    }
    assert.ok(run.moves <= run.budget, "moves exceeded budget");
  }
  assert.ok(["completed", "budget"].includes(run.status), `unexpected status ${run.status}`);
  assert.ok(forcedOk);
  const summary = rr.rrSummarizeRun(run, board);
  assert.equal(summary.moves, run.moves);
  if (run.status === "completed") {
    assert.ok(summary.efficiency > 0 && summary.efficiency <= 1);
  }
});

test("19. colour tags: GREEN for 1-3 visits, RED above 3, YELLOW dead end, red flag recorded", () => {
  const board = stubBoard();
  const run = rr.rrCreateRunState(board, { memoryAid: "facts" });
  walkTo(run, board, ["right", "right", "right"]);
  const left = () => rr.rrLegalMoves(board, run.pos).find((move) => move.id === "left");
  const right = () => rr.rrLegalMoves(board, run.pos).find((move) => move.id === "right");
  assert.ok(rr.rrMoveFactText(run, board, left()).includes("GREEN · visited 1 time, ok"));
  assert.ok(rr.rrMoveFactText(run, board, right()).includes("never visited"));
  for (let i = 0; i < rr.RR_RED_VISITS; i++) walkTo(run, board, ["left", "right"]);
  const redText = rr.rrMoveFactText(run, board, left());
  assert.ok(redText.includes(`RED · visited ${rr.RR_RED_VISITS + 1} times`), redText);
  assert.ok(!redText.includes("GREEN"), redText);
  assert.equal(rr.rrMoveFacts(run, board, left()).red, true);
  const flag = rr.rrRecordDecision(run, board, rr.rrLegalMoves(board, run.pos), { chosenId: "left", forced: false });
  assert.equal(flag, "red");
  assert.equal(run.flagsIgnored, 1, "choosing a shown RED move counts as ignoring a flag");
  // Dead end is YELLOW and never also GREEN.
  const up = rr.rrLegalMoves(board, run.pos).find((move) => move.id === "up");
  walkTo(run, board, ["up", "down"]);
  const deadText = rr.rrMoveFactText(run, board, up);
  assert.ok(deadText.includes("YELLOW · KNOWN DEAD END"), deadText);
  assert.ok(!deadText.includes("GREEN"), deadText);
  // A RED Right is not labelled FORWARD; the map level shows no colours.
  const mapRun = rr.rrCreateRunState(board, { memoryAid: "map" });
  walkTo(mapRun, board, ["right", "right", "right"]);
  for (let i = 0; i < rr.RR_RED_VISITS; i++) walkTo(mapRun, board, ["left", "right"]);
  const mapText = rr.rrMoveFactText(mapRun, board, rr.rrLegalMoves(board, mapRun.pos).find((move) => move.id === "left"));
  assert.ok(!/RED|GREEN|YELLOW/.test(mapText), mapText);
  assert.ok(!rr.rrRenderKnownMap(mapRun, board).includes("RED"));
  assert.ok(rr.rrRenderKnownMap(run, board).includes(`${rr.RR_RED_VISITS + 1} or more = RED`));
});

test("20. choosing a flagged move is not counted as ignored when every option is flagged", () => {
  const board = stubBoard();
  const run = rr.rrCreateRunState(board, { memoryAid: "facts" });
  walkTo(run, board, ["right", "right", "right"]);
  const legal = rr.rrLegalMoves(board, run.pos).map((move) => ({ ...move }));
  for (const move of legal) run.visits[rr.gridKey(move.row, move.col)] = rr.RR_RED_VISITS + 1;
  const flag = rr.rrRecordDecision(run, board, legal, { chosenId: legal[0].id, forced: false });
  assert.ok(flag, "chosen move is flagged");
  assert.equal(run.flagsIgnored, 0);
  assert.equal(run.flagsUnseen, 0);
});
