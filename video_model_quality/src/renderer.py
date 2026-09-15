"""Deterministic 2D stickman renderer & video encoder.

Renders motion features (T, 30) or (T, 60) into antialiased 512x512 24fps MP4 videos.
Features:
- 2x supersampling with Lanczos downsampling for clean, antialiased lines.
- Smooth camera tracking to eliminate canvas exit during long locomotion.
- Dynamic ground contact drop shadows with airborne height scaling.
- Expanded procedural prop kit: sword, tree, chair, ball, background crowd.
- Direct ffmpeg pipe for fast, lossless encoding without intermediate disk files.
"""

import os
import subprocess
import numpy as np
from PIL import Image, ImageDraw

from .rig import decode, forward_kinematics, BONES, FPS, CLIP_LEN_5S, GROUND_Y

# Bone connections matching rig.py hierarchy (joint_a, joint_b)
# Joints:
# 0: pelvis (root)
# 1: spine, 2: chest, 3: neck, 4: head
# 5: elbowL, 6: handL
# 7: elbowR, 8: handR
# 9: kneeL, 10: ankleL, 11: toeL
# 12: kneeR, 13: ankleR, 14: toeR
BONE_SEGMENTS = [
    # Torso
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 4),  # Neck to Head center
    # Left Arm
    (2, 5),
    (5, 6),
    # Right Arm
    (2, 7),
    (7, 8),
    # Left Leg
    (0, 9),
    (9, 10),
    (10, 11),
    # Right Leg
    (0, 12),
    (12, 13),
    (13, 14),
]

# Color themes (RGB)
DEFAULT_PALETTES = [
    {"body": (20, 20, 20), "head": (20, 20, 20)},       # Person 1: Charcoal / Black
    {"body": (160, 25, 25), "head": (160, 25, 25)},     # Person 2: Crimson Red
]

GROUND_COLOR = (215, 215, 215)
BACKGROUND_COLOR = (255, 255, 255)
SHADOW_BASE_COLOR = (200, 200, 200)

# World coordinate mapping defaults
WORLD_GROUND_Y = GROUND_Y  # single source of truth: derived from the rig rest pose
CANVAS_GROUND_RATIO = 0.82  # Ground plane at ~82% height of canvas
DEFAULT_SCALE = 250.0  # Pixels per world unit (character height ~1.0 => ~250px)


def apply_contact_correction(joints_all, ground_y=WORLD_GROUND_Y):
    """Ensure characters do not penetrate beneath the ground plane.
    
    joints_all: (T, N, 15, 2)
    Returns corrected copy of joints_all.
    """
    joints = np.copy(joints_all)
    T, N, _, _ = joints.shape
    foot_indices = [10, 11, 13, 14]
    
    for t in range(T):
        for n in range(N):
            feet_y = joints[t, n, foot_indices, 1]
            min_y = np.min(feet_y)
            if min_y < ground_y:
                penetration = ground_y - min_y
                joints[t, n, :, 1] += penetration
    return joints


class StickmanRenderer:
    """Renders 2D stickman joints to images and MP4 videos with cinematic polish."""

    def __init__(self, canvas_size=512, supersample=2, ground_y=WORLD_GROUND_Y,
                 bg_color=BACKGROUND_COLOR, line_width=4.0, head_radius=18.0):
        self.canvas_size = canvas_size
        self.ss = supersample
        self.render_size = canvas_size * supersample
        self.ground_y_world = ground_y
        self.canvas_ground_y = int(self.render_size * CANVAS_GROUND_RATIO)
        self.scale = DEFAULT_SCALE * supersample
        self.center_x = self.render_size // 2
        self.bg_color = bg_color
        self.line_width = int(line_width * supersample)
        self.head_radius = int(head_radius * supersample)

    def world_to_canvas(self, points, camera_x=0.0):
        """Convert world coordinates (..., 2) to canvas pixel coordinates with camera offset."""
        pts = np.asarray(points, dtype=np.float32)
        cx = self.center_x + (pts[..., 0] - camera_x) * self.scale
        cy = self.canvas_ground_y - (pts[..., 1] - self.ground_y_world) * self.scale
        return np.stack([cx, cy], axis=-1)

    def draw_drop_shadow(self, draw, joints_2d, joints_world):
        """Draw dynamic ground drop shadow scaled by airborne elevation."""
        root_y = joints_world[0, 1]
        elevation = max(0.0, float(root_y))  # Root elevation above pelvis rest (0.0)
        
        # Shadow shrinks and fades as character jumps higher
        factor = 1.0 / (1.0 + 3.0 * elevation)
        shadow_w = int(48 * self.ss * (0.35 + 0.65 * factor))
        shadow_h = max(2, int(9 * self.ss * factor))
        
        # Anchor shadow horizontally under pelvis
        pelvis_cx = float(joints_2d[0, 0])
        ground_cy = self.canvas_ground_y
        
        # Shadow color interpolates towards white with height
        gray = int(170 + (245 - 170) * (1.0 - factor))
        shadow_col = (gray, gray, gray)
        
        draw.ellipse([pelvis_cx - shadow_w, ground_cy - shadow_h,
                      pelvis_cx + shadow_w, ground_cy + shadow_h], fill=shadow_col)

    def draw_stickman(self, draw, joints_2d, palette):
        """Draw a single stickman on Pillow ImageDraw."""
        body_col = palette.get("body", (20, 20, 20))
        head_col = palette.get("head", (20, 20, 20))
        half_w = max(1, self.line_width // 2)

        # Draw bones
        for ja, jb in BONE_SEGMENTS:
            pt_a = (float(joints_2d[ja, 0]), float(joints_2d[ja, 1]))
            pt_b = (float(joints_2d[jb, 0]), float(joints_2d[jb, 1]))
            draw.line([pt_a, pt_b], fill=body_col, width=self.line_width)

        # Draw smooth joint rounded caps
        for j_idx in range(15):
            if j_idx == 4:
                continue
            x, y = float(joints_2d[j_idx, 0]), float(joints_2d[j_idx, 1])
            draw.ellipse([x - half_w, y - half_w, x + half_w, y + half_w], fill=body_col)

        # Draw head circle
        hx, hy = float(joints_2d[4, 0]), float(joints_2d[4, 1])
        hr = self.head_radius
        draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=head_col, outline=body_col, width=max(1, self.line_width // 2))

    def draw_prop(self, draw, prop, camera_x=0.0):
        """Draw procedural props: sword, tree, chair, ball, crowd."""
        kind = prop.get("kind", "")
        px = prop.get("x", 0.0)
        py = prop.get("y", self.ground_y_world)
        cpt = self.world_to_canvas(np.array([[px, py]]), camera_x=camera_x)[0]
        
        if kind == "tree":
            trunk_w = max(2, int(6 * self.ss))
            trunk_h = int(120 * self.ss)
            draw.line([(cpt[0], cpt[1]), (cpt[0], cpt[1] - trunk_h)], fill=(120, 100, 80), width=trunk_w)
            # Foliage circle
            foliage_r = int(45 * self.ss)
            fc_y = cpt[1] - trunk_h - int(10 * self.ss)
            draw.ellipse([cpt[0] - foliage_r, fc_y - foliage_r, cpt[0] + foliage_r, fc_y + foliage_r],
                         fill=(70, 140, 70), outline=(50, 110, 50), width=max(1, int(2 * self.ss)))

        elif kind == "chair":
            cw = int(24 * self.ss)
            ch = int(40 * self.ss)
            leg_w = max(1, int(2 * self.ss))
            col = (130, 90, 60)
            # 2 Legs
            draw.line([(cpt[0] - cw, cpt[1]), (cpt[0] - cw, cpt[1] - ch // 2)], fill=col, width=leg_w)
            draw.line([(cpt[0] + cw, cpt[1]), (cpt[0] + cw, cpt[1] - ch // 2)], fill=col, width=leg_w)
            # Seat
            draw.line([(cpt[0] - cw - 4, cpt[1] - ch // 2), (cpt[0] + cw + 4, cpt[1] - ch // 2)], fill=col, width=leg_w + 1)
            # Backrest
            draw.line([(cpt[0] - cw, cpt[1] - ch // 2), (cpt[0] - cw, cpt[1] - ch)], fill=col, width=leg_w)

        elif kind == "ball":
            r = int(prop.get("radius", 0.08) * self.scale)
            draw.ellipse([cpt[0] - r, cpt[1] - r, cpt[0] + r, cpt[1] + r], fill=(220, 60, 60), outline=(160, 30, 30), width=max(1, int(2 * self.ss)))

        elif kind == "sword":
            length = prop.get("length", 0.35) * self.scale
            angle = prop.get("angle", 0.4)
            ex = cpt[0] + length * np.cos(angle)
            ey = cpt[1] - length * np.sin(angle)
            draw.line([(cpt[0], cpt[1]), (ex, ey)], fill=(70, 70, 80), width=max(1, int(3 * self.ss)))
            # Crossguard
            gx1 = cpt[0] + 0.15 * length * np.cos(angle) - 8 * np.sin(angle)
            gy1 = cpt[1] - 0.15 * length * np.sin(angle) - 8 * np.cos(angle)
            gx2 = cpt[0] + 0.15 * length * np.cos(angle) + 8 * np.sin(angle)
            gy2 = cpt[1] - 0.15 * length * np.sin(angle) + 8 * np.cos(angle)
            draw.line([(gx1, gy1), (gx2, gy2)], fill=(120, 120, 130), width=max(1, int(3 * self.ss)))

        elif kind == "crowd":
            # Silhouette spectators in background
            sil_col = (210, 210, 220)
            offsets = [-1.4, -1.0, -0.6, 0.6, 1.0, 1.4]
            for off in offsets:
                scpt = self.world_to_canvas(np.array([[px + off, py]]), camera_x=camera_x)[0]
                sh = int(70 * self.ss)
                draw.line([(scpt[0], scpt[1]), (scpt[0], scpt[1] - sh)], fill=sil_col, width=int(2 * self.ss))
                hr = int(10 * self.ss)
                draw.ellipse([scpt[0] - hr, scpt[1] - sh - 2 * hr, scpt[0] + hr, scpt[1] - sh], fill=sil_col)

    def draw_speed_lines(self, draw, cx, cy, direction=1.0, scale=1.0, progress=0.0):
        """Trailing motion lines behind a fast joint; fade out over progress 0->1."""
        fade = max(0.0, 1.0 - float(progress))
        if fade <= 0.0:
            return
        col = (120, 120, 130)
        line_len = 55.0 * self.ss * float(scale) * fade
        width = max(1, int(round(2 * self.ss * fade)))
        dir_s = 1.0 if float(direction) >= 0 else -1.0
        for dy in (-16.0, 0.0, 16.0):
            y_pos = cy + dy * self.ss
            x1 = cx - dir_s * (20.0 * self.ss)
            x2 = x1 - dir_s * line_len
            draw.line([(x1, y_pos), (x2, y_pos)], fill=col, width=width)

    def draw_dust_puff(self, draw, cx, scale=1.0, progress=0.0):
        """Ground-level dust ellipse pair; seated on the canvas ground line."""
        fade = max(0.0, 1.0 - float(progress))
        if fade <= 0.0:
            return
        gy = float(self.canvas_ground_y)
        col = (160, 160, 165)
        dr = 20.0 * self.ss * float(scale) * (0.5 + 0.5 * fade)
        w = max(1, int(2 * self.ss))
        draw.ellipse([cx - dr * 1.6, gy - dr * 0.9, cx + dr * 1.6, gy + dr * 0.3],
                     outline=col, width=w)
        draw.ellipse([cx - dr * 0.9, gy - dr * 1.3, cx + dr * 0.9, gy],
                     outline=col, width=max(1, w - 1))

    def draw_impact_burst(self, draw, cx, cy, scale=1.0, progress=0.0):
        """Radial impact flash; shrinks over progress 0->1."""
        fade = max(0.0, 1.0 - float(progress))
        if fade <= 0.0:
            return
        col = (220, 50, 20)
        r_outer = 32.0 * self.ss * float(scale) * (0.4 + 0.6 * fade)
        for k in range(8):
            ang = np.radians(k * 45.0 + 22.5)
            p1 = (cx + np.cos(ang) * r_outer * 0.25, cy + np.sin(ang) * r_outer * 0.25)
            p2 = (cx + np.cos(ang) * r_outer, cy + np.sin(ang) * r_outer)
            draw.line([p1, p2], fill=col, width=max(1, int(3 * self.ss)))
        flash_r = 6.0 * self.ss * float(scale) * fade
        if flash_r >= 1.0:
            draw.ellipse([cx - flash_r, cy - flash_r, cx + flash_r, cy + flash_r],
                         fill=(255, 255, 255))

    def resolve_vfx_anchor(self, v, joints_frame, camera_x=0.0):
        """Resolves a raw event dict to supersampled canvas coords (cx, cy) or None.

        Joint anchors and explicit x/y (world space) resolve through
        world_to_canvas.
        """
        if "anchor_puppet" in v and "anchor_joint" in v:
            try:
                pidx, jidx = int(v["anchor_puppet"]), int(v["anchor_joint"])
            except (TypeError, ValueError):
                return None
            if not (0 <= pidx < len(joints_frame)):
                return None
            pts = self.world_to_canvas(np.asarray(joints_frame[pidx][jidx]), camera_x=camera_x)
            return float(pts[0]), float(pts[1])
        if "x" in v and "y" in v:
            pts = self.world_to_canvas(np.array([float(v["x"]), float(v["y"])]),
                                        camera_x=camera_x)
            return float(pts[0]), float(pts[1])
        return None

    def _draw_joint_prop(self, draw, p, c_pts_all):
        """Draws a weapon rigidly anchored to a puppet joint (mirrors stage renderer).

        Supported kinds: sword, staff, shield. The prop aligns to the limb
        vector pts[joint] - pts[parent_joint] so it tracks the hand exactly.
        Unknown kinds and out-of-range puppets are ignored silently.
        """
        try:
            pidx = int(p.get("anchor_puppet", 0))
        except (TypeError, ValueError):
            return
        if not (0 <= pidx < len(c_pts_all)):
            return
        pts = np.asarray(c_pts_all[pidx], dtype=np.float32)
        try:
            joint = int(p.get("joint", 8))  # default right wrist/hand
        except (TypeError, ValueError):
            return
        if joint == 8:
            parent_joint = 7
        elif joint == 6:
            parent_joint = 5
        else:
            try:
                parent_joint = int(p.get("parent_joint", max(0, joint - 1)))
            except (TypeError, ValueError):
                return
        if not (0 <= joint < len(pts) and 0 <= parent_joint < len(pts)):
            return
        p_hand = pts[joint]
        p_elbow = pts[parent_joint]
        dx = float(p_hand[0] - p_elbow[0])
        dy = float(p_hand[1] - p_elbow[1])
        L = float(np.hypot(dx, dy)) + 1e-5
        u = np.array([dx / L, dy / L], dtype=np.float32)
        n = np.array([-dy / L, dx / L], dtype=np.float32)
        kind = p.get("kind")
        scale = float(p.get("scale", 1.0))

        if kind == "sword":
            col = p.get("color", (40, 40, 50))
            guard_col = (190, 160, 40)
            p_pommel = p_hand - u * (14.0 * self.ss * scale)
            draw.line([tuple(p_hand), tuple(p_pommel)], fill=col, width=int(3 * self.ss))
            g1 = p_hand - n * (12.0 * self.ss * scale)
            g2 = p_hand + n * (12.0 * self.ss * scale)
            draw.line([tuple(g1), tuple(g2)], fill=guard_col, width=int(3.5 * self.ss))
            p_tip = p_hand + u * (75.0 * self.ss * scale)
            draw.line([tuple(p_hand), tuple(p_tip)], fill=col, width=int(3.5 * self.ss))
        elif kind == "staff":
            col = p.get("color", (139, 69, 19))
            p_back = p_hand - u * (55.0 * self.ss * scale)
            p_front = p_hand + u * (95.0 * self.ss * scale)
            draw.line([tuple(p_back), tuple(p_front)], fill=col, width=int(4.5 * self.ss))
        elif kind == "shield":
            col = p.get("color", (100, 80, 180))
            mid = (p_elbow + p_hand) * 0.5
            sr = int(24 * self.ss * scale)
            draw.ellipse([mid[0] - sr, mid[1] - sr, mid[0] + sr, mid[1] + sr],
                         fill=(230, 230, 240), outline=col, width=int(3 * self.ss))

    def render_frame(self, joints_frame, camera_x=0.0, props=None, vfx=None):
        """Render a single frame with smooth camera offset, shadows, props, and VFX."""
        img = Image.new("RGB", (self.render_size, self.render_size), self.bg_color)
        draw = ImageDraw.Draw(img)

        # Draw ground horizon line
        draw.line([(0, self.canvas_ground_y), (self.render_size, self.canvas_ground_y)],
                  fill=GROUND_COLOR, width=max(1, int(2 * self.ss)))

        # Draw props (background; joint-anchored props wait for stickmen below)
        if props:
            for prop in props:
                if isinstance(prop, dict) and "anchor_puppet" in prop:
                    continue
                self.draw_prop(draw, prop, camera_x=camera_x)

        N = len(joints_frame)
        canvas_people = []

        # 1. Draw contact shadows first (beneath characters)
        for n in range(N):
            c_pts = self.world_to_canvas(joints_frame[n], camera_x=camera_x)
            canvas_people.append(c_pts)
            self.draw_drop_shadow(draw, c_pts, joints_frame[n])

        # 2. Draw stickmen
        for n in range(N):
            palette = DEFAULT_PALETTES[n % len(DEFAULT_PALETTES)]
            self.draw_stickman(draw, canvas_people[n], palette)

        # 2b. Draw joint-locked props (weapons track hands, above limbs)
        if props:
            for prop in props:
                if isinstance(prop, dict) and "anchor_puppet" in prop:
                    self._draw_joint_prop(draw, prop, canvas_people)

        # 3. Draw active VFX overlays (None by default -> byte-identical output)
        if vfx:
            for v in vfx:
                anchor = self.resolve_vfx_anchor(v, joints_frame, camera_x=camera_x)
                if anchor is None:
                    continue
                cx, cy = anchor
                progress = float(v.get("progress", 0.0))
                scale = float(v.get("scale", 1.0))
                if v.get("kind") == "speed_lines":
                    self.draw_speed_lines(draw, cx, cy,
                                          direction=float(v.get("direction", 1.0)),
                                          scale=scale, progress=progress)
                elif v.get("kind") == "impact_burst":
                    self.draw_impact_burst(draw, cx, cy, scale=scale, progress=progress)
                elif v.get("kind") == "dust_puff":
                    # Dust lives on the ground line; anchor y is ignored by design.
                    self.draw_dust_puff(draw, cx, scale=scale, progress=progress)

        # Downsample with Lanczos for smooth antialiased edges
        if self.ss > 1:
            img = img.resize((self.canvas_size, self.canvas_size), resample=Image.Resampling.LANCZOS)
        return img


def decode_motion_features(feat):
    """Accepts feat of shape (T, 30) or (T, 60), or dict with 'feat'.
    
    Returns joints of shape (T, N, 15, 2).
    """
    if isinstance(feat, dict):
        feat = feat["feat"]
    feat = np.asarray(feat, dtype=np.float32)
    T = feat.shape[0]
    total_dim = feat.shape[-1]
    
    if total_dim == 30:
        N = 1
        feats_split = [feat]
    elif total_dim == 60:
        N = 2
        feats_split = [feat[:, :30], feat[:, 30:]]
    elif total_dim % 30 == 0:
        N = total_dim // 30
        feats_split = [feat[:, i * 30:(i + 1) * 30] for i in range(N)]
    else:
        raise ValueError(f"Expected feature dimension to be multiple of 30, got {total_dim}")

    joints_list = []
    for f in feats_split:
        root, angles = decode(f)
        j = forward_kinematics(root, angles)  # (T, 15, 2)
        joints_list.append(j)
        
    return np.stack(joints_list, axis=1)


def compute_smooth_camera_track(joints, alpha=0.10):
    """Computes smooth damped horizontal camera tracking array (T,)."""
    T, N, _, _ = joints.shape
    if T == 0:
        return np.zeros(0, dtype=np.float32)
    
    # Target is center of the horizontal bounding box across all active actors and joints
    min_x = np.min(joints[:, :, :, 0], axis=(1, 2))
    max_x = np.max(joints[:, :, :, 0], axis=(1, 2))
    target_x = 0.5 * (min_x + max_x)
    cam_x = np.zeros(T, dtype=np.float32)
    curr = target_x[0]
    
    for t in range(T):
        curr = (1.0 - alpha) * curr + alpha * target_x[t]
        cam_x[t] = curr
        
    return cam_x


def apply_camera_impulses(cam_track, impulses=None, default_magnitude=0.02):
    """Adds 1-2 frame hit-shake kicks to a camera track (in place, also returned).

    Each impulse ``{"start_frame": int, "magnitude": float, "direction": +1|-1}``
    kicks the camera by magnitude at start_frame and settles with -0.5x on the
    next frame. Magnitudes are world units (~0.02 ~= a few px at 512).
    Single home for this helper (stage_renderer re-exports it).
    """
    if not impulses:
        return cam_track
    arr = np.asarray(cam_track, dtype=np.float32)
    T = len(arr)
    for imp in impulses:
        try:
            sf = int(imp.get("start_frame", 0))
            mag = float(imp.get("magnitude", default_magnitude))
            direction = 1.0 if int(imp.get("direction", 1)) >= 0 else -1.0
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= sf < T:
            arr[sf] += direction * mag
            if sf + 1 < T:
                arr[sf + 1] -= direction * mag * 0.5
    # Write back so callers holding the original reference observe the kicks.
    try:
        cam_track[:] = arr[:len(cam_track)]
    except (TypeError, ValueError):
        pass
    return cam_track


def impacts_to_vfx(impacts, default_duration=8):
    """Convert object-runtime impacts ``{frame,x,y,kind}`` to VFX event dicts.

    The object runtime already names its events ("impact_burst"/"dust_puff"),
    so this is a light normaliser into the renderer's start_frame contract.
    """
    out = []
    for imp in impacts or []:
        if not isinstance(imp, dict):
            continue
        try:
            frame = int(imp.get("frame", 0))
        except (TypeError, ValueError):
            continue
        out.append({
            "kind": imp.get("kind", "impact_burst"),
            "start_frame": frame,
            "duration": int(imp.get("duration", default_duration)),
            "x": float(imp.get("x", 0.0)),
            "y": float(imp.get("y", -0.42)),
            "scale": float(imp.get("scale", 1.0)),
        })
    return out


def impulses_from_impact_events(vfx_events, magnitude=0.02):
    """Derives camera impulses from impact_burst event dicts."""
    impulses = []
    for v in vfx_events or []:
        if not isinstance(v, dict) or v.get("kind") != "impact_burst":
            continue
        try:
            impulses.append({
                "start_frame": int(v.get("start_frame", 0)),
                "magnitude": float(v.get("scale", 1.0)) * magnitude,
                "direction": int(v.get("direction", 1)),
            })
        except (TypeError, ValueError):
            continue
    return impulses


def active_vfx_for_frame(vfx_events, frame_idx):
    """Filters raw event dicts to those active at frame_idx, stamped with progress.

    Event window: start_frame <= frame_idx < start_frame + duration.
    progress 0->1 across the window for fade-outs.
    """
    active = []
    for v in vfx_events or []:
        try:
            start = int(v.get("start_frame", 0))
            dur = max(1, int(v.get("duration", 8)))
        except (TypeError, ValueError):
            continue
        if start <= frame_idx < start + dur:
            active.append({**v, "progress": (frame_idx - start) / dur})
    return active


def render_to_video(feat_or_joints, output_path, fps=FPS, canvas_size=512,
                    fix_contact=True, auto_camera=True, props=None, vfx_events=None,
                    prop_tracks=None, camera_track=None, impacts=None,
                    progress_cb=None):
    """Render motion directly to an MP4 file with smooth camera tracking & shadows.

    vfx_events: optional raw event dicts (compile_events format). None (default)
    renders byte-identical output to the pre-VFX path.
    prop_tracks: optional per-frame prop lists (index t -> list of prop dicts),
    produced by objects.evaluate_objects. Takes precedence over ``props``.
    camera_track: optional dict {"camera_x": (T,), "zoom": float} from
    camera.compute_camera. Overrides auto_camera when given.
    impacts: optional impact event dicts {"frame","x","y","kind"} converted to
    VFX (and thus camera shake) automatically.
    progress_cb: optional ``(frames_done, total_frames)`` callback for UIs.
    """
    if isinstance(feat_or_joints, (dict, np.ndarray)) and (
        isinstance(feat_or_joints, dict) or feat_or_joints.shape[-1] in (30, 60)
    ):
        joints = decode_motion_features(feat_or_joints)
    else:
        joints = np.asarray(feat_or_joints, dtype=np.float32)
        if joints.ndim == 3:
            joints = joints[:, np.newaxis, :, :]

    if fix_contact:
        joints = apply_contact_correction(joints)

    T, N, _, _ = joints.shape
    renderer = StickmanRenderer(canvas_size=canvas_size)

    # Impacts are VFX too (impact bursts + dust puffs).
    if impacts:
        vfx_events = list(vfx_events or []) + impacts_to_vfx(impacts)

    # Compute camera track, then layer hit-shake impulses from impact events.
    if camera_track and "camera_x" in camera_track:
        cam_track = np.asarray(camera_track["camera_x"], dtype=np.float32)[:T]
        if len(cam_track) < T:
            cam_track = np.pad(cam_track, (0, T - len(cam_track)), mode="edge")
    elif auto_camera:
        cam_track = compute_smooth_camera_track(joints, alpha=0.10)
    else:
        cam_track = np.zeros(T, dtype=np.float32)
    if vfx_events:
        hits = impulses_from_impact_events(vfx_events)
        if hits:
            cam_track = np.asarray(apply_camera_impulses(cam_track, hits),
                                   dtype=np.float32)

    from .video_encode import open_ffmpeg_writer, close_ffmpeg_writer

    proc = open_ffmpeg_writer(output_path, width=canvas_size, height=canvas_size, fps=fps, crf=22, preset="fast")

    try:
        for t in range(T):
            frame_vfx = active_vfx_for_frame(vfx_events, t) if vfx_events else None
            frame_props = prop_tracks[t] if prop_tracks is not None else props
            img = renderer.render_frame(joints[t], camera_x=cam_track[t], props=frame_props,
                                        vfx=frame_vfx)
            proc.stdin.write(img.tobytes())
            if progress_cb is not None and (t % 4 == 0 or t == T - 1):
                progress_cb(t + 1, T)
        close_ffmpeg_writer(proc)
    except Exception:
        proc.kill()
        raise

    return output_path
