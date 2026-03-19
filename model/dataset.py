"""PyTorch Dataset for March Madness matchup data."""

import numpy as np
import torch
from torch.utils.data import Dataset


class MarchMadnessDataset(Dataset):
    """Dataset wrapping feature arrays, win labels, and margin labels."""

    def __init__(self, features, win_labels, margin_labels, normalize=True,
                 mean=None, std=None):
        """
        Args:
            features: (N, 29) numpy array
            win_labels: (N,) numpy array of 0/1
            margin_labels: (N,) numpy array of score margins
            normalize: whether to z-score normalize features
            mean, std: precomputed normalization params (use training set stats)
        """
        self.features = features.copy()
        self.win_labels = win_labels
        self.margin_labels = margin_labels

        if normalize:
            if mean is None:
                self.mean = np.mean(self.features, axis=0)
                self.std = np.std(self.features, axis=0)
            else:
                self.mean = mean
                self.std = std
            self.std[self.std < 1e-8] = 1.0
            self.features = (self.features - self.mean) / self.std
        else:
            self.mean = np.zeros(features.shape[1])
            self.std = np.ones(features.shape[1])

        # Convert to tensors
        self.X = torch.tensor(self.features, dtype=torch.float32)
        self.y_win = torch.tensor(self.win_labels, dtype=torch.float32).unsqueeze(1)
        self.y_margin = torch.tensor(self.margin_labels, dtype=torch.float32).unsqueeze(1)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y_win[idx], self.y_margin[idx]
