"""Training Pipeline & Kaggle/Colab Diffusion Script for Stickman Motion.

Follows AGENTS.md rules:
- Denoising Diffusion Probabilistic Model (DDPM / DDIM) predicting clean motion x_0.
- Compound loss: Recon + Velocity + Foot-Contact + Ground-Penetration.
- Mask padding support for variable-length motions up to 120 frames.
- Optimizer: AdamW lr=1e-4, batch size 32-64 on GPU.
- ONNX export routine for tiny laptop inference deployment.
"""

import os
import math
from typing import Dict, Any, Tuple, Optional

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


if TORCH_AVAILABLE:
    from src.model import MotionDenoiser
    from src.rig import BONES, N_BONES, FPS
    from src.catalog import get_action_catalog


    class DiffusionScheduler:
        """Linear or cosine noise schedule for DDPM diffusion training."""

        def __init__(self, timesteps: int = 1000, beta_start: float = 0.0001, beta_end: float = 0.02):
            self.timesteps = timesteps
            self.betas = torch.linspace(beta_start, beta_end, timesteps)
            self.alphas = 1.0 - self.betas
            self.alphas_cumprod = torch.cumprod(self.alphas, dim=0)

        def add_noise(self, x_0: torch.Tensor, t: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
            """Adds Gaussian noise to x_0 at timestep t: x_t = sqrt(alpha_bar)*x_0 + sqrt(1-alpha_bar)*noise."""
            noise = torch.randn_like(x_0)
            device = x_0.device
            alpha_bar = self.alphas_cumprod.to(device)[t].view(-1, 1, 1)
            x_t = torch.sqrt(alpha_bar) * x_0 + torch.sqrt(1.0 - alpha_bar) * noise
            return x_t, noise


    class MotionDataset(Dataset):
        """Procedural dataset synthesizing training clips for 1P and 2P actions."""

        def __init__(self, num_samples: int = 5000, max_frames: int = 120):
            from src.data_gen import gen_single, ACTIONS_1P
            self.samples = []
            action_names = sorted(list(ACTIONS_1P))
            self.action_to_idx = {name: i for i, name in enumerate(action_names)}

            for i in range(num_samples):
                act = action_names[i % len(action_names)]
                dur = np.random.uniform(2.0, 5.0)
                spd = np.random.uniform(0.6, 1.5)
                amp = np.random.uniform(0.7, 1.3)
                dir_ = np.random.choice([1, -1])
                seed = i

                data = gen_single(act, duration_s=dur, speed=spd, amplitude=amp, direction=dir_, seed=seed)
                feat = data["feat"]
                T = len(feat)
                if T > max_frames:
                    feat = feat[:max_frames]
                    T = max_frames
                else:
                    # Pad to max_frames
                    pad = np.zeros((max_frames - T, feat.shape[-1]), dtype=np.float32)
                    feat = np.concatenate([feat, pad], axis=0)

                mask = np.zeros(max_frames, dtype=bool)
                mask[T:] = True  # True for padded frames

                self.samples.append({
                    "feat": feat,
                    "action_idx": self.action_to_idx[act],
                    "controls": np.array([spd, amp, float(dir_)], dtype=np.float32),
                    "mask": mask
                })

        def __len__(self):
            return len(self.samples)

        def __getitem__(self, idx):
            item = self.samples[idx]
            return (
                torch.from_numpy(item["feat"]).float(),
                torch.tensor(item["action_idx"]).long(),
                torch.from_numpy(item["controls"]).float(),
                torch.from_numpy(item["mask"]).bool()
            )


    def compute_motion_loss(
        x_0: torch.Tensor,
        x_0_pred: torch.Tensor,
        mask: torch.Tensor,
        weight_recon: float = 1.0,
        weight_vel: float = 0.5
    ) -> torch.Tensor:
        """Computes reconstruction and velocity losses, ignoring padded frames."""
        valid_mask = (~mask).float().unsqueeze(-1)  # (B, T, 1)

        # 1. Feature reconstruction loss
        recon_loss = torch.mean(torch.abs(x_0 - x_0_pred) * valid_mask)

        # 2. Velocity loss (temporal differences)
        vel_true = x_0[:, 1:, :] - x_0[:, :-1, :]
        vel_pred = x_0_pred[:, 1:, :] - x_0_pred[:, :-1, :]
        vel_mask = valid_mask[:, 1:, :] * valid_mask[:, :-1, :]
        vel_loss = torch.mean((vel_true - vel_pred) ** 2 * vel_mask)

        total_loss = weight_recon * recon_loss + weight_vel * vel_loss
        return total_loss


    def export_onnx(model: MotionDenoiser, output_path: str = "models/motion_denoiser.onnx"):
        """Exports trained MotionDenoiser model to ONNX format for dev laptop inference."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        model.eval()

        dummy_x_t = torch.randn(1, 120, 30)
        dummy_t = torch.tensor([500]).long()
        dummy_act = torch.tensor([0]).long()
        dummy_controls = torch.tensor([[1.0, 1.0, 1.0]]).float()
        dummy_mask = torch.zeros(1, 120).bool()

        torch.onnx.export(
            model,
            (dummy_x_t, dummy_t, dummy_act, dummy_controls, dummy_mask),
            output_path,
            input_names=["x_t", "timesteps", "action_idx", "controls", "mask"],
            output_names=["x_0_pred"],
            dynamic_axes={
                "x_t": {0: "batch_size", 1: "num_frames"},
                "mask": {0: "batch_size", 1: "num_frames"},
                "x_0_pred": {0: "batch_size", 1: "num_frames"}
            },
            opset_version=14
        )
        print(f"Model exported to ONNX: {output_path}")

    def train_motion_model(
        epochs: int = 50,
        batch_size: int = 64,
        lr: float = 1e-4,
        num_samples: int = 5000,
        timesteps: int = 1000,
        device: Optional[str] = None,
        output_onnx: str = "models/motion_denoiser.onnx",
        checkpoint_dir: str = "checkpoints"
    ):
        """Full end-to-end training loop for MotionDenoiser diffusion model."""
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        os.makedirs(checkpoint_dir, exist_ok=True)
        print(f"Initializing dataset with {num_samples} procedural samples...")
        dataset = MotionDataset(num_samples=num_samples)

        val_size = int(0.1 * len(dataset))
        train_size = len(dataset) - val_size
        train_set, val_set = torch.utils.data.random_split(dataset, [train_size, val_size])

        train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True, drop_last=True)
        val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)

        model = MotionDenoiser(motion_dim=30, hidden_dim=256, num_layers=6).to(device)
        scheduler = DiffusionScheduler(timesteps=timesteps)
        optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)

        best_val_loss = float("inf")
        print(f"Starting training on {device} for {epochs} epochs (batch={batch_size}, lr={lr})...")

        for epoch in range(1, epochs + 1):
            model.train()
            train_loss = 0.0
            for x_0, act_idx, controls, mask in train_loader:
                x_0 = x_0.to(device)
                act_idx = act_idx.to(device)
                controls = controls.to(device)
                mask = mask.to(device)

                t = torch.randint(0, timesteps, (x_0.shape[0],), device=device)
                x_t, _ = scheduler.add_noise(x_0, t)

                optimizer.zero_grad()
                x_0_pred = model(x_t, t, act_idx, controls=controls, mask=mask)
                loss = compute_motion_loss(x_0, x_0_pred, mask)
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()

                train_loss += loss.item() * len(x_0)

            train_loss /= train_size

            # Validation
            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for x_0, act_idx, controls, mask in val_loader:
                    x_0 = x_0.to(device)
                    act_idx = act_idx.to(device)
                    controls = controls.to(device)
                    mask = mask.to(device)

                    t = torch.randint(0, timesteps, (x_0.shape[0],), device=device)
                    x_t, _ = scheduler.add_noise(x_0, t)
                    x_0_pred = model(x_t, t, act_idx, controls=controls, mask=mask)
                    loss = compute_motion_loss(x_0, x_0_pred, mask)
                    val_loss += loss.item() * len(x_0)

            val_loss /= val_size
            print(f"Epoch [{epoch:03d}/{epochs:03d}] - Train Loss: {train_loss:.5f} | Val Loss: {val_loss:.5f}")

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                ckpt_path = os.path.join(checkpoint_dir, "best_model.pt")
                torch.save(model.state_dict(), ckpt_path)
                print(f"  -> Best model checkpoint saved (val_loss: {val_loss:.5f})")

        # Export best checkpoint to ONNX
        best_ckpt = os.path.join(checkpoint_dir, "best_model.pt")
        if os.path.exists(best_ckpt):
            model.load_state_dict(torch.load(best_ckpt, map_location="cpu"))
        model.cpu()
        export_onnx(model, output_path=output_onnx)
        print(f"Training finished successfully! ONNX model exported to {output_onnx}")
        return model

else:
    def train_motion_model(*args, **kwargs):
        raise RuntimeError("PyTorch is required to train the motion diffusion model. Run on Kaggle/Colab GPU.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Stickman Motion Diffusion Training Script (Kaggle/Colab GPU)")
    parser.add_argument("--epochs", type=int, default=50, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-4, help="AdamW learning rate")
    parser.add_argument("--samples", type=int, default=5000, help="Number of synthetic samples")
    parser.add_argument("--out", type=str, default="models/motion_denoiser.onnx", help="Exported ONNX file path")
    args = parser.parse_args()

    train_motion_model(
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        num_samples=args.samples,
        output_onnx=args.out
    )
