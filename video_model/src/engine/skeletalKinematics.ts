/** Skeletal kinematics: FK, IK stub, angle lerp, 5-view projection, 13 presets.
 *
 *  Conventions:
 *  - Angle 0 = straight UP (+y world). Positive rotates clockwise.
 *  - view === "right": character faces camera-right (+x world).
 *  - view === "left": mirror; dir = -1.
 *  - view === "front" | "back": character faces camera; L/R spread symmetrically.
 *  - view === "perspective": 3/4 iso -- falls back to "front" for now.
 *
 *  World units are arbitrary; the renderer maps them to pixels.
 */

import type {
  BodyView,
  JointAngleMap,
  JointId,
  JointMetadata,
  JointPositions,
  PresetPoseName,
  SkeletonPose,
} from "../types";

// ====================================================================== metadata
const JOINT_ORDER: JointId[] = [
  "root", "spine_mid", "chest", "neck", "head",
  "shoulder_l", "elbow_l", "wrist_l", "hand_l",
  "shoulder_r", "elbow_r", "wrist_r", "hand_r",
  "hip_l", "knee_l", "ankle_l", "foot_l",
  "hip_r", "knee_r", "ankle_r", "foot_r",
];

const FK_ORDER: JointId[] = JOINT_ORDER.filter((j) => j !== "root");

const COLORS = {
  orange: "#f97316", emerald: "#10b981", cyan: "#06b6d4",
  crimson: "#ef4444", sky: "#0284c7", darkred: "#b91c1c",
};

export const JOINT_METADATA: Record<JointId, JointMetadata> = {
  root:      { id: "root",       name: "Root",       parentId: null,        side: "center", defaultLength: 0,   colorHint: COLORS.orange },
  spine_mid: { id: "spine_mid",  name: "Spine Mid",  parentId: "root",      side: "center", defaultLength: 18,  colorHint: COLORS.emerald, minAngle: -45, maxAngle: 45 },
  chest:     { id: "chest",      name: "Chest",      parentId: "spine_mid", side: "center", defaultLength: 22,  colorHint: COLORS.emerald, minAngle: -45, maxAngle: 45 },
  neck:      { id: "neck",       name: "Neck",       parentId: "chest",     side: "center", defaultLength: 8,   colorHint: COLORS.emerald, minAngle: -40, maxAngle: 40 },
  head:      { id: "head",       name: "Head",       parentId: "neck",      side: "center", defaultLength: 22,  colorHint: COLORS.emerald, minAngle: -50, maxAngle: 50 },
  shoulder_l:{ id: "shoulder_l", name: "Shoulder L", parentId: "chest",     side: "left",   defaultLength: 14,  colorHint: COLORS.cyan },
  elbow_l:   { id: "elbow_l",    name: "Elbow L",    parentId: "shoulder_l",side: "left",   defaultLength: 24,  colorHint: COLORS.cyan, minAngle: -160, maxAngle: 160 },
  wrist_l:   { id: "wrist_l",    name: "Wrist L",    parentId: "elbow_l",   side: "left",   defaultLength: 22,  colorHint: COLORS.cyan, minAngle: -90, maxAngle: 90 },
  hand_l:    { id: "hand_l",     name: "Hand L",     parentId: "wrist_l",   side: "left",   defaultLength: 8,   colorHint: COLORS.cyan },
  shoulder_r:{ id: "shoulder_r", name: "Shoulder R", parentId: "chest",     side: "right",  defaultLength: 14,  colorHint: COLORS.crimson },
  elbow_r:   { id: "elbow_r",    name: "Elbow R",    parentId: "shoulder_r",side: "right",  defaultLength: 24,  colorHint: COLORS.crimson, minAngle: -160, maxAngle: 160 },
  wrist_r:   { id: "wrist_r",    name: "Wrist R",    parentId: "elbow_r",   side: "right",  defaultLength: 22,  colorHint: COLORS.crimson, minAngle: -90, maxAngle: 90 },
  hand_r:    { id: "hand_r",     name: "Hand R",     parentId: "wrist_r",   side: "right",  defaultLength: 8,   colorHint: COLORS.crimson },
  hip_l:     { id: "hip_l",      name: "Hip L",      parentId: "root",      side: "left",   defaultLength: 10,  colorHint: COLORS.sky, minAngle: -120, maxAngle: 120 },
  knee_l:    { id: "knee_l",     name: "Knee L",     parentId: "hip_l",     side: "left",   defaultLength: 28,  colorHint: COLORS.sky, minAngle: -20, maxAngle: 160 },
  ankle_l:   { id: "ankle_l",    name: "Ankle L",    parentId: "knee_l",    side: "left",   defaultLength: 26,  colorHint: COLORS.sky, minAngle: -40, maxAngle: 130 },
  foot_l:    { id: "foot_l",     name: "Foot L",     parentId: "ankle_l",   side: "left",   defaultLength: 12,  colorHint: COLORS.sky },
  hip_r:     { id: "hip_r",      name: "Hip R",      parentId: "root",      side: "right",  defaultLength: 10,  colorHint: COLORS.darkred, minAngle: -120, maxAngle: 120 },
  knee_r:    { id: "knee_r",     name: "Knee R",     parentId: "hip_r",     side: "right",  defaultLength: 28,  colorHint: COLORS.darkred, minAngle: -20, maxAngle: 160 },
  ankle_r:   { id: "ankle_r",    name: "Ankle R",    parentId: "knee_r",    side: "right",  defaultLength: 26,  colorHint: COLORS.darkred, minAngle: -40, maxAngle: 130 },
  foot_r:    { id: "foot_r",     name: "Foot R",     parentId: "ankle_r",   side: "right",  defaultLength: 12,  colorHint: COLORS.darkred },
};

// ====================================================================== helpers
const degToRad = (d: number) => (d * Math.PI) / 180;

export function normalizeAngle(deg: number): number {
  let a = deg % 360;
  if (a > 180) a -= 360;
  if (a < -180) a += 360;
  return a;
}

export function lerpAngle(a: number, b: number, t: number): number {
  return a + normalizeAngle(b - a) * t;
}

export function lerpPoses(p: SkeletonPose, q: SkeletonPose, t: number): SkeletonPose {
  const keys = new Set<JointId>([...Object.keys(p.angles), ...Object.keys(q.angles)] as JointId[]);
  const angles: JointAngleMap = {};
  for (const k of keys) angles[k] = lerpAngle(p.angles[k] ?? 0, q.angles[k] ?? 0, t);
  return {
    id: `lerp-${t}`,
    rootX: p.rootX + (q.rootX - p.rootX) * t,
    rootY: p.rootY + (q.rootY - p.rootY) * t,
    view: q.view,
    scale: p.scale + (q.scale - p.scale) * t,
    angles,
  };
}

// ========================================================================== FK
/** Base direction for each joint's zero angle.
 *
 *  This is the single most important convention in the engine. The spine
 *  points UP from the pelvis (angle 0 = straight up), but the limbs point
 *  DOWN (angle 0 = straight down). Without this split, a standing figure
 *  draws its legs going up alongside its spine -- which is exactly the
 *  "scrambled with a pen" look: legs and spine overlapping in the same
 *  direction instead of the legs hanging below the pelvis.
 *
 *  A joint's world position is:
 *      x = parent.x + sin(abs) * L
 *      y = parent.y - baseSign * cos(abs) * L
 *  so baseSign +1 sends the bone up the screen and -1 sends it down.
 */
const BASE_SIGN: Record<JointId, 1 | -1> = {
  root: 1,
  spine_mid: 1, chest: 1, neck: 1, head: 1,        // spine: 0 = up
  shoulder_l: -1, elbow_l: -1, wrist_l: -1, hand_l: -1,   // arms: 0 = down
  shoulder_r: -1, elbow_r: -1, wrist_r: -1, hand_r: -1,
  hip_l: -1, knee_l: -1, ankle_l: -1, foot_l: -1,         // legs: 0 = down
  hip_r: -1, knee_r: -1, ankle_r: -1, foot_r: -1,
};

export interface ResolveOptions {
  canvasWidth: number;
  canvasHeight: number;
  /** Pixels per world unit. Default 2.4 -- a 1.6m figure fills ~480px tall. */
  pixelsPerUnit?: number;
}

export interface ResolvedScene {
  positions: JointPositions;
  view: BodyView;
  scale: number;
}

/** Resolve a pose to world-space joint positions in pixels.
 *
 *  Algorithm:
 *  1. Place root at (rootX, rootY) on the canvas.
 *  2. For each joint in FK order, compute its absolute angle as
 *     (parent's absolute angle + dir * local angle), then walk along that
 *     direction by defaultLength * scale * pixelsPerUnit.
 *  3. In "front" / "back" views, the shoulder_l/_r and hip_l/_r are re-anchored
 *     laterally before their FK chain runs, so the arms and legs spread
 *     symmetrically. In profile views, far-side joints get a small +x depth
 *     cue so the rig reads as 3-D, not flat.
 */
export function resolveSkeletonJoints(pose: SkeletonPose, opts: ResolveOptions): ResolvedScene {
  const ppu = opts.pixelsPerUnit ?? 2.4;
  const dir = pose.view === "left" ? -1 : 1;
  const rootX = (pose.rootX / 100) * opts.canvasWidth;
  const rootY = (pose.rootY / 100) * opts.canvasHeight;
  const shoulderWidth = 18 * pose.scale;
  const hipWidth = 12 * pose.scale;
  const profileDepth = 4 * pose.scale;

  const positions: JointPositions = {} as JointPositions;
  positions.root = { x: rootX, y: rootY };

  // Track absolute angles in a parallel map -- we don't want to mutate the
  // public JointPositions type with a private "_a" field.
  const absAngle: Record<string, number> = { root: 0 };

  // For front/back we re-anchor the shoulder and hip bilaterally before FK.
  if (pose.view === "front" || pose.view === "back") {
    positions.shoulder_l = { x: rootX - shoulderWidth, y: rootY - 18 * pose.scale };
    positions.shoulder_r = { x: rootX + shoulderWidth, y: rootY - 18 * pose.scale };
    positions.hip_l      = { x: rootX - hipWidth,      y: rootY };
    positions.hip_r      = { x: rootX + hipWidth,      y: rootY };
    // Mirror the limb angles: without this, a t-pose's left arm (authored +90,
    // i.e. toward +x) would extend INWARD from its left-of-centre anchor and
    // cross the body. Mirroring sends left limbs further left and right limbs
    // further right, which is what a bilateral view should look like.
    const m = -dir;
    absAngle.shoulder_l = degToRad(pose.angles.shoulder_l ?? 0) * m;
    absAngle.shoulder_r = degToRad(pose.angles.shoulder_r ?? 0) * m;
    absAngle.hip_l      = degToRad(pose.angles.hip_l      ?? 0) * m;
    absAngle.hip_r      = degToRad(pose.angles.hip_r      ?? 0) * m;
  }

  for (const j of FK_ORDER) {
    if (j in positions && absAngle[j] !== undefined) continue;
    const meta = JOINT_METADATA[j];
    const parent = positions[meta.parentId!];
    const L = meta.defaultLength * pose.scale * ppu;
    const localDeg = pose.angles[j] ?? 0;
    // Mirror limb angles in bilateral views so left limbs swing left and right
    // limbs swing right instead of crossing the body.
    const isLimb = meta.side === "left" || meta.side === "right";
    const mirror =
      (pose.view === "front" || pose.view === "back") && isLimb ? -1 : 1;
    const localA = degToRad(dir * localDeg * mirror);
    const parentAbs = absAngle[meta.parentId!] ?? 0;
    const abs = parentAbs + localA;
    absAngle[j] = abs;

    const sign = BASE_SIGN[j];
    let ox = Math.sin(abs) * L;
    let oy = -sign * Math.cos(abs) * L;

    // depth cue in profile views
    if (pose.view === "right" || pose.view === "left") {
      if (meta.side === "left")  ox -= profileDepth * dir;
      if (meta.side === "right") ox += profileDepth * dir;
    }

    positions[j] = { x: parent.x + ox, y: parent.y + oy };
  }

  return { positions, view: pose.view, scale: pose.scale };
}

// ========================================================================== IK
export interface IKResult {
  origin: JointId;
  middle: JointId;
  end: JointId;
  angles: JointAngleMap;
  outOfReach: boolean;
}

/** Analytical 2-bone IK. Given an end-effector target in world pixels, returns the
 *  angle overrides for the two parent joints so the chain reaches the target.
 *  Out-of-reach targets are clamped and `outOfReach` is set true. */
export function solveTwoBoneIK(opts: {
  origin: { x: number; y: number };
  middle: JointId;
  end: { x: number; y: number };
  pose: SkeletonPose;
  bend?: 1 | -1;
}): IKResult {
  const mMeta = JOINT_METADATA[opts.middle];
  const originId = mMeta.parentId ?? "root";
  const oMeta = JOINT_METADATA[originId];
  // The end-effector is the joint whose parent is `opts.middle`. Find it.
  const endId = (Object.keys(JOINT_METADATA) as JointId[]).find(
    (j) => JOINT_METADATA[j].parentId === opts.middle,
  ) ?? opts.middle;
  const L1 = oMeta.defaultLength * opts.pose.scale;
  const L2 = mMeta.defaultLength * opts.pose.scale;
  void L1; void L2; void endId;

  const dx = opts.end.x - opts.origin.x;
  const dy = opts.end.y - opts.origin.y;
  const D = Math.hypot(dx, dy);
  const reach = L1 + L2;
  const outOfReach = D > reach;
  const Dc = Math.max(Math.abs(L1 - L2) * 1.001, Math.min(reach * 0.999, D));
  const base = Math.atan2(dx, -dy);
  const cosA = (L1 * L1 + Dc * Dc - L2 * L2) / (2 * L1 * Dc);
  const cosG = (L1 * L1 + L2 * L2 - Dc * Dc) / (2 * L1 * L2);
  const alpha = Math.acos(Math.max(-1, Math.min(1, cosA)));
  const gamma = Math.acos(Math.max(-1, Math.min(1, cosG)));
  const bend = opts.bend ?? 1;
  const a1 = base + bend * alpha;
  const a2 = bend * (Math.PI - gamma);
  return {
    origin: originId,
    middle: opts.middle,
    end: endId,
    angles: { [originId]: (a1 * 180) / Math.PI, [opts.middle]: (a2 * 180) / Math.PI },
    outOfReach,
  };
}

// ===================================================================== presets
export const PRESET_POSES: Record<PresetPoseName, { label: string; description: string; angles: JointAngleMap; rootY?: number }> = {
  stand: { label: "Stand", description: "Natural upright stance.",
    angles: { shoulder_l: 0, elbow_l: -8, wrist_l: 0, hand_l: 0,
             shoulder_r: 0, elbow_r: 8, wrist_r: 0, hand_r: 0,
             hip_l: 0, knee_l: 0, ankle_l: 0, foot_l: 0,
             hip_r: 0, knee_r: 0, ankle_r: 0, foot_r: 0 } },
  sit_chair: { label: "Sit (Chair)", description: "90° hip flexion, vertical feet.",
    angles: { hip_l: -90, hip_r: -90, knee_l: 88, knee_r: 88, ankle_l: 0, ankle_r: 0 }, rootY: 70 },
  sit_floor: { label: "Sit (Floor)", description: "Cross-legged lotus.",
    angles: { hip_l: -95, hip_r: 95, knee_l: 125, knee_r: -125, ankle_l: 0, ankle_r: 0 }, rootY: 80 },
  walk_contact: { label: "Walk Contact", description: "Heel strike, reciprocal arm swing.",
    angles: { hip_l: -10, hip_r: 10, knee_l: 10, knee_r: -5, ankle_l: 0, ankle_r: 5,
             shoulder_l: 15, elbow_l: 10, wrist_l: 0, hand_l: 0,
             shoulder_r: -15, elbow_r: -10, wrist_r: 0, hand_r: 0 } },
  walk_passing: { label: "Walk Passing", description: "Airborne knee swings through.",
    angles: { hip_l: 5, hip_r: -5, knee_l: 60, knee_r: 0, ankle_l: -10, ankle_r: 0,
             shoulder_l: -10, shoulder_r: 10, elbow_l: -10, elbow_r: 10 } },
  run: { label: "Run", description: "Forward lean, high knee drive, pumped elbows.",
    angles: { spine_mid: 6, chest: 8,
             hip_l: 10, hip_r: -10, knee_l: 70, knee_r: 20, ankle_l: -15, ankle_r: -5,
             shoulder_l: -65, elbow_l: -90,
             shoulder_r: 65, elbow_r: 90 } },
  jump: { label: "Jump", description: "Coiled spine, raised arms.",
    angles: { spine_mid: -8, chest: -6,
             hip_l: 25, hip_r: -25, knee_l: 60, knee_r: 60, ankle_l: 10, ankle_r: 10,
             shoulder_l: -120, elbow_l: -30, shoulder_r: -120, elbow_r: -30 } },
  crouch: { label: "Crouch", description: "Low center of gravity.",
    angles: { hip_l: -75, hip_r: -75, knee_l: 105, knee_r: 105, ankle_l: 0, ankle_r: 0 }, rootY: 75 },
  punch: { label: "Punch", description: "Grounded stance, straight lead jab.",
    angles: { hip_l: -10, hip_r: 0, knee_l: 10, knee_r: 0,
             shoulder_l: -95, elbow_l: -10, wrist_l: 0, hand_l: 0 } },
  kick: { label: "Kick", description: "Rooted support, high extension.",
    angles: { spine_mid: -4, chest: -3,
             hip_l: 0, hip_r: 0, knee_l: 10, knee_r: 95, ankle_l: 0, ankle_r: 0,
             shoulder_l: 30, shoulder_r: -30, elbow_l: -10, elbow_r: 10 } },
  wave: { label: "Wave", description: "One arm elevated, wrist greeting.",
    angles: { shoulder_r: -140, elbow_r: -45, wrist_r: 0, hand_r: 0 } },
  sword_thrust: { label: "Sword Thrust", description: "Lunging thrust aligned with forearm.",
    angles: { spine_mid: 4, hip_l: -30, hip_r: 10, knee_l: 45, knee_r: -5,
             shoulder_r: 30, elbow_r: -10, wrist_r: 0, hand_r: 0 } },
  t_pose: { label: "T-Pose", description: "Standard horizontal calibration.",
    angles: { shoulder_l: 90, elbow_l: 0, wrist_l: 0, hand_l: 0,
             shoulder_r: -90, elbow_r: 0, wrist_r: 0, hand_r: 0 } },
};

export function applyPreset(name: PresetPoseName): SkeletonPose {
  const p = PRESET_POSES[name];
  return {
    id: `preset-${name}`,
    name: p.label,
    rootX: 50,
    rootY: p.rootY ?? 65,
    view: "right",
    scale: 1.0,
    angles: { ...p.angles },
  };
}