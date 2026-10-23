import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta

# ----------------------------
# Activity definitions (zones)
# ----------------------------
ZONES = {
    "Zone A: Customer Interaction": [
        "A1_View_Product", "A2_Add_To_Cart", "A3_Checkout_Started",
        "A4_Login_Customer", "A5_Enter_Guest_Info", "A6_Submit_Order"
    ],
    "Zone B: Payment & Risk": [
        "B1_Initiate_Payment", "B2_PayPal_Payment", "B3_CreditCard_Payment", "B4_Invoice_Payment",
        "B5_Fraud_Review", "B6_Request_Verification", "B7_Receive_Verification",
        "B8_Payment_Confirmed", "B9_Payment_Failed"
    ],
    "Zone C: Fulfillment": [
        "C1_Reserve_Stock", "C2_Pick_Items", "C3_Print_Documents", "C4_Pack_Items"
    ],
    "Zone D: Quality": [
        "D1_Quality_Check", "D2_Rework", "D3_QA_Completed"
    ],
    "Zone E: Logistics": [
        "E1_Create_Shipping_Label", "E2_Handover_To_Courier", "E3_Out_For_Delivery", "E4_Dispatch",
        "E5_Delivered"
    ]
}
ACT2ZONE = {a: z for z, acts in ZONES.items() for a in acts}

# ----------------------------
# Random helpers
# ----------------------------
def triangular_minutes(a, m, b):
    return float(np.random.triangular(a, m, b))

def lognormal_minutes(mu, sigma):
    # mu/sigma in log-space
    return float(np.random.lognormal(mu, sigma))

def gamma_minutes(k, theta):
    return float(np.random.gamma(k, theta))

def next_hour(ts: datetime) -> datetime:
    return (ts.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))

def add_wait_hours(ts: datetime, hmin: float, hmax: float, weekend_factor=1.2, night_factor=1.3) -> datetime:
    """
    Adds queue/transit waiting time in hours with mild weekend/night effects.
    """
    h = float(np.random.uniform(hmin, hmax))
    if ts.weekday() >= 5:
        h *= weekend_factor
    if ts.hour >= 20 or ts.hour <= 6:
        h *= night_factor
    return ts + timedelta(hours=h)

# ----------------------------
# Baseline service durations (minutes)
# ----------------------------
BASE_DURATION = {
    # Zone A
    "A1_View_Product": lambda: triangular_minutes(0, 2, 5),
    "A2_Add_To_Cart": lambda: triangular_minutes(0, 2, 5),
    "A3_Checkout_Started": lambda: lognormal_minutes(1.2, 0.3),
    "A4_Login_Customer": lambda: triangular_minutes(1, 3, 7),
    "A5_Enter_Guest_Info": lambda: triangular_minutes(1, 4, 10),
    "A6_Submit_Order": lambda: lognormal_minutes(1.0, 0.25),

    # Zone B
    "B1_Initiate_Payment": lambda: triangular_minutes(1, 3, 8),
    "B2_PayPal_Payment": lambda: lognormal_minutes(1.5, 0.3),
    "B3_CreditCard_Payment": lambda: lognormal_minutes(2.0, 0.4),
    "B4_Invoice_Payment": lambda: triangular_minutes(2, 4, 15),
    "B5_Fraud_Review": lambda: gamma_minutes(3, 7),
    "B6_Request_Verification": lambda: triangular_minutes(1, 3, 10),
    "B7_Receive_Verification": lambda: triangular_minutes(1, 3, 6),
    "B8_Payment_Confirmed": lambda: triangular_minutes(1, 2, 6),
    "B9_Payment_Failed": lambda: triangular_minutes(1, 3, 8),

    # Zone C
    "C1_Reserve_Stock": lambda: triangular_minutes(2, 6, 20),
    "C2_Pick_Items": lambda: gamma_minutes(4, 8),
    "C3_Print_Documents": lambda: triangular_minutes(1, 2, 6),
    "C4_Pack_Items": lambda: gamma_minutes(3, 10),

    # Zone D
    "D1_Quality_Check": lambda: gamma_minutes(3, 8),
    "D2_Rework": lambda: gamma_minutes(5, 10),
    "D3_QA_Completed": lambda: triangular_minutes(1, 2, 5),

    # Zone E
    "E1_Create_Shipping_Label": lambda: triangular_minutes(1, 2, 6),
    "E2_Handover_To_Courier": lambda: triangular_minutes(2, 6, 20),
    "E3_Out_For_Delivery": lambda: triangular_minutes(1, 3, 10),
    "E4_Dispatch": lambda: triangular_minutes(1, 2, 6),
    "E5_Delivered": lambda: triangular_minutes(1, 2, 5),
}

import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta

# keep your ZONES, ACT2ZONE, helpers, BASE_DURATION exactly as-is above

def generate_order_log_v5_capacity_backlog(
    n_days=35,
    base_daily_orders=120,
    start_date="2024-01-01",

    # Zone-specific drifts (make them mostly non-overlapping)
    drift_A=(12, 7, 2.2),   # (start_day, days, multiplier) arrivals
    drift_B=(6,  9),        # risk drift window
    drift_C=(16, 10),       # fulfillment bottleneck window
    drift_D=(22, 7),        # quality drift window

    # Payment / risk behavior
    fraud_review_prob_base=0.12,
    fraud_review_prob_drift=0.55,
    verification_loop_prob_base=0.06,
    verification_loop_prob_drift=0.30,
    payment_fail_prob_base=0.03,
    payment_fail_prob_drift=0.20,   # <-- stronger so flow stops in B during drift

    # Fulfillment system capacity (THIS creates real backlog)
    fulfill_capacity_base=110,      # how many paid orders C can start per day
    fulfill_capacity_drift=55,      # reduced capacity during drift_C
    fulfill_wait_if_backlog_hours=(4.0, 20.0),  # waiting added when backlog exists

    # Quality behavior
    qc_prob_base=0.20,
    qc_prob_drift=0.60,
    rework_prob_base=0.12,
    rework_prob_drift=0.40,

    # Logistics batching
    shipping_batch_daily=True,
    shipping_cutoff_hour=17,
    next_day_ship_hour=9,
    logistics_transit_hours=(12.0, 72.0),

    # Noise knobs (keep small while validating)
    p_checkout_abandon=0.02,
    p_extra_event=0.02,
    extra_event_pool=("B8_Payment_Confirmed","C4_Pack_Items","E4_Dispatch","B5_Fraud_Review"),

    seed=42,
    include_zone=True

):
    random.seed(seed)
    np.random.seed(seed)
    start_dt = pd.to_datetime(start_date).to_pydatetime()

    def in_range(day_idx, start, days):
        return start <= day_idx < start + days

    driftA_start, driftA_days, driftA_mult = drift_A
    driftB_start, driftB_days = drift_B
    driftC_start, driftC_days = drift_C
    driftD_start, driftD_days = drift_D

    def in_drift_A(day): return in_range(day, driftA_start, driftA_days)
    def in_drift_B(day): return in_range(day, driftB_start, driftB_days)
    def in_drift_C(day): return in_range(day, driftC_start, driftC_days)
    def in_drift_D(day): return in_range(day, driftD_start, driftD_days)

    rows = []
    case_id = 0

    def next_day_morning(ts: datetime) -> datetime:
        return (ts + timedelta(days=1)).replace(hour=next_day_ship_hour, minute=0, second=0, microsecond=0)

    def inject_extra_event(current_ts: datetime, day_idx: int, cid: int):
        if random.random() >= p_extra_event:
            return
        act = random.choice(list(extra_event_pool))
        ts_extra = current_ts + timedelta(seconds=random.randint(1, 20))
        rows.append({
            "case_id": cid,
            "concept:name": act,
            "zone": (ACT2ZONE.get(act, "__extra__") if include_zone else None),
            "time:timestamp": ts_extra,
            "in_drift_A": int(in_drift_A(day_idx)),
            "in_drift_B": int(in_drift_B(day_idx)),
            "in_drift_C": int(in_drift_C(day_idx)),
            "in_drift_D": int(in_drift_D(day_idx)),
        })

    # --- NEW: backlog queue for fulfillment start (orders waiting to enter Zone C)
    backlog_paid = []  # list of (case_id, ts_at_paid, ts_current)

    for day in range(n_days):
        day_start = start_dt + timedelta(days=day)
        weekday = day_start.weekday()
        season = 0.85 if weekday >= 5 else 1.0

        lam = base_daily_orders * season * (driftA_mult if in_drift_A(day) else 1.0)
        n_orders = int(np.random.poisson(lam))

        # daily capacity of fulfillment (Zone C entry)
        cap = fulfill_capacity_drift if in_drift_C(day) else fulfill_capacity_base

        # Arrival profile
        arrival_offsets = []
        for _ in range(n_orders):
            h = np.random.normal(14, 3) if random.random() < 0.65 else np.random.normal(10, 2)
            h = min(max(h, 0.0), 23.99)
            m = int((h - int(h)) * 60)
            arrival_offsets.append((int(h), m))
        arrival_offsets.sort()

        # helper to emit one event and advance timestamp
        def emit(cid, act, ts):
            rows.append({
                "case_id": cid,
                "concept:name": act,
                "zone": (ACT2ZONE.get(act, "__unknown__") if include_zone else None),
                "time:timestamp": ts,
                "in_drift_A": int(in_drift_A(day)),
                "in_drift_B": int(in_drift_B(day)),
                "in_drift_C": int(in_drift_C(day)),
                "in_drift_D": int(in_drift_D(day)),
            })

        # ---------- 1) generate new orders through A + B, then enqueue paid ones ----------
        for hh, mm in arrival_offsets:
            ts = day_start.replace(hour=hh, minute=mm, second=0, microsecond=0)
            cid = case_id

            def do(act, dur_min):
                nonlocal ts
                emit(cid, act, ts)
                ts = ts + timedelta(minutes=float(dur_min)) + timedelta(seconds=random.randint(5, 90))

            # Zone A
            do("A1_View_Product", BASE_DURATION["A1_View_Product"]())
            do("A2_Add_To_Cart", BASE_DURATION["A2_Add_To_Cart"]())
            do("A3_Checkout_Started", BASE_DURATION["A3_Checkout_Started"]())
            if random.random() < 0.35:
                do("A5_Enter_Guest_Info", BASE_DURATION["A5_Enter_Guest_Info"]())
            else:
                do("A4_Login_Customer", BASE_DURATION["A4_Login_Customer"]())
            do("A6_Submit_Order", BASE_DURATION["A6_Submit_Order"]())

            inject_extra_event(ts, day, cid)

            if random.random() < p_checkout_abandon:
                case_id += 1
                continue

            # Zone B (risk drift)
            do("B1_Initiate_Payment", BASE_DURATION["B1_Initiate_Payment"]())
            method = random.choice(["B2_PayPal_Payment", "B3_CreditCard_Payment", "B4_Invoice_Payment"])
            do(method, BASE_DURATION[method]())

            fr_prob = fraud_review_prob_drift if in_drift_B(day) else fraud_review_prob_base
            ver_prob = verification_loop_prob_drift if in_drift_B(day) else verification_loop_prob_base
            fail_prob = payment_fail_prob_drift if in_drift_B(day) else payment_fail_prob_base

            if random.random() < fr_prob:
                # fraud review adds time
                ts = add_wait_hours(ts, 0.5, 3.0, weekend_factor=1.1, night_factor=1.15)
                do("B5_Fraud_Review", BASE_DURATION["B5_Fraud_Review"]())

            if random.random() < ver_prob:
                loops = np.random.choice([1, 2], p=[0.6, 0.4])
                for _ in range(loops):
                    do("B6_Request_Verification", BASE_DURATION["B6_Request_Verification"]())
                    do("B7_Receive_Verification", BASE_DURATION["B7_Receive_Verification"]())

            if random.random() < fail_prob:
                do("B9_Payment_Failed", BASE_DURATION["B9_Payment_Failed"]())
                case_id += 1
                continue

            # payment confirmed (batching to next hour)
            ts = next_hour(ts)
            do("B8_Payment_Confirmed", BASE_DURATION["B8_Payment_Confirmed"]())
            inject_extra_event(ts, day, cid)

            # enqueue paid case for fulfillment entry later (capacity-limited)
            backlog_paid.append((cid, ts, ts))
            case_id += 1

        # ---------- 2) start fulfillment for up to cap backlog cases today ----------
        # process oldest paid first
        backlog_paid.sort(key=lambda x: x[1])  # sort by paid timestamp
        todays = backlog_paid[:cap]
        backlog_paid = backlog_paid[cap:]

        for cid, ts_paid, ts_cur in todays:
            ts = max(ts_cur, day_start.replace(hour=8, minute=0, second=0, microsecond=0))

            # if backlog exists (i.e. cases still waiting), add wait to simulate queue pressure
            if len(backlog_paid) > 0:
                ts = add_wait_hours(ts, fulfill_wait_if_backlog_hours[0], fulfill_wait_if_backlog_hours[1])

            # Zone C
            def doC(act, dur_min):
                nonlocal ts
                emit(cid, act, ts)
                ts = ts + timedelta(minutes=float(dur_min)) + timedelta(seconds=random.randint(5, 90))

            doC("C1_Reserve_Stock", BASE_DURATION["C1_Reserve_Stock"]())
            parallel = ["C2_Pick_Items", "C3_Print_Documents"]
            random.shuffle(parallel)
            for act in parallel:
                doC(act, BASE_DURATION[act]())
            doC("C4_Pack_Items", BASE_DURATION["C4_Pack_Items"]())

            # Zone D (quality drift)
            qc_prob = qc_prob_drift if in_drift_D(day) else qc_prob_base
            rework_prob = rework_prob_drift if in_drift_D(day) else rework_prob_base

            if random.random() < qc_prob:
                ts = add_wait_hours(ts, 0.0, 2.0)
                emit(cid, "D1_Quality_Check", ts)
                ts += timedelta(minutes=float(BASE_DURATION["D1_Quality_Check"]()))
                if random.random() < rework_prob:
                    ts = add_wait_hours(ts, 0.5, 4.0)
                    emit(cid, "D2_Rework", ts)
                    ts += timedelta(minutes=float(BASE_DURATION["D2_Rework"]()))
                    ts = add_wait_hours(ts, 0.0, 2.0)
                    emit(cid, "D1_Quality_Check", ts)
                    ts += timedelta(minutes=float(BASE_DURATION["D1_Quality_Check"]()))
                emit(cid, "D3_QA_Completed", ts)
                ts += timedelta(minutes=float(BASE_DURATION["D3_QA_Completed"]()))

            # Zone E (batching/cutoff)
            emit(cid, "E1_Create_Shipping_Label", ts); ts += timedelta(minutes=float(BASE_DURATION["E1_Create_Shipping_Label"]()))
            emit(cid, "E2_Handover_To_Courier", ts);   ts += timedelta(minutes=float(BASE_DURATION["E2_Handover_To_Courier"]()))

            if shipping_batch_daily and ts.hour >= shipping_cutoff_hour:
                ts = next_day_morning(ts)

            ts = add_wait_hours(ts, logistics_transit_hours[0], logistics_transit_hours[1],
                                weekend_factor=1.3, night_factor=1.2)

            emit(cid, "E3_Out_For_Delivery", ts); ts += timedelta(minutes=float(BASE_DURATION["E3_Out_For_Delivery"]()))
            emit(cid, "E4_Dispatch", ts);         ts += timedelta(minutes=float(BASE_DURATION["E4_Dispatch"]()))
            emit(cid, "E5_Delivered", ts);        ts += timedelta(minutes=float(BASE_DURATION["E5_Delivered"]()))

    df = pd.DataFrame(rows)
    df["time:timestamp"] = pd.to_datetime(df["time:timestamp"])
    df = df.sort_values(["case_id", "time:timestamp"]).reset_index(drop=True)
    return df



if __name__ == "__main__":
    df = generate_order_log_v5_capacity_backlog(include_zone=False)
    df.to_csv("online_order_fulfillment_log.csv", index=False)
    print("Saved: online_order_fulfillment_log.csv")
    print("Cases:", df["case_id"].nunique(), "Events:", len(df), "Activities:", df["concept:name"].nunique())
    print(df.head())
