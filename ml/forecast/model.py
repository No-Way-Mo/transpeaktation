"""Event-conditioned spatial-patch forecaster.

    history [B, 6, N, F] + static road attributes + calendar time
      -> embed -> 3 x PatchBlock( temporal attention per road
                                  -> local attention inside each 128-road patch
                                  -> global attention between pooled patch summaries, broadcast back
                                  -> sparse exchange over legal road connections (in/out neighbours)
                                  -> feed-forward )
      -> horizon decoder (per road, per future bucket, sees that bucket's scheduled context)
      -> z = log(travel_time / free_flow_travel_time)   [B, 6, N]

Adapted from PatchSTG (local/global spatial patching) and ConFormer-style conditioning; NOT a reproduction:
the global stage attends over mean-pooled patch summaries (a deliberate simplification of PatchSTG's patch-level
interaction), patches come from a balanced coordinate bisection of road midpoints, and a sparse legal-connection
exchange is added because road traffic propagates along turns, not along straight-line proximity.

Event branch (use_events=True): sparse (case, road) pair features -> MLP -> permutation-invariant mean/max per road
-> propagation over up/downstream connections -> per-block FiLM scale/shift + residual gate, and per-horizon context
into the decoder. All conditioning heads are zero-initialised, so the untrained branch is an exact no-op; with
use_events=False the branch does not exist and the backbone is otherwise identical.

Padding masks are respected in local attention and patch pooling; nothing allocates an N x N tensor.
"""
from __future__ import annotations

import warnings

import torch
import torch.nn as nn
import torch.nn.functional as F

warnings.filterwarnings("ignore", message="index_reduce\(\) is in beta")


class Attn(nn.Module):
    def __init__(self, d: int, heads: int, dropout: float):
        super().__init__()
        assert d % heads == 0
        self.h, self.p = heads, dropout
        self.qkv = nn.Linear(d, 3 * d)
        self.out = nn.Linear(d, d)

    def forward(self, x: torch.Tensor, key_valid: torch.Tensor | None = None) -> torch.Tensor:
        M, L, d = x.shape
        q, k, v = self.qkv(x).view(M, L, 3, self.h, d // self.h).permute(2, 0, 3, 1, 4)
        mask = None if key_valid is None else key_valid[:, None, None, :]
        y = F.scaled_dot_product_attention(q, k, v, attn_mask=mask, dropout_p=self.p if self.training else 0.0)
        return self.out(y.transpose(1, 2).reshape(M, L, d))


def scatter_mean(x: torch.Tensor, index: torch.Tensor, size: int, count: torch.Tensor) -> torch.Tensor:
    """x [M, E, d] summed into [M, size, d] at index [E], divided by count [size]."""
    out = x.new_zeros(x.shape[0], size, x.shape[2]).index_add_(1, index, x)
    return out / count.clamp(min=1).to(out.dtype)[None, :, None]


class GraphBuffers(nn.Module):
    """Road/patch/connection mappings persisted inside the checkpoint."""

    def __init__(self, patch_idx, road_patch, src, dst, static):
        super().__init__()
        P, S = patch_idx.shape
        N = len(road_patch)
        slot = torch.full((N,), -1, dtype=torch.long)
        valid = patch_idx >= 0
        flat = torch.arange(P * S).view(P, S)
        slot[patch_idx[valid]] = flat[valid]
        assert (slot >= 0).all(), "every road must sit in exactly one patch"
        self.register_buffer("patch_idx", torch.where(valid, patch_idx, torch.full_like(patch_idx, N)))
        self.register_buffer("patch_valid", valid)
        self.register_buffer("road_slot", slot)
        self.register_buffer("road_patch", road_patch.long())
        self.register_buffer("patch_count", valid.sum(1))
        self.register_buffer("src", src.long())
        self.register_buffer("dst", dst.long())
        self.register_buffer("indeg", torch.bincount(dst.long(), minlength=N))
        self.register_buffer("outdeg", torch.bincount(src.long(), minlength=N))
        self.register_buffer("static", static.float())
        self.N, self.P, self.S = N, P, S


class PatchBlock(nn.Module):
    def __init__(self, d: int, heads: int, dropout: float):
        super().__init__()
        self.ln = nn.ModuleList([nn.LayerNorm(d) for _ in range(5)])
        self.temporal = Attn(d, heads, dropout)
        self.local = Attn(d, heads, dropout)
        self.glob = Attn(d, heads, dropout)
        self.glob_back = nn.Linear(d, d)
        self.sparse = nn.Sequential(nn.Linear(2 * d, d), nn.GELU(), nn.Linear(d, d))
        self.ffn = nn.Sequential(nn.Linear(d, 2 * d), nn.GELU(), nn.Linear(2 * d, d))
        self.drop = nn.Dropout(dropout)

    def _temporal(self, u, g):
        B, T, N, d = u.shape
        y = self.temporal(u.permute(0, 2, 1, 3).reshape(B * N, T, d))
        return y.view(B, N, T, d).permute(0, 2, 1, 3)

    def _local(self, u, g: GraphBuffers):
        B, T, N, d = u.shape
        flat = torch.cat([u.reshape(B * T, N, d), u.new_zeros(B * T, 1, d)], 1)   # row N = padding
        x = flat[:, g.patch_idx.reshape(-1)].view(B * T * g.P, g.S, d)
        valid = g.patch_valid[None].expand(B * T, -1, -1).reshape(B * T * g.P, g.S)
        y = self.local(x, valid).view(B * T, g.P * g.S, d)
        return y[:, g.road_slot].view(B, T, N, d)

    def _global(self, u, g: GraphBuffers):
        B, T, N, d = u.shape
        flat = u.reshape(B * T, N, d)
        pooled = scatter_mean(flat, g.road_patch, g.P, g.patch_count)
        y = self.glob(pooled)
        return self.glob_back(y[:, g.road_patch]).view(B, T, N, d)

    def _sparse(self, u, g: GraphBuffers):
        B, T, N, d = u.shape
        flat = u.reshape(B * T, N, d)
        from_up = scatter_mean(flat[:, g.src], g.dst, N, g.indeg)      # messages from predecessors
        from_down = scatter_mean(flat[:, g.dst], g.src, N, g.outdeg)   # messages from successors
        return self.sparse(torch.cat([from_up, from_down], -1)).view(B, T, N, d)

    def forward(self, h, g: GraphBuffers, film=None):
        for ln, f in zip(self.ln, (self._temporal, self._local, self._global, self._sparse, None)):
            u = ln(h)
            if film is not None:
                gamma, beta, _ = film
                u = u * (1 + gamma) + beta
            y = self.ffn(u) if f is None else f(u, g)
            if film is not None:
                y = y * (1 + film[2])
            h = h + self.drop(y)
        return h


class EventBranch(nn.Module):
    def __init__(self, n_feat: int, d: int, hops: int, blocks: int):
        super().__init__()
        self.pair = nn.Sequential(nn.Linear(n_feat, d), nn.GELU(), nn.Linear(d, d))
        self.agg = nn.Sequential(nn.Linear(2 * d + 1, d), nn.GELU(), nn.Linear(d, d))
        self.prop = nn.ModuleList([nn.ModuleDict({"ln": nn.LayerNorm(d), "down": nn.Linear(d, d),
                                                  "up": nn.Linear(d, d)}) for _ in range(hops)])
        self.film = nn.ModuleList([nn.Linear(d, 3 * d) for _ in range(blocks)])
        self.dec_ctx = nn.Linear(d, d)
        self.dec_film = nn.Linear(d, 2 * d)
        for m in [*self.film, self.dec_ctx, self.dec_film]:   # identity / no-op at initialisation
            nn.init.zeros_(m.weight)
            nn.init.zeros_(m.bias)

    def forward(self, feats: torch.Tensor, pair_road: torch.Tensor, g: GraphBuffers) -> torch.Tensor:
        """feats [K, P, F] (K = context times) -> road context [K, N, d]."""
        K, P, _ = feats.shape
        N = g.N
        e = self.pair(feats)
        d = e.shape[-1]
        cnt = torch.bincount(pair_road, minlength=N)
        mean = scatter_mean(e, pair_road, N, cnt)
        mx = e.new_zeros(K, N, d).index_reduce_(1, pair_road, e, "amax", include_self=False)
        has = (cnt > 0).to(e.dtype)[None, :, None]
        c = self.agg(torch.cat([mean, mx, torch.log1p(cnt.to(e.dtype))[None, :, None].expand(K, N, 1)], -1)) * has
        for layer in self.prop:
            u = layer["ln"](c)
            c = c + F.gelu(layer["down"](scatter_mean(u[:, g.src], g.dst, N, g.indeg))
                           + layer["up"](scatter_mean(u[:, g.dst], g.src, N, g.outdeg)))
        return c


class EventPatchForecaster(nn.Module):
    def __init__(self, gb: GraphBuffers, n_hist: int, n_time: int, n_fut_base: int, n_event: int, history: int,
                 horizon: int, hidden=64, heads=4, blocks=3, dropout=0.1, use_events=True, event_hops=2,
                 z_bias: float = 0.0):
        super().__init__()
        d = hidden
        self.g, self.T, self.H, self.use_events = gb, history, horizon, use_events
        self.hist_in = nn.Linear(n_hist, d)
        self.static_in = nn.Sequential(nn.Linear(gb.static.shape[1], d), nn.GELU(), nn.Linear(d, d))
        self.time_in = nn.Linear(n_time, d)
        self.blocks = nn.ModuleList([PatchBlock(d, heads, dropout) for _ in range(blocks)])
        self.summary = nn.Linear(history * d, d)
        self.hor = nn.Embedding(horizon, d)
        self.time_fut = nn.Linear(n_time, d)
        self.fut_base = nn.Linear(n_fut_base, d)
        self.dec_ln = nn.LayerNorm(d)
        self.head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))
        nn.init.constant_(self.head[-1].bias, z_bias)
        self.events = EventBranch(n_event, d, event_hops, blocks) if use_events else None

    def forward(self, hist, time_hist, time_fut, fut_base, event_feats=None, pair_road=None):
        """hist [B,T,N,F]; time_hist [B,T,4]; time_fut [B,H,4]; fut_base [B,H,N,Fb];
        event_feats [B, 1+H, P, Fe] (context at the last history bucket, then each future bucket); B must be 1 when
        events are used (pair lists differ per window). Returns z [B, H, N]."""
        g = self.g
        B, T, N, _ = hist.shape
        h = self.hist_in(hist) + self.static_in(g.static)[None, None] + self.time_in(time_hist)[:, :, None]
        ctx = None
        if self.use_events:
            assert B == 1 and event_feats is not None
            ctx = self.events(event_feats[0], pair_road, g)[None]         # [1, 1+H, N, d]
        for i, blk in enumerate(self.blocks):
            film = None
            if ctx is not None:
                film = self.events.film[i](ctx[:, :1]).chunk(3, -1)        # from issue-time context, [1,1,N,d] each
            h = blk(h, g, film)
        s = self.summary(h.permute(0, 2, 1, 3).reshape(B, N, T * h.shape[-1]))
        q = (s[:, None] + self.hor.weight[None, :, None] + self.time_fut(time_fut)[:, :, None]
             + self.fut_base(fut_base))
        q = self.dec_ln(q)
        if ctx is not None:
            cf = ctx[:, 1:]                                                  # scheduled context of each target bucket
            q = q + self.events.dec_ctx(cf)
            gamma, beta = self.events.dec_film(cf).chunk(2, -1)
            q = q * (1 + gamma) + beta
        return self.head(q).squeeze(-1)


def build_model(cfg, graph, norm, n_event: int) -> EventPatchForecaster:
    from .data import FUTURE_BASE_FEATURES, HIST_FEATURES, TIME_FEATURES, static_normalized
    gb = GraphBuffers(torch.as_tensor(graph.patch_idx), torch.as_tensor(graph.road_patch), torch.as_tensor(graph.src),
                      torch.as_tensor(graph.dst), torch.as_tensor(static_normalized(graph, norm)))
    m = cfg.model
    return EventPatchForecaster(gb, len(HIST_FEATURES), len(TIME_FEATURES), len(FUTURE_BASE_FEATURES), n_event,
                                cfg.data.history_steps, cfg.data.horizon_steps, m.hidden, m.heads, m.blocks,
                                m.dropout, m.use_events, m.event_hops, z_bias=norm.get("target_z_mean_train", 0.0))
