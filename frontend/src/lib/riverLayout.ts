import type { RiverGraph, RiverNode } from '../api';

export interface PlacedNode {
  node: RiverNode;
  row: number;
  x: number;
  y: number;
  /** True when the row holds several nodes (labels then go below the node). */
  shared: boolean;
}

export interface BorderLine {
  y: number;
  above: string;
  below: string;
}

export interface RiverLayout {
  placed: Record<string, PlacedNode>;
  order: string[];
  borders: BorderLine[];
  width: number;
  height: number;
}

export const LAYOUT = { width: 480, rowHeight: 120, top: 40, bottom: 80 };

/**
 * Lay a river graph out top-to-bottom by flow order (topological depth).
 * Countries are kept in contiguous bands in the order they first appear along
 * the flow, so a single dashed border line can separate them.
 */
export function layoutRiver(graph: RiverGraph, width = LAYOUT.width): RiverLayout {
  const nodes = graph.nodes ?? [];
  const edges = (graph.edges ?? []).filter(
    (e) => nodes.some((n) => n.id === e.from) && nodes.some((n) => n.id === e.to),
  );
  const preds: Record<string, string[]> = {};
  const indeg: Record<string, number> = {};
  for (const n of nodes) {
    preds[n.id] = [];
    indeg[n.id] = 0;
  }
  for (const e of edges) {
    preds[e.to].push(e.from);
    indeg[e.to] += 1;
  }

  // Kahn's algorithm; any nodes left in a cycle are appended in input order.
  const order: string[] = [];
  const queue = nodes.filter((n) => indeg[n.id] === 0).map((n) => n.id);
  const remaining = { ...indeg };
  while (queue.length > 0) {
    const id = queue.shift() as string;
    order.push(id);
    for (const e of edges) {
      if (e.from !== id) continue;
      remaining[e.to] -= 1;
      if (remaining[e.to] === 0) queue.push(e.to);
    }
  }
  for (const n of nodes) if (!order.includes(n.id)) order.push(n.id);

  const byId: Record<string, RiverNode> = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const depth: Record<string, number> = {};
  for (const id of order) {
    const ps = preds[id].filter((p) => p in depth);
    depth[id] = ps.length ? Math.max(...ps.map((p) => depth[p])) + 1 : 0;
  }

  // Country bands, in order of first appearance along the flow.
  const countries: string[] = [];
  for (const id of order) {
    const c = byId[id].country ?? '';
    if (!countries.includes(c)) countries.push(c);
  }
  const row: Record<string, number> = {};
  let offset = 0;
  for (const c of countries) {
    const ids = order.filter((id) => (byId[id].country ?? '') === c);
    const minDepth = Math.min(...ids.map((id) => depth[id]));
    let maxRow = offset;
    for (const id of ids) {
      row[id] = offset + depth[id] - minDepth;
      maxRow = Math.max(maxRow, row[id]);
    }
    offset = maxRow + 1;
  }
  // Keep every edge pointing downwards.
  for (const id of order) {
    for (const p of preds[id]) {
      if (row[p] !== undefined && row[id] <= row[p]) row[id] = row[p] + 1;
    }
  }

  const rowsUsed = order.length ? Math.max(...order.map((id) => row[id])) + 1 : 0;
  const height = LAYOUT.top + Math.max(rowsUsed - 1, 0) * LAYOUT.rowHeight + LAYOUT.bottom;
  const placed: Record<string, PlacedNode> = {};
  for (let r = 0; r < rowsUsed; r++) {
    const inRow = order.filter((id) => row[id] === r);
    inRow.forEach((id, i) => {
      const side = inRow.length === 2 ? width * 0.25 : width * 0.15;
      const usable = width - side * 2;
      const x = inRow.length === 1 ? width * 0.3 : side + (usable * i) / (inRow.length - 1);
      placed[id] = { node: byId[id], row: r, x, y: LAYOUT.top + r * LAYOUT.rowHeight, shared: inRow.length > 1 };
    });
  }

  const borders: BorderLine[] = [];
  for (let k = 1; k < countries.length; k++) {
    const prevRows = order.filter((id) => (byId[id].country ?? '') === countries[k - 1]).map((id) => row[id]);
    const nextRows = order.filter((id) => (byId[id].country ?? '') === countries[k]).map((id) => row[id]);
    const maxPrev = Math.max(...prevRows);
    const minNext = Math.min(...nextRows);
    if (maxPrev < minNext) {
      const y = LAYOUT.top + ((maxPrev + minNext) / 2) * LAYOUT.rowHeight;
      borders.push({ y, above: countries[k - 1], below: countries[k] });
    }
  }

  return { placed, order, borders, width, height };
}
