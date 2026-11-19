// Visual map of a scenario's scenes and paths, laid out left to right by
// distance from the starting scene. Every arrow carries its path's name, so the
// map can be read without hovering. Click a scene to edit it.
const W = 196, H = 62, GX = 230, GY = 34, PAD = 22;

const clip = (text, n) => (text.length > n ? text.slice(0, n - 1) + "…" : text);

export default function FlowMap({ def, onSelect, selected }) {
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
  ids.forEach((id) => { (cols[depth[id] ?? maxD + 1] ||= []).push(id); });
  const tallest = Math.max(...Object.values(cols).map((l) => l.length));
  const height = PAD * 2 + tallest * (H + GY) - GY;
  const pos = {};
  Object.entries(cols).forEach(([d, list]) => {
    const offset = ((tallest - list.length) * (H + GY)) / 2;       // centre shorter columns
    list.forEach((id, i) => { pos[id] = { x: PAD + Number(d) * (W + GX), y: PAD + offset + i * (H + GY) }; });
  });
  const width = PAD * 2 + Object.keys(cols).length * (W + GX) - GX;
  const names = Object.fromEntries((def.characters || []).map((c) => [c.id, c.name]));

  // Each path leaves its scene at its own height, with its name written right beside
  // the scene it leaves, so labels never sit on top of each other or on a scene.
  const edges = [], labels = [];
  ids.forEach((id) => {
    const out = nodes[id].choices || [];
    out.forEach((c, j) => {
      const a = pos[id], b = pos[c.next];
      const key = `${id}-${j}`;
      const name = c.label || "Unnamed path";
      const x1 = a.x + W;
      const y1 = a.y + H / 2 + (j - (out.length - 1) / 2) * Math.min(20, (H - 8) / Math.max(1, out.length));
      const text = b ? clip(name, 27) : `${clip(name, 14)}: no scene yet`;
      const tail = x1 + 14 + text.length * 6.1 + 12;          // where the label ends
      labels.push({ key, x: x1 + 14, y: y1 + 4, text, full: name, bad: !b });
      if (!b) { edges.push(<path key={key} className="broken" d={`M${x1},${y1} H${x1 + 12}`} />); return; }
      const x2 = b.x, y2 = b.y + H / 2;
      let d;
      if (x2 > x1) {
        const bend = Math.max(tail + 6, x1 + 60);
        d = `M${x1},${y1} H${Math.min(bend, x2 - 24)} C${x2 - 10},${y1} ${Math.min(bend, x2 - 24) + 4},${y2} ${x2},${y2}`;
      } else if (id === c.next) {
        d = `M${x1},${y1} H${tail} C${tail + 30},${y1} ${tail + 30},${a.y - 14} ${a.x + W - 30},${a.y - 2}`;      // loops back to itself
      } else {
        // Same column or an earlier scene: go out past the label, then around to the target's right edge.
        const far = Math.max(tail, b.x + W) + 26;
        const yb = b.y + H / 2 + (b.y < a.y ? 12 : -12);
        d = `M${x1},${y1} H${tail} C${far},${y1} ${far},${yb} ${b.x + W + 2},${yb}`;
      }
      edges.push(<path key={key} d={d} markerEnd="url(#flow-arrow)" />);
    });
  });

  return (
    <div className="flow" role="group" aria-label="Scenario map">
      <svg width={width} height={height + 44} viewBox={`0 0 ${width} ${height + 44}`}>
        <defs>
          <marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="arrow-head" />
          </marker>
        </defs>
        {edges}
        {labels.map((l) => (
          <g key={l.key} className={`edge-label ${l.bad ? "bad" : ""}`}>
            <rect x={l.x - 6} y={l.y - 13} width={l.text.length * 6.1 + 12} height={18} rx="9" />
            <text x={l.x} y={l.y}>{l.text}{l.full !== l.text && <title>{l.full}</title>}</text>
          </g>
        ))}
        {ids.map((id) => {
          const n = nodes[id], p = pos[id];
          const cls = ["node", id === def.start && "start", n.ending?.type, depth[id] === undefined && "unreachable", id === selected && "current"].filter(Boolean).join(" ");
          const cast = (n.characters?.length ? n.characters : [n.character]).map((c) => names[c]).filter(Boolean).join(", ");
          const sub = n.ending ? `Ending: ${n.ending.label || "unnamed"}` : cast || "No one in the scene";
          return (
            <g key={id} className={cls} transform={`translate(${p.x},${p.y})`} tabIndex={0} role="button"
              aria-label={`Open scene ${n.title}`} onClick={() => onSelect?.(id)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect?.(id))}>
              <rect width={W} height={H} rx="6" />
              {id === def.start && <text x="12" y="17" className="tag">Start</text>}
              <text x="12" y={id === def.start ? 35 : 27}>{clip(n.title || id, 25)}</text>
              <text x="12" y={id === def.start ? 52 : 46} className="sub">{clip(sub, 31)}</text>
            </g>
          );
        })}
      </svg>
      <div className="flow-legend">
        <span><i className="k start" />Starting scene</span>
        <span><i className="k success" />Ending: success</span>
        <span><i className="k partial" />Ending: partial</span>
        <span><i className="k fail" />Ending: didn't succeed</span>
        <span><i className="k unreachable" />Not connected</span>
      </div>
    </div>
  );
}
