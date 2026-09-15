import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.puppet.choreography import PuppetChoreographer
from src.renderer import render_to_video

def main():
    print("[*] Generating jump_run_v5 with corrected knee flexion...")
    ch = PuppetChoreographer(start_x=-0.8, fps=24, init_pose="stand_relaxed")
    
    # 1. Forward run strides (flight=0.06, arm_scale=1.4)
    ch.walk(
        steps=6,
        step_duration=0.30,
        stride_length=0.34,
        direction=1,
        flight=0.06,
        arm_scale=1.4,
        end_hold=0.75
    )
    
    # 2. Acrobatic leap & staggered absorb landing
    ch.jump(distance_x=0.45, height=0.40)

    feat = ch.compile()
    print(f"[+] Compiled {len(feat)} frames ({len(feat)/24.0:.2f}s)")

    out_file = "out/jump_run_v5.mp4"
    render_to_video(feat, out_file, fps=24, canvas_size=512, fix_contact=False, auto_camera=True)
    print(f"[SUCCESS] Rendered to {out_file}")

if __name__ == "__main__":
    main()
