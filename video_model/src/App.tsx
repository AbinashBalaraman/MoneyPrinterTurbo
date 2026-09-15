import { useState } from "react";
import { SkeletalCanvas } from "./components/SkeletalCanvas";
import { applyPreset, PRESET_POSES } from "./engine/skeletalKinematics";
import type { AppearanceConfig, BodyView, SkeletonPose } from "./types";

/** Phase 1 shell. Loads the t-pose, hosts the canvas, exposes the 5-view
 *  switcher and the preset bar so you can see the engine doing work. Nothing
 *  here saves to disk, plays an animation, or drags joints -- that's Phase 2. */

const DEFAULT_CFG: AppearanceConfig = {
  rig: "classic",
  primaryColor: "#22d3ee",
  accentColor: "#475569",
  jointColor: "#f97316",
  lineWidth: 3,
  jointRadius: 4,
  headRadius: 14,
  showHandles: false,
  showGrid: true,
  showFloor: true,
  floorY: 90,
  onionSkinning: false,
  onionSkinOpacity: 0.4,
  useIK: false,
};

const VIEWS: BodyView[] = ["right", "left", "front", "back", "perspective"];

export function App() {
  const [pose, setPose] = useState<SkeletonPose>(() => applyPreset("t_pose"));
  const [cfg, setCfg] = useState<AppearanceConfig>(DEFAULT_CFG);

  return (
    <div className="flex flex-col h-screen text-slate-100 bg-slate-900">
      <header className="flex items-center justify-between px-4 py-2 border-b border-slate-800 bg-slate-900/80 backdrop-blur">
        <div className="flex items-center gap-3">
          <div className="w-2.5 h-2.5 rounded-full bg-accent animate-pulse" />
          <h1 className="text-lg font-semibold tracking-tight">TextAnim</h1>
          <span className="text-xs text-slate-400">2D Skeletal Studio · Phase 1</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <select
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1"
            value={pose.view}
            onChange={(e) => setPose({ ...pose, view: e.target.value as BodyView })}
          >
            {VIEWS.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
          <button
            className="px-2 py-1 rounded border border-slate-700 bg-slate-800 hover:bg-slate-700"
            onClick={() => setCfg({ ...cfg, showHandles: !cfg.showHandles })}
          >
            {cfg.showHandles ? "Hide Handles" : "Show Handles"}
          </button>
        </div>
      </header>

      <div className="flex flex-1 min-h-0">
        <aside className="w-64 border-r border-slate-800 bg-slate-900/40 overflow-y-auto p-3 space-y-3">
          <section>
            <h2 className="text-xs uppercase tracking-wider text-slate-400 mb-2">Presets</h2>
            <div className="grid grid-cols-2 gap-1.5">
              {(Object.entries(PRESET_POSES) as [keyof typeof PRESET_POSES, typeof PRESET_POSES[keyof typeof PRESET_POSES]][]).map(
                ([name, info]) => (
                  <button
                    key={name}
                    onClick={() => setPose(applyPreset(name))}
                    className={`text-left text-xs rounded px-2 py-1.5 border transition ${
                      pose.id === `preset-${name}`
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-slate-700 bg-slate-800 hover:bg-slate-700"
                    }`}
                  >
                    <div className="font-medium">{info.label}</div>
                    <div className="text-[10px] text-slate-400 truncate">{info.description}</div>
                  </button>
                ),
              )}
            </div>
          </section>
        <section>
            <h2 className="text-xs uppercase tracking-wider text-slate-400 mb-2">Appearance</h2>
            <div className="space-y-2 text-xs">
              <label className="flex items-center justify-between gap-2">
                <span className="text-slate-300">Rig</span>
                <select
                  className="bg-slate-800 border border-slate-700 rounded px-2 py-1"
                  value={cfg.rig}
                  onChange={(e) => setCfg({ ...cfg, rig: e.target.value as AppearanceConfig["rig"] })}
                >
                  <option value="classic">classic</option>
                </select>
              </label>
              <label className="flex items-center justify-between gap-2">
                <span className="text-slate-300">Stroke</span>
                <input
                  type="range" min={1} max={8} value={cfg.lineWidth}
                  onChange={(e) => setCfg({ ...cfg, lineWidth: Number(e.target.value) })}
                />
                <span className="text-slate-400 w-6 text-right">{cfg.lineWidth}</span>
              </label>
              <label className="flex items-center justify-between gap-2">
                <span className="text-slate-300">Head</span>
                <input
                  type="range" min={6} max={28} value={cfg.headRadius}
                  onChange={(e) => setCfg({ ...cfg, headRadius: Number(e.target.value) })}
                />
                <span className="text-slate-400 w-6 text-right">{cfg.headRadius}</span>
              </label>
              <label className="flex items-center justify-between gap-2">
                <span className="text-slate-300">Floor</span>
                <input
                  type="range" min={50} max={99} value={cfg.floorY}
                  onChange={(e) => setCfg({ ...cfg, floorY: Number(e.target.value) })}
                />
                <span className="text-slate-400 w-6 text-right">{cfg.floorY}%</span>
              </label>
            </div>
          </section>
        </aside>

        <main className="flex-1 min-w-0 bg-canvas relative">
          <SkeletalCanvas pose={pose} cfg={cfg} onPoseChange={setPose} />
          <div className="absolute bottom-2 left-2 text-[10px] font-mono text-slate-500 bg-slate-900/60 px-1.5 py-0.5 rounded">
            {pose.id} · {pose.view} · {Object.keys(pose.angles).length} angles
          </div>
        </main>

        <aside className="w-72 border-l border-slate-800 bg-slate-900/40 overflow-y-auto p-3">
          <h2 className="text-xs uppercase tracking-wider text-slate-400 mb-2">Skeleton Inspector</h2>
          <SkeletonInspector pose={pose} onChange={(angles) => setPose({ ...pose, angles })} />
        </aside>
      </div>
    </div>
  );
}

function SkeletonInspector(props: {
  pose: SkeletonPose;
  onChange: (angles: SkeletonPose["angles"]) => void;
}) {
  const groups: Array<[string, Array<keyof typeof props.pose.angles>]> = [
    ["Spine & Head", ["spine_mid", "chest", "neck", "head"]],
    ["Left Arm", ["shoulder_l", "elbow_l", "wrist_l", "hand_l"]],
    ["Right Arm", ["shoulder_r", "elbow_r", "wrist_r", "hand_r"]],
    ["Left Leg", ["hip_l", "knee_l", "ankle_l", "foot_l"]],
    ["Right Leg", ["hip_r", "knee_r", "ankle_r", "foot_r"]],
  ];
  return (
    <div className="space-y-3">
      {groups.map(([title, keys]) => (
        <section key={title} className="border border-slate-800 rounded p-2 bg-slate-900/30">
          <h3 className="text-[11px] uppercase tracking-wider text-slate-400 mb-1.5">{title}</h3>
          <div className="space-y-1">
            {keys.map((k) => (
              <JointSlider key={k} id={k} pose={props.pose} onChange={props.onChange} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function JointSlider(props: {
  id: keyof import("./types").SkeletonPose["angles"];
  pose: import("./types").SkeletonPose;
  onChange: (angles: import("./types").SkeletonPose["angles"]) => void;
}) {
  const v = props.pose.angles[props.id] ?? 0;
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="font-mono text-slate-300 w-20 truncate">{props.id}</span>
      <input
        type="range" min={-180} max={180} step={1} value={v}
        onChange={(e) => props.onChange({ ...props.pose.angles, [props.id]: Number(e.target.value) })}
        className="flex-1 accent-accent"
      />
      <span className="font-mono text-slate-400 w-10 text-right">{v}°</span>
    </div>
  );
}