/** Canvas2D renderer for TextAnim.
 *
 *  Visual contract: a clean, simple stickman. One head circle, one spine
 *  line (head to root), two jointed arm chains, two jointed leg chains, and a
 *  subtle floor. NO body-width lines, NO near/far depth shading -- the
 *  reference pose sheet is the gold standard and it is minimal.
 *
 *  Bone topology: this file KNOWS which bones connect which joints and which
 *  lines the stickman should actually draw. It does not know how the joints
 *  were positioned -- the kinematics engine hands it world coordinates.
 *
 *  Drawing model: a single pass, one stroke per bone. Round line caps so
 *  joints look clean. Optional joint handles drawn as small dots if the
 *  appearance config requests them.
 */

import type {
  AppearanceConfig,
  JointId,
} from "../types";
import {
  JOINT_METADATA,
  type ResolvedScene,
} from "./skeletalKinematics";

/** The bones the stickman actually draws. Every other bone is part of the FK
 *  tree but is invisible on screen -- a clean stickman has ten visible lines,
 *  not twenty. */
const STICK_BONES: Array<[JointId, JointId]> = [
  // spine: one line from pelvis to head
  ["root", "spine_mid"],
  ["spine_mid", "chest"],
  ["chest", "neck"],
  ["neck", "head"],
  // left arm: shoulder -> elbow -> wrist -> hand
  ["chest", "shoulder_l"], ["shoulder_l", "elbow_l"],
  ["elbow_l", "wrist_l"], ["wrist_l", "hand_l"],
  // right arm
  ["chest", "shoulder_r"], ["shoulder_r", "elbow_r"],
  ["elbow_r", "wrist_r"], ["wrist_r", "hand_r"],
  // left leg: hip -> knee -> ankle -> foot
  ["root", "hip_l"], ["hip_l", "knee_l"],
  ["knee_l", "ankle_l"], ["ankle_l", "foot_l"],
  // right leg
  ["root", "hip_r"], ["hip_r", "knee_r"],
  ["knee_r", "ankle_r"], ["ankle_r", "foot_r"],
];

export interface RenderOptions {
  cfg: AppearanceConfig;
}

export function renderStickmanScene(
  ctx: CanvasRenderingContext2D,
  scene: ResolvedScene,
  opts: RenderOptions,
): void {
  const { cfg } = opts;
  const W = ctx.canvas.width;
  const H = ctx.canvas.height;

  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#0b1220";
  ctx.fillRect(0, 0, W, H);

  if (cfg.showGrid) {
    ctx.strokeStyle = "#1f2a44";
    ctx.lineWidth = 1;
    for (let x = 0; x < W; x += 40) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let y = 0; y < H; y += 40) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }
  }

  if (cfg.showFloor) {
    const fy = (cfg.floorY / 100) * H;
    ctx.strokeStyle = "#334155";
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(0, fy); ctx.lineTo(W, fy); ctx.stroke();
  }

  // All limbs use the same ink and the same stroke width. The reference pose
  // sheet draws the figure as one continuous weight; we do the same.
  ctx.strokeStyle = cfg.primaryColor;
  ctx.lineWidth = cfg.lineWidth;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  for (const [a, b] of STICK_BONES) {
    drawBone(ctx, scene, a, b);
  }

  // Head circle sits on top of the neck.
  const head = scene.positions.head;
  ctx.beginPath();
  ctx.arc(head.x, head.y, cfg.headRadius, 0, Math.PI * 2);
  ctx.stroke();

  // Optional joint handles (small dots) when the inspector is visible.
  if (cfg.showHandles) {
    ctx.fillStyle = cfg.jointColor;
    for (const j of Object.keys(JOINT_METADATA) as JointId[]) {
      const p = scene.positions[j];
      ctx.beginPath();
      ctx.arc(p.x, p.y, Math.max(2, cfg.jointRadius - 1), 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function drawBone(
  ctx: CanvasRenderingContext2D,
  scene: ResolvedScene,
  a: JointId, b: JointId,
): void {
  const pa = scene.positions[a];
  const pb = scene.positions[b];
  if (!pa || !pb) return;
  ctx.beginPath();
  ctx.moveTo(pa.x, pa.y);
  ctx.lineTo(pb.x, pb.y);
  ctx.stroke();
}