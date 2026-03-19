"""MarchMadnessNet: dual-head neural network for win probability and margin prediction."""

import torch
import torch.nn as nn
from config import NUM_FEATURES, HIDDEN_SIZES, DROPOUT_RATES


class MarchMadnessNet(nn.Module):
    """Dual-head network predicting both win probability and score margin.

    Architecture:
        Input (29) → Linear(128) → BN → ReLU → Dropout(0.3)
                   → Linear(64)  → BN → ReLU → Dropout(0.3)
                   → Linear(32)  → BN → ReLU → Dropout(0.2)
                   ├→ Win Head:   Linear(16) → ReLU → Linear(1) → Sigmoid
                   └→ Margin Head: Linear(16) → ReLU → Linear(1)
    """

    def __init__(self, input_size=NUM_FEATURES,
                 hidden_sizes=None, dropout_rates=None):
        super().__init__()
        hidden_sizes = hidden_sizes or HIDDEN_SIZES
        dropout_rates = dropout_rates or DROPOUT_RATES

        # Shared backbone
        layers = []
        in_size = input_size
        for h, d in zip(hidden_sizes, dropout_rates):
            layers.extend([
                nn.Linear(in_size, h),
                nn.BatchNorm1d(h),
                nn.ReLU(),
                nn.Dropout(d),
            ])
            in_size = h
        self.backbone = nn.Sequential(*layers)

        # Win probability head
        self.win_head = nn.Sequential(
            nn.Linear(in_size, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid(),
        )

        # Margin prediction head
        self.margin_head = nn.Sequential(
            nn.Linear(in_size, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        """Forward pass.

        Args:
            x: (batch, 29) feature tensor
        Returns:
            win_prob: (batch, 1) win probability [0, 1]
            margin: (batch, 1) predicted score margin
        """
        shared = self.backbone(x)
        win_prob = self.win_head(shared)
        margin = self.margin_head(shared)
        return win_prob, margin
