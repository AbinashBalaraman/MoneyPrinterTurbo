"""Temporal Transformer Denoiser for Stickman Motion Diffusion.

Follows AGENTS.md specifications:
- 1 token per frame, up to 120 frames (5s @ 24fps).
- Hidden dimension 256, 6-8 transformer blocks, ~5-15M parameters.
- Predicts clean motion x_0 from noisy motion x_t and timestep t.
- Conditioned on action class embedding and continuous controls (speed, amplitude, direction).
- Designed for Kaggle/Colab GPU training (T4/P100) and exportable to ONNX for dev laptop inference.
"""

import math
from typing import Optional

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    nn = object


if TORCH_AVAILABLE:

    class SinusoidalPositionalEmbedding(nn.Module):
        """Sinusoidal positional encoding for frame timestamps and diffusion timesteps."""

        def __init__(self, dim: int, max_len: int = 5000):
            super().__init__()
            self.dim = dim
            inv_freq = 1.0 / (10000 ** (torch.arange(0, dim, 2).float() / dim))
            self.register_buffer("inv_freq", inv_freq)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # x: (B,) or (T,)
            sinusoid_in = torch.einsum("i,j->ij", x.float(), self.inv_freq)
            emb = torch.cat([torch.sin(sinusoid_in), torch.cos(sinusoid_in)], dim=-1)
            return emb


    class TransformerBlock(nn.Module):
        """Standard pre-LN Transformer encoder block with Multihead Attention and MLP."""

        def __init__(self, hidden_dim: int = 256, num_heads: int = 8, mlp_ratio: float = 4.0, dropout: float = 0.1):
            super().__init__()
            self.ln1 = nn.LayerNorm(hidden_dim)
            self.attn = nn.MultiheadAttention(
                embed_dim=hidden_dim,
                num_heads=num_heads,
                dropout=dropout,
                batch_first=True
            )
            self.ln2 = nn.LayerNorm(hidden_dim)
            mlp_hidden = int(hidden_dim * mlp_ratio)
            self.mlp = nn.Sequential(
                nn.Linear(hidden_dim, mlp_hidden),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(mlp_hidden, hidden_dim),
                nn.Dropout(dropout)
            )

        def forward(self, x: torch.Tensor, key_padding_mask: Optional[torch.Tensor] = None) -> torch.Tensor:
            # Pre-LN Self-Attention
            norm_x = self.ln1(x)
            attn_out, _ = self.attn(norm_x, norm_x, norm_x, key_padding_mask=key_padding_mask)
            x = x + attn_out
            # Pre-LN MLP
            x = x + self.mlp(self.ln2(x))
            return x


    class MotionDenoiser(nn.Module):
        """Temporal Transformer Denoiser predicting clean motion x_0.
        
        Args:
            motion_dim: Feature dimension per frame (30 for 1P, 60 for 2P).
            hidden_dim: Transformer embedding dimension (default 256).
            num_layers: Number of transformer blocks (default 6).
            num_heads: Number of attention heads (default 8).
            num_actions: Number of discrete action classes (17).
            max_frames: Maximum sequence length (120 frames).
        """

        def __init__(
            self,
            motion_dim: int = 30,
            hidden_dim: int = 256,
            num_layers: int = 6,
            num_heads: int = 8,
            num_actions: int = 17,
            max_frames: int = 120,
            dropout: float = 0.1
        ):
            super().__init__()
            self.motion_dim = motion_dim
            self.hidden_dim = hidden_dim
            self.max_frames = max_frames

            # Input motion projection
            self.input_proj = nn.Linear(motion_dim, hidden_dim)

            # Timestep embedding (diffusion noise level)
            self.time_emb = nn.Sequential(
                SinusoidalPositionalEmbedding(hidden_dim),
                nn.Linear(hidden_dim, hidden_dim),
                nn.SiLU(),
                nn.Linear(hidden_dim, hidden_dim)
            )

            # Action class conditioning embedding
            self.action_emb = nn.Embedding(num_actions, hidden_dim)

            # Continuous control conditioning: [speed, amplitude, direction] -> hidden_dim
            self.control_proj = nn.Sequential(
                nn.Linear(3, hidden_dim),
                nn.SiLU(),
                nn.Linear(hidden_dim, hidden_dim)
            )

            # Frame position embedding (temporal ordering)
            self.frame_pos_emb = nn.Parameter(torch.randn(1, max_frames, hidden_dim) * 0.02)

            # Transformer encoder backbone
            self.blocks = nn.ModuleList([
                TransformerBlock(hidden_dim=hidden_dim, num_heads=num_heads, dropout=dropout)
                for _ in range(num_layers)
            ])

            # Output head predicting clean motion x_0
            self.final_ln = nn.LayerNorm(hidden_dim)
            self.output_proj = nn.Linear(hidden_dim, motion_dim)

        def forward(
            self,
            x_t: torch.Tensor,
            timesteps: torch.Tensor,
            action_idx: torch.Tensor,
            controls: Optional[torch.Tensor] = None,
            mask: Optional[torch.Tensor] = None
        ) -> torch.Tensor:
            """Forward pass predicting clean motion x_0.
            
            Args:
                x_t: Noisy motion tensor of shape (B, T, motion_dim).
                timesteps: Diffusion timesteps of shape (B,).
                action_idx: Action class indices of shape (B,).
                controls: Continuous controls [speed, amplitude, direction] of shape (B, 3).
                mask: Boolean padding mask of shape (B, T) where True indicates padded frames.
                
            Returns:
                x_0_pred: Predicted clean motion tensor of shape (B, T, motion_dim).
            """
            B, T, D = x_t.shape

            # 1. Project input motion features to tokens
            h = self.input_proj(x_t)  # (B, T, hidden_dim)

            # 2. Add temporal position embedding
            h = h + self.frame_pos_emb[:, :T, :]

            # 3. Compute conditioning token (timestep + action + controls)
            t_emb = self.time_emb(timesteps)  # (B, hidden_dim)
            a_emb = self.action_emb(action_idx)  # (B, hidden_dim)
            cond = t_emb + a_emb

            if controls is not None:
                c_emb = self.control_proj(controls)  # (B, hidden_dim)
                cond = cond + c_emb

            # Inject conditioning into every frame token
            h = h + cond.unsqueeze(1)

            # 4. Pass through Transformer encoder blocks
            for block in self.blocks:
                h = block(h, key_padding_mask=mask)

            # 5. Output projection back to motion feature space
            h = self.final_ln(h)
            x_0_pred = self.output_proj(h)

            return x_0_pred

else:
    class MotionDenoiser:
        """Stub when PyTorch is not installed in the environment."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "PyTorch is not installed in this environment. "
                "Per AGENTS.md, model training runs on Kaggle/Colab GPU. "
                "For laptop inference, use procedural generation or exported ONNX runtime."
            )
