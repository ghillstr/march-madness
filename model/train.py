"""Training loop with early stopping for MarchMadnessNet."""

import os
import sys
import json
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.network import MarchMadnessNet
from model.dataset import MarchMadnessDataset
from features.feature_engineering import build_training_data
from db.database import get_db
from config import (
    MODEL_DIR, BATCH_SIZE, MAX_EPOCHS, EARLY_STOP_PATIENCE,
    LEARNING_RATE, WEIGHT_DECAY, WIN_LOSS_WEIGHT, MARGIN_LOSS_WEIGHT,
    TRAIN_END, VAL_SEASON, TEST_SEASON,
)


def train_model():
    """Train the model and save the best checkpoint."""
    os.makedirs(MODEL_DIR, exist_ok=True)

    print("Loading training data from database...")
    with get_db() as conn:
        features, win_labels, margin_labels, seasons = build_training_data(conn)

    if features is None or len(features) == 0:
        print("ERROR: No training data found. Run scrapers first.")
        return None

    print(f"Total samples: {len(features)}")

    # Split by season
    train_mask = seasons <= TRAIN_END
    val_mask = seasons == VAL_SEASON
    test_mask = seasons == TEST_SEASON

    X_train = features[train_mask]
    y_win_train = win_labels[train_mask]
    y_margin_train = margin_labels[train_mask]

    X_val = features[val_mask]
    y_win_val = win_labels[val_mask]
    y_margin_val = margin_labels[val_mask]

    X_test = features[test_mask]
    y_win_test = win_labels[test_mask]
    y_margin_test = margin_labels[test_mask]

    print(f"Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")

    # Create datasets (normalize using training stats)
    train_ds = MarchMadnessDataset(X_train, y_win_train, y_margin_train, normalize=True)
    val_ds = MarchMadnessDataset(X_val, y_win_val, y_margin_val, normalize=True,
                                  mean=train_ds.mean, std=train_ds.std)
    test_ds = MarchMadnessDataset(X_test, y_win_test, y_margin_test, normalize=True,
                                   mean=train_ds.mean, std=train_ds.std)

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE)
    test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE)

    # Model, loss, optimizer
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = MarchMadnessNet().to(device)
    bce_loss = nn.BCELoss()
    mse_loss = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE,
                                  weight_decay=WEIGHT_DECAY)

    print(f"\nTraining on {device}...")
    best_val_loss = float("inf")
    patience_counter = 0

    for epoch in range(MAX_EPOCHS):
        # Training
        model.train()
        train_loss_sum = 0
        train_correct = 0
        train_total = 0

        for X, y_win, y_margin in train_loader:
            X, y_win, y_margin = X.to(device), y_win.to(device), y_margin.to(device)
            optimizer.zero_grad()

            win_prob, margin_pred = model(X)
            loss_w = bce_loss(win_prob, y_win)
            loss_m = mse_loss(margin_pred, y_margin)
            loss = WIN_LOSS_WEIGHT * loss_w + MARGIN_LOSS_WEIGHT * loss_m

            loss.backward()
            optimizer.step()

            train_loss_sum += loss.item() * len(X)
            preds = (win_prob > 0.5).float()
            train_correct += (preds == y_win).sum().item()
            train_total += len(X)

        # Validation
        model.eval()
        val_loss_sum = 0
        val_correct = 0
        val_total = 0

        with torch.no_grad():
            for X, y_win, y_margin in val_loader:
                X, y_win, y_margin = X.to(device), y_win.to(device), y_margin.to(device)
                win_prob, margin_pred = model(X)
                loss_w = bce_loss(win_prob, y_win)
                loss_m = mse_loss(margin_pred, y_margin)
                loss = WIN_LOSS_WEIGHT * loss_w + MARGIN_LOSS_WEIGHT * loss_m

                val_loss_sum += loss.item() * len(X)
                preds = (win_prob > 0.5).float()
                val_correct += (preds == y_win).sum().item()
                val_total += len(X)

        train_loss = train_loss_sum / train_total
        val_loss = val_loss_sum / max(val_total, 1)
        train_acc = train_correct / train_total * 100
        val_acc = val_correct / max(val_total, 1) * 100

        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"Epoch {epoch+1:3d} | "
                  f"Train Loss: {train_loss:.4f} Acc: {train_acc:.1f}% | "
                  f"Val Loss: {val_loss:.4f} Acc: {val_acc:.1f}%")

        # Early stopping
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            torch.save({
                "model_state": model.state_dict(),
                "mean": train_ds.mean.tolist(),
                "std": train_ds.std.tolist(),
                "val_loss": val_loss,
                "val_acc": val_acc,
                "epoch": epoch + 1,
            }, os.path.join(MODEL_DIR, "best_model.pt"))
        else:
            patience_counter += 1
            if patience_counter >= EARLY_STOP_PATIENCE:
                print(f"\nEarly stopping at epoch {epoch+1}")
                break

    # Evaluate on test set
    print("\n--- Test Set Evaluation ---")
    checkpoint = torch.load(os.path.join(MODEL_DIR, "best_model.pt"),
                            weights_only=False)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    test_correct = 0
    test_total = 0
    all_probs = []
    all_labels = []
    all_margins_pred = []
    all_margins_true = []

    with torch.no_grad():
        for X, y_win, y_margin in test_loader:
            X, y_win, y_margin = X.to(device), y_win.to(device), y_margin.to(device)
            win_prob, margin_pred = model(X)
            preds = (win_prob > 0.5).float()
            test_correct += (preds == y_win).sum().item()
            test_total += len(X)
            all_probs.extend(win_prob.cpu().numpy().flatten())
            all_labels.extend(y_win.cpu().numpy().flatten())
            all_margins_pred.extend(margin_pred.cpu().numpy().flatten())
            all_margins_true.extend(y_margin.cpu().numpy().flatten())

    test_acc = test_correct / max(test_total, 1) * 100
    margin_mae = np.mean(np.abs(np.array(all_margins_pred) - np.array(all_margins_true)))

    print(f"Test Accuracy: {test_acc:.1f}%")
    print(f"Margin MAE: {margin_mae:.2f} points")
    print(f"Best model saved (val loss: {best_val_loss:.4f})")

    # Save metrics
    metrics = {
        "test_accuracy": test_acc,
        "margin_mae": float(margin_mae),
        "val_loss": best_val_loss,
        "val_accuracy": checkpoint["val_acc"],
        "best_epoch": checkpoint["epoch"],
        "train_samples": int(len(X_train)),
        "val_samples": int(len(X_val)),
        "test_samples": int(len(X_test)),
    }
    with open(os.path.join(MODEL_DIR, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    return model


if __name__ == "__main__":
    train_model()
