"""Masked losses on z = log(travel_time / free-flow travel time). Horizons are weighted equally."""
from __future__ import annotations

import torch
import torch.nn.functional as F


def masked_huber(pred: torch.Tensor, target: torch.Tensor, mask: torch.Tensor, delta: float = 1.0) -> torch.Tensor:
    """pred/target/mask [B, H, N]. Mean over valid roads per horizon, then mean over horizons that have labels.
    Invalid targets (NaN) never reach the loss."""
    pred = pred.float()
    tgt = torch.where(mask, target, torch.zeros_like(target)).float()
    l = F.huber_loss(pred, tgt, reduction="none", delta=delta) * mask
    n = mask.sum(dim=(0, 2)).float()
    per_h = l.sum(dim=(0, 2)) / n.clamp(min=1)
    has = n > 0
    return per_h[has].mean() if has.any() else pred.sum() * 0.0


def masked_congestion_l1(pred_z, target_z, mask) -> torch.Tensor:
    """Optional auxiliary loss on the derived congestion ratio clip(1 - exp(-z), 0, 1)."""
    c = lambda z: (1 - torch.exp(-z.float())).clamp(0, 1)
    tgt = torch.where(mask, target_z, torch.zeros_like(target_z))
    l = (c(pred_z) - c(tgt)).abs() * mask
    return l.sum() / mask.sum().clamp(min=1)


def paired_delta_huber(pred_e, pred_c, target_e, target_c, common, delta: float = 1.0) -> torch.Tensor:
    """Huber on the predicted vs observed (event - control) difference of z over their common valid roads
    [B, H, N]. A log travel-time-ratio difference, not seconds; effects may be negative (diversion)."""
    te = torch.where(common, target_e, torch.zeros_like(target_e))
    tc = torch.where(common, target_c, torch.zeros_like(target_c))
    return masked_huber(pred_e - pred_c, te - tc, common, delta)
