/** Universal type contracts for TextAnim. The state, the rig, and the renderer
 *  all agree on these shapes -- no file imports another file's domain types. */

/** Every named joint in the rig. The rig is a 21-joint tree, which is what the
 *  architecture calls "17 points" plus the four-terminal foot/hand joints. */
export type JointId =
  | "root"
  | "spine_mid"
  | "chest"
  | "neck"
  | "head"
  | "shoulder_l"
  | "elbow_l"
  | "wrist_l"
  | "hand_l"
  | "shoulder_r"
  | "elbow_r"
  | "wrist_r"
  | "hand_r"
  | "hip_l"
  | "knee_l"
  | "ankle_l"
  | "foot_l"
  | "hip_r"
  | "knee_r"
  | "ankle_r"
  | "foot_r";

export type BodySide = "center" | "left" | "right";

export type BodyView = "right" | "left" | "front" | "back" | "perspective";

export interface JointMetadata {
  id: JointId;
  name: string;
  parentId: JointId | null;
  side: BodySide;
  defaultLength: number;
  colorHint: string;
  minAngle?: number;
  maxAngle?: number;
}

export type JointAngleMap = Partial<Record<JointId, number>>;

export interface SkeletonPose {
  id: string;
  name?: string;
  rootX: number;
  rootY: number;
  view: BodyView;
  scale: number;
  angles: JointAngleMap;
  holdingItem?: "none" | "katana" | "staff" | "ball";
}

export interface AnimationKeyframe {
  id: string;
  frameIndex: number;
  timestampMs: number;
  pose: SkeletonPose;
  caption?: string;
}

export interface AnimationClip {
  id: string;
  name: string;
  fps: number;
  isLooping: boolean;
  smoothPlayback: boolean;
  frames: AnimationKeyframe[];
}

export type AppearanceRig =
  | "classic"
  | "articulated"
  | "shadow_ninja"
  | "cyber_neon"
  | "minimal_ink";

export interface AppearanceConfig {
  rig: AppearanceRig;
  primaryColor: string;
  accentColor: string;
  jointColor: string;
  lineWidth: number;
  jointRadius: number;
  headRadius: number;
  showHandles: boolean;
  showGrid: boolean;
  showFloor: boolean;
  floorY: number;
  onionSkinning: boolean;
  onionSkinOpacity: number;
  useIK: boolean;
}

export type PresetPoseName =
  | "stand"
  | "sit_chair"
  | "sit_floor"
  | "walk_contact"
  | "walk_passing"
  | "run"
  | "jump"
  | "crouch"
  | "punch"
  | "kick"
  | "wave"
  | "sword_thrust"
  | "t_pose";

/** A flat array of 2D world positions for the 21 joints, in joint-id order. */
export type JointPositions = Record<JointId, { x: number; y: number }>;