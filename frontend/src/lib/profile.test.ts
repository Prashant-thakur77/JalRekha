import { describe, expect, it } from 'vitest';
import { metreTicks, nearestRow, niceStep, profileGeometry } from './profile';

const BOX = { width: 240, height: 120, pad: { top: 10, right: 10, bottom: 10, left: 40 } };
// Row 0 is the top of the gauge strip (highest stage); stage falls by 0.1 m per row.
const AXIS = [3.0, 2.9, 2.8, 2.7, 2.6, 2.5, 2.4, 2.3, 2.2, 2.1, 2.0];
const SIGNAL = [5, 5, 5, 5, 5, 1, 1, 1, 1, 1, 1];

describe('profile chart scaling', () => {
  it('puts the highest stage at the top and the lowest at the bottom of the plot', () => {
    const g = profileGeometry(AXIS, SIGNAL, BOX)!;
    expect(g.top).toBe(3.0);
    expect(g.bottom).toBe(2.0);
    expect(g.y(3.0)).toBeCloseTo(10);
    expect(g.y(2.0)).toBeCloseTo(110);
    expect(g.y(2.5)).toBeCloseTo(60);
  });

  it('maps the signal range across the plot width', () => {
    const g = profileGeometry(AXIS, SIGNAL, BOX)!;
    expect(g.lo).toBe(1);
    expect(g.hi).toBe(5);
    expect(g.x(1)).toBeCloseTo(40);
    expect(g.x(5)).toBeCloseTo(230);
    expect(g.x(3)).toBeCloseTo(135);
  });

  it('draws one path vertex per row, top to bottom', () => {
    const g = profileGeometry(AXIS, SIGNAL, BOX)!;
    const vertices = g.path.match(/[ML]/g) ?? [];
    expect(vertices).toHaveLength(AXIS.length);
    expect(g.path.startsWith('M230.0,10.0')).toBe(true);
    expect(g.path.endsWith('L40.0,110.0')).toBe(true);
  });

  it('breaks the path at missing values and survives a flat signal', () => {
    const gap = profileGeometry(AXIS, [1, 2, NaN, 4, 5, 6, 7, 8, 9, 10, 11], BOX)!;
    expect((gap.path.match(/M/g) ?? []).length).toBe(2);
    const flat = profileGeometry(AXIS, AXIS.map(() => 2), BOX)!;
    expect(flat.x(2)).toBeCloseTo(135);
    expect(profileGeometry([1], [1], BOX)).toBeNull();
    expect(profileGeometry([2, 2, 2], [1, 2, 3], BOX)).toBeNull();
  });

  it('picks round metre ticks inside the axis', () => {
    expect(niceStep(1, 4)).toBe(0.25);
    expect(niceStep(4.3, 4)).toBe(2);
    expect(metreTicks(2.0, 3.0)).toEqual([2, 2.25, 2.5, 2.75, 3]);
    expect(metreTicks(0.85, 5.1).every((v) => v >= 0.85 && v <= 5.1)).toBe(true);
  });

  it('finds the row nearest a stage for the hover readout', () => {
    expect(nearestRow(AXIS, 2.71)).toBe(3);
    expect(nearestRow(AXIS, 9)).toBe(0);
  });
});
