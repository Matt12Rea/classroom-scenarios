// Visual map of a scenario's scenes and decisions, laid out left to right by
// distance from the starting scene. Click a scene to edit it.
const W = 180, H = 58, GX = 70, GY = 22, PAD = 20;

export default function FlowMap({ def, onSelect }) {
  const nodes = def.nodes || {};
  const ids = Object.keys(nodes);
  if (!ids.length) return null;
  const depth = {};
  if (nodes[def.start]) {
    depth[def.start] = 0;
    const q = [def.start];
    while (q.length) {
      const n = q.shift();
      for (const c of nodes[n].choices || []) {
        if (nodes[c.next] && depth[c.next] === undefined) { depth[c.next] = depth[n] + 1; q.push(c.next); }
      }
    }
  }
  const maxD = Math.max(0, ...Object.values(depth));
  const cols = {};
  ids.forEach((id) => {
    const d = depth[id] ?? maxD + 1;
    (cols[d] ||= []).push(id);
  });
  const pos = {};
  Object.entries(cols).forEach(([d, list]) => list.forEach((id, i) => {
    pos[id] = { x: PAD + Number(d) * (W + GX), y: PAD + i * (H + GY) };
  }));
  const width = PAD * 2 + (Object.keys(cols).length) * (W + GX) - GX;
  const height = PAD * 2 + Math.max(...Object.values(cols).map((l) => l.length)) * (H + GY) - GY;

  const edges = [];
  ids.forEach((id) => (nodes[id].choices || []).forEach((c, j) => {
    const a = pos[id];
    const b = pos[c.next];
    if (!b) {
      edges.push(<path key={`${id}-${j}`} className="broken" d={`M${a.x + W},${a.y + H / 2} h28`}><title>{`“${c.label}” leads nowhere yet`}</title></path>);
      return;
    }
    const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
    let d;
    if (a.x === b.x && id !== c.next) {
      // Same column: loop out to the right of both boxes.
      const ya = a.y + H / 2 + (b.y < a.y ? -8 : 8), yb = b.y + H / 2 + (b.y < a.y ? 8 : -8);
      d = `M${x1},${ya} C${x1 + 34},${ya} ${x1 + 34},${yb} ${x1 + 2},${yb}`;
    } else if (x2 <= x1) {
      // Back to an earlier scene (or itself): loop underneath.
      d = `M${a.x + W / 2},${a.y + H} C${a.x + W / 2},${a.y + H + 34} ${b.x + W / 2 + 20},${b.y + H + 34} ${b.x + W / 2 + 20},${b.y + H + 2}`;
    } else {
      d = `M${x1},${y1} C${x1 + GX / 2},${y1} ${x2 - GX / 2},${y2} ${x2},${y2}`;
    }
    edges.push(<path key={`${id}-${j}`} d={d} markerEnd="url(#arrow)"><title>{c.label}</title></path>);
  }));

  return (
    <div className="flow" role="group" aria-label="Scenario map">
      <svg width={width} height={height + 30} viewBox={`0 0 ${width} ${height + 30}`}>
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" style={{ fill: "var(--ink-3)", stroke: "none" }} />
          </marker>
        </defs>
        {edges}
        {ids.map((id) => {
          const n = nodes[id];
          const p = pos[id];
          const cls = ["node", id === def.start && "start", n.ending?.type, depth[id] === undefined && "unreachable"].filter(Boolean).join(" ");
          const title = n.title.length > 22 ? n.title.slice(0, 21) + "…" : n.title;
          const sub = n.ending ? `Ending: ${n.ending.label || "unnamed"}` : `${(n.choices || []).length} decision${(n.choices || []).length === 1 ? "" : "s"}`;
          return (
            <g key={id} className={cls} transform={`translate(${p.x},${p.y})`} tabIndex={0} role="button"
              aria-label={`Edit scene ${n.title}`} onClick={() => onSelect?.(id)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect?.(id))}>
              <rect width={W} height={H} rx="8" />
              <text x="12" y="24">{id === def.start ? "▶ " : ""}{title}</text>
              <text x="12" y="44" className="sub">{sub.length > 28 ? sub.slice(0, 27) + "…" : sub}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
