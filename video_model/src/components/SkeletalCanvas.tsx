import { useEffect, useRef } from "react";
import type { AppearanceConfig, JointId, SkeletonPose } from "../types";
import {
  JOINT_METADATA,
  resolveSkeletonJoints,
  solveTwoBoneIK,
} from "../engine/skeletalKinematics";
import { renderStickmanScene } from "../engine/skeletalRenderer";

interface Props {
  pose: SkeletonPose;
  cfg: AppearanceConfig;
  onPoseChange: (next: SkeletonPose) => void;
}

/** The animated stage. Hosts an HTML5 canvas, sizes it to the parent, applies
 *  DPR for crisp lines, and re-renders the stickman whenever the pose or
 *  appearance changes.
 *
 *  Phase 2 drag:
 *  - End-effectors (hand_l/r, foot_l/r, head) drag via solveTwoBoneIK when
 *    cfg.useIK is true.
 *  - Intermediate joints drag in FK mode (relative to their parent's world
 *    position) otherwise. The drag rotates the joint around its parent pivot.
 *  - Root (the orange pelvis pivot) translates the whole figure with +4 px
 *    bonus radius for easy grabbing.
 */
export function SkeletalCanvas({ pose, cfg, onPoseChange }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const poseRef = useRef(pose);
  const cfgRef = useRef(cfg);
  poseRef.current = pose;
  cfgRef.current = cfg;

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    type Drag =
      | { kind: "ik"; jointId: JointId; pointerId: number }
      | { kind: "fk"; jointId: JointId; parentId: JointId; parentAbsRad: number; pointerId: number }
      | { kind: "root"; dx: number; dy: number; pointerId: number }
      | null;
    let drag: Drag = null;

    const draw = () => {
      const cssW = wrap.clientWidth;
      const cssH = wrap.clientHeight;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(cssW * dpr));
      canvas.height = Math.max(1, Math.floor(cssH * dpr));
      canvas.style.width = `${cssW}px`;
      canvas.style.height = `${cssH}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const scene = resolveSkeletonJoints(poseRef.current, {
        canvasWidth: cssW,
        canvasHeight: cssH,
      });
      renderStickmanScene(ctx, scene, { cfg: cfgRef.current });
    };

    const observer = new ResizeObserver(() => draw());
    observer.observe(wrap);
    draw();

    const opts = () => ({
      canvasWidth: wrap.clientWidth,
      canvasHeight: wrap.clientHeight,
    });

    const cssX = (clientX: number) => clientX - canvas.getBoundingClientRect().left;
    const cssY = (clientY: number) => clientY - canvas.getBoundingClientRect().top;

    function hit(x: number, y: number): { id: JointId; r: number } | null {
      const r = cfgRef.current.jointRadius;
      const scene = resolveSkeletonJoints(poseRef.current, opts());
      // Priority: root gets a +4 px bonus for easy grabbing.
      const root = scene.positions.root;
      if (Math.hypot(root.x - x, root.y - y) <= r + 4) return { id: "root", r };
      // End-effectors next.
      for (const id of ["head", "hand_l", "hand_r", "foot_l", "foot_r"] as JointId[]) {
        const p = scene.positions[id];
        if (Math.hypot(p.x - x, p.y - y) <= r * 1.5) return { id, r };
      }
      // All other joints.
      for (const j of Object.keys(scene.positions) as JointId[]) {
        const p = scene.positions[j];
        if (Math.hypot(p.x - x, p.y - y) <= r) return { id: j, r };
      }
      return null;
    }

    const onDown = (e: PointerEvent) => {
      const hit_ = hit(cssX(e.clientX), cssY(e.clientY));
      if (!hit_) return;
      canvas.setPointerCapture(e.pointerId);
      if (hit_.id === "root") {
        drag = { kind: "root", dx: cssX(e.clientX), dy: cssY(e.clientY), pointerId: e.pointerId };
        return;
      }
      if (cfgRef.current.useIK && ["head", "hand_l", "hand_r", "foot_l", "foot_r"].includes(hit_.id)) {
        drag = { kind: "ik", jointId: hit_.id, pointerId: e.pointerId };
        return;
      }
      const parent = JOINT_METADATA[hit_.id].parentId;
      if (!parent) return;
      // Current parent absolute angle (sum of local angles up the chain).
      const parentAbsRad = absAngleAt(parent, poseRef.current);
      drag = { kind: "fk", jointId: hit_.id, parentId: parent, parentAbsRad, pointerId: e.pointerId };
    };

    const onMove = (e: PointerEvent) => {
      if (!drag || drag.pointerId !== e.pointerId) return;
      const x = cssX(e.clientX);
      const y = cssY(e.clientY);
      const cur = poseRef.current;
      const dir = cur.view === "left" ? -1 : 1;

      if (drag.kind === "root") {
        const W = opts().canvasWidth;
        const H = opts().canvasHeight;
        const dx = (x - drag.dx) / W * 100;
        const dy = (y - drag.dy) / H * 100;
        onPoseChange({ ...cur, rootX: cur.rootX + dx, rootY: cur.rootY + dy });
        drag.dx = x; drag.dy = y;
        return;
      }

      if (drag.kind === "ik") {
        const joint = drag.jointId;
        const middle = JOINT_METADATA[joint].parentId;
        if (!middle || middle === "root") return;
        const origin = JOINT_METADATA[middle].parentId;
        if (!origin || origin === "root") return;
        const scene = resolveSkeletonJoints(cur, opts());
        const originPos = scene.positions[origin as JointId];
        const result = solveTwoBoneIK({
          origin: originPos,
          middle,
          end: { x, y },
          pose: cur,
          bend: 1,
        });
        onPoseChange({ ...cur, angles: { ...cur.angles, ...result.angles } });
        return;
      }

      if (drag.kind === "fk") {
        // Recompute the parent's world position from the CURRENT pose each move,
        // so the FK drag tracks the joint as it rotates.
        const parentPos = resolveSkeletonJoints(cur, opts()).positions[drag.parentId];
        // The local angle that puts the joint at (x,y) about its parent.
        const dx = x - parentPos.x;
        const dy = y - parentPos.y;
        // 0 = straight up (+y). Atan2(x, -y) gives that. Then subtract parent's
        // absolute to get the LOCAL angle, then apply view direction.
        const worldRad = Math.atan2(dx * dir, -dy);
        let localDeg = ((worldRad - drag.parentAbsRad) * 180) / Math.PI;
        localDeg = localDeg * dir;
        onPoseChange({ ...cur, angles: { ...cur.angles, [drag.jointId]: localDeg } });
      }
    };

    const onUp = (e: PointerEvent) => {
      if (drag && drag.pointerId === e.pointerId) {
        canvas.releasePointerCapture(e.pointerId);
        drag = null;
      }
    };

    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointercancel", onUp);

    const onCfgChange = () => draw();
    const cfgObserver = new ResizeObserver(onCfgChange);
    cfgObserver.observe(wrap);

    return () => {
      observer.disconnect();
      cfgObserver.disconnect();
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointercancel", onUp);
    };
  }, []);

  // Re-render on pose/cfg changes via a separate effect so the drag handler
  // stays stable.
  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = wrap.clientWidth;
    const cssH = wrap.clientHeight;
    canvas.width = Math.max(1, Math.floor(cssW * dpr));
    canvas.height = Math.max(1, Math.floor(cssH * dpr));
    canvas.style.width = `${cssW}px`;
    canvas.style.height = `${cssH}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const scene = resolveSkeletonJoints(pose, { canvasWidth: cssW, canvasHeight: cssH });
    renderStickmanScene(ctx, scene, { cfg });
  }, [pose, cfg]);

  return (
    <div ref={wrapRef} className="relative w-full h-full">
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />
    </div>
  );
}

/** Sum of the local angles from root down to (and not including) `id`. */
function absAngleAt(id: JointId, pose: SkeletonPose): number {
  const meta = JOINT_METADATA[id];
  if (!meta.parentId) return 0;
  const parentDeg = pose.angles[meta.parentId] ?? 0;
  const dir = pose.view === "left" ? -1 : 1;
  // Recursively walk up. The parent's absolute angle is its parent's absolute
  // angle plus its own local angle (sign-flipped for "left" view).
  return absAngleAt(meta.parentId, pose) + dir * ((parentDeg * Math.PI) / 180);
}