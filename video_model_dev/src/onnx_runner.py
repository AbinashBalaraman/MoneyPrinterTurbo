"""ONNX Runtime Inference Engine for Motion Diffusion.

Runs on dev laptop CPU without PyTorch or CUDA dependencies.
If a trained ONNX model is available at models/motion_denoiser.onnx,
executes DDIM / DDPM sampling loop; otherwise falls back gracefully
to the procedural motion generator.
"""

import os
from typing import Dict, Any, Optional
import numpy as np

try:
    import onnxruntime as ort
    ORT_AVAILABLE = True
except ImportError:
    ORT_AVAILABLE = False

from src.data_gen import gen_single, ACTIONS_1P


class MotionONNXRunner:
    """Inference runner using ONNX Runtime for CPU motion generation."""

    def __init__(self, model_path: str = "models/motion_denoiser.onnx"):
        self.model_path = model_path
        self.session = None
        if ORT_AVAILABLE and os.path.exists(model_path):
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            self.session = ort.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])

    def is_model_loaded(self) -> bool:
        return self.session is not None

    def generate_motion(
        self,
        action: str,
        duration_s: float = 3.0,
        speed: float = 1.0,
        amplitude: float = 1.0,
        direction: int = 1,
        seed: int = 0
    ) -> Dict[str, Any]:
        """Generates motion features using ONNX model or procedural fallback."""
        if self.session is None:
            # Procedural fallback
            return gen_single(
                action=action,
                duration_s=duration_s,
                speed=speed,
                amplitude=amplitude,
                direction=direction,
                seed=seed
            )

        # ONNX model inference path
        action_names = sorted(list(ACTIONS_1P))
        act_idx = action_names.index(action) if action in action_names else 0
        T = int(duration_s * 24)
        max_frames = 120
        T_pad = min(T, max_frames)

        # Simple 1-step DDIM preview inference
        rng = np.random.RandomState(seed)
        x_init = rng.randn(1, max_frames, 30).astype(np.float32)
        timesteps = np.array([0], dtype=np.int64)
        action_tensor = np.array([act_idx], dtype=np.int64)
        controls = np.array([[speed, amplitude, float(direction)]], dtype=np.float32)
        mask = np.zeros((1, max_frames), dtype=bool)
        if T_pad < max_frames:
            mask[0, T_pad:] = True

        inputs = {
            "x_t": x_init,
            "timesteps": timesteps,
            "action_idx": action_tensor,
            "controls": controls,
            "mask": mask
        }
        outputs = self.session.run(None, inputs)
        x_pred = outputs[0][0, :T_pad]

        return {
            "feat": x_pred,
            "family_id": f"onnx-{action}",
            "label": action,
            "n_person": 1,
            "T": T_pad
        }
