#!/usr/bin/env python3

PROMOTION_THRESHOLDS = {
    "F1": {"l1_to_l2": 0.70, "l2_to_l3": 0.80, "min_confidence_l1": 0.55, "min_confidence_l2": 0.75},
    "F2": {"l1_to_l2": 0.65, "l2_to_l3": 0.75, "min_confidence_l1": 0.50, "min_confidence_l2": 0.70},
    "F3": {"l1_to_l2": 0.68, "l2_to_l3": 0.78, "min_confidence_l1": 0.55, "min_confidence_l2": 0.72},
    "F4": {"l1_to_l2": 0.70, "l2_to_l3": 0.82, "min_confidence_l1": 0.58, "min_confidence_l2": 0.76},
    "F5": {"l1_to_l2": 0.74, "l2_to_l3": 0.84, "min_confidence_l1": 0.60, "min_confidence_l2": 0.78},
    "F6": {"l1_to_l2": 0.76, "l2_to_l3": 0.86, "min_confidence_l1": 0.62, "min_confidence_l2": 0.80},
    "F7": {"l1_to_l2": 0.78, "l2_to_l3": 0.88, "min_confidence_l1": 0.65, "min_confidence_l2": 0.82},
}

DEFAULT_FAMILY = "F1"
MAX_L2_TO_L3_MAPE_PERCENT = 20.0
