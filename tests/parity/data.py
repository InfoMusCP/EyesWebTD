"""Synthetic signals for the parity tests: smooth movement, skeletons, pulse trains. All float64, deterministic."""
import numpy as np


def smooth_walk(n, dims=3, rate=60.0, seed=1, scale=1.0):
    """A smooth random trajectory (n, dims): a sum of a few low-frequency sinusoids with random phase and amplitude."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / rate
    out = np.zeros((n, dims))
    for d in range(dims):
        for _ in range(4):
            out[:, d] += rng.uniform(0.2, 1.0) * np.sin(2 * np.pi * rng.uniform(0.3, 3.0) * t + rng.uniform(0, 2 * np.pi))
    return scale * out


def skeleton(n, joints=5, dims=3, rate=60.0, seed=2):
    """A moving skeleton, joint-major like the CHOP channels: (n, joints * dims), joint j axis d at column j * dims + d."""
    return np.hstack([smooth_walk(n, dims, rate, seed + j) + j for j in range(joints)])


def pulse_train(n, period=10, jitter=0, seed=3, density=None):
    """A 0/1 pulse train of length n; with `jitter` the period varies by up to that many samples."""
    rng = np.random.default_rng(seed)
    out = np.zeros(n)
    if density is not None:
        out[rng.random(n) < density] = 1.0
        return out
    i = 0
    while i < n:
        out[i] = 1.0
        i += max(1, period + (int(rng.integers(-jitter, jitter + 1)) if jitter else 0))
    return out


def noisy_sine(n, rate=60.0, freq=2.0, noise=0.1, seed=4):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / rate
    return np.sin(2 * np.pi * freq * t) + noise * rng.standard_normal(n)
