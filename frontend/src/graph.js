// Plain functions over a scenario definition: story order, every route from the
// start to an ending, and what is reachable. Used by the builder's outline, map
// and review step. No React here, so it can be tested with plain Node.

/** Scene ids in the order a student could meet them (breadth-first from the start),
 *  followed by any scenes that can't be reached. */
export function storyOrder(def) {
  const nodes = def?.nodes || {};
  const order = [];
  const seen = new Set();
  if (nodes[def?.start]) {
    const q = [def.start];
    seen.add(def.start);
    while (q.length) {
      const id = q.shift();
      order.push(id);
      for (const c of nodes[id].choices || []) {
        if (nodes[c.next] && !seen.has(c.next)) { seen.add(c.next); q.push(c.next); }
      }
    }
  }
  const unreachable = Object.keys(nodes).filter((id) => !seen.has(id));
  return { order: [...order, ...unreachable], reachable: seen, unreachable };
}

/** Which scenes lead into each scene: { sceneId: [{ from, label }] }. */
export function incoming(def) {
  const nodes = def?.nodes || {};
  const into = {};
  for (const [id, n] of Object.entries(nodes)) {
    for (const c of n.choices || []) {
      if (nodes[c.next]) (into[c.next] ||= []).push({ from: id, label: c.label });
    }
  }
  return into;
}

/**
 * Every way through the scenario, from the starting scene to an ending.
 * Each route: { steps: [{ scene, path }], end: sceneId | null, problem: null | "loop" | "dead-end" | "broken" }
 * A route that comes back to a scene it has already visited stops there ("loop").
 * Stops after `limit` routes and reports `truncated`.
 */
export function routes(def, limit = 60) {
  const nodes = def?.nodes || {};
  const out = [];
  let truncated = false;
  if (!nodes[def?.start]) return { routes: out, truncated };
  const walk = (id, steps, visited) => {
    if (out.length >= limit) { truncated = true; return; }
    const n = nodes[id];
    if (n.ending) { out.push({ steps, end: id, problem: null }); return; }
    const choices = n.choices || [];
    if (!choices.length) { out.push({ steps, end: id, problem: "dead-end" }); return; }
    for (const c of choices) {
      const step = { scene: id, path: c.label || "(unnamed path)" };
      if (!nodes[c.next]) out.push({ steps: [...steps, step], end: null, problem: "broken" });
      else if (visited.has(c.next)) out.push({ steps: [...steps, step], end: c.next, problem: "loop" });
      else walk(c.next, [...steps, step], new Set([...visited, c.next]));
      if (out.length >= limit) { truncated = true; return; }
    }
  };
  walk(def.start, [], new Set([def.start]));
  return { routes: out, truncated };
}

const RANK = { fail: 0, partial: 1, success: 2 };

/** The path a scene takes when the student never clearly takes one: the instructor's
 *  pick, or else the path whose branch can lead to the worst ending (the last such
 *  path on a tie). Mirrors fallback_choice() on the server. Returns the path's index or -1. */
export function fallbackIndex(def, sceneId) {
  const nodes = def?.nodes || {};
  const n = nodes[sceneId];
  if (!n) return -1;
  const valid = (n.choices || []).map((c, i) => [c, i]).filter(([c]) => nodes[c.next]);
  if (!valid.length) return -1;
  if (n.fallback) {
    const hit = valid.find(([c]) => c.label === n.fallback);
    if (hit) return hit[1];
  }
  const worstFrom = (start) => {
    let worst = null;
    const seen = new Set([start]);
    const q = [start];
    while (q.length) {
      const x = nodes[q.shift()];
      if (!x) continue;
      if (x.ending) { const r = RANK[x.ending.type] ?? 1; worst = worst === null ? r : Math.min(worst, r); }
      for (const c of x.choices || []) if (nodes[c.next] && !seen.has(c.next)) { seen.add(c.next); q.push(c.next); }
    }
    return worst === null ? 1 : worst;
  };
  let best = null;
  for (const [c, i] of valid) {
    const w = worstFrom(c.next);
    if (best === null || w < best.w || (w === best.w && i > best.i)) best = { w, i };
  }
  return best.i;
}

/** Counts for the review step. */
export function summary(def) {
  const nodes = Object.values(def?.nodes || {});
  const endings = nodes.filter((n) => n.ending);
  return {
    scenes: nodes.length,
    endings: endings.length,
    byType: { success: endings.filter((n) => n.ending.type === "success").length,
      partial: endings.filter((n) => n.ending.type === "partial").length,
      fail: endings.filter((n) => n.ending.type === "fail").length },
    paths: nodes.reduce((a, n) => a + (n.choices || []).length, 0),
  };
}
