import logging
from pathlib import Path
from typing import Optional

import numpy as np

try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.envs import DummyVecEnv
    import gym
except Exception:
    # ML libraries are optional; log if missing but continue gracefully
    PPO = None
    gym = None

logger = logging.getLogger(__name__)


def load_behavior_model(path: str) -> Optional[object]:
    """Load a trained RL model if it exists."""
    if PPO is None or not Path(path).exists():
        logger.debug("Behavior model not available")
        return None
    try:
        model = PPO.load(path)
        logger.debug("Loaded behavior model from %s", path)
        return model
    except Exception as exc:
        logger.debug("Failed to load behavior model: %s", exc)
        return None


def predict_hold_duration(model: Optional[object], default: float) -> float:
    """Use the RL model to predict a realistic hold duration."""
    if model is None:
        return default

    # The observation could include time of day or other context. Here we use a
    # simple random value as a placeholder observation.
    obs = np.array([[default]])
    try:
        action, _ = model.predict(obs, deterministic=False)
        duration = float(action[0])
        # Constrain duration between 3 and 6 seconds
        return max(3.0, min(6.0, duration))
    except Exception as exc:
        logger.debug("Prediction failed: %s", exc)
        return default


def example_training(path: str = "models/behavior_model.zip") -> None:
    """Example of training an RL model to mimic human timings."""
    if PPO is None:
        raise RuntimeError("stable-baselines3 not installed")

    class HoldEnv(gym.Env):
        """Minimal environment where the agent outputs a hold duration."""

        def __init__(self):
            super().__init__()
            self.action_space = gym.spaces.Box(low=3.0, high=6.0, shape=(1,))
            self.observation_space = gym.spaces.Box(low=0, high=1, shape=(1,))

        def reset(self):
            return np.array([0.5])

        def step(self, action):
            # Reward smooth, human-like durations around 4.5s
            duration = action[0]
            reward = -abs(duration - 4.5)
            return np.array([0.5]), reward, True, {}

    env = DummyVecEnv([HoldEnv])
    model = PPO("MlpPolicy", env, verbose=0)
    model.learn(total_timesteps=1000)
    Path("models").mkdir(exist_ok=True)
    model.save(path)
    logger.info("Saved trained behavior model to %s", path)
