import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.puppet.choreography import PuppetChoreographer
from src.stage_renderer import render_stage_video

def main():
    print('[*] Choreographing: running forward and jumping around...')
    ch = PuppetChoreographer(start_x=-0.8, fps=24, init_pose='stand_relaxed')

    # 1. Fast Sprint forward (+X)
    ch.run(steps=5, step_duration=0.26, stride_length=0.34, direction=1)

    # 2. Big leap forward (+X) with landing dust puff
    ch.jump(distance_x=0.45, height=0.42)

    # 3. Quick rebound jump back (-X) with landing dust
    ch.jump(distance_x=-0.30, height=0.35)

    # 4. Acrobatic vertical bounce (+X)
    ch.jump(distance_x=0.20, height=0.38)

    # 5. Triumphant celebration
    ch.celebrate()

    feat = ch.compile()
    events = ch.compile_events(puppet_index=0)
    print(f'[+] Compiled {len(feat)} frames ({len(feat)/24.0:.2f}s) with {len(events)} VFX events.')

    out_file = 'out/stickman_run_and_jump.mp4'
    render_stage_video(
        feat,
        out_file,
        theme_name='dark',
        vfx=events,
        fix_contact=False,
        scenery={'auto_camera': True}
    )
    print(f'[SUCCESS] Rendered to: {out_file}')

if __name__ == '__main__':
    main()
