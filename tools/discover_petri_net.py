from pm4py.objects.petri_net.obj import PetriNet, Marking
from pm4py.objects.petri_net.utils import petri_utils
from pm4py.objects.petri_net.exporter import exporter as pnml_exporter
from pm4py.visualization.petri_net import visualizer as pn_visualizer

def build_fixed_order_petri_net():
    net = PetriNet("order_process_fixed")
    p = {}

    def place(name):
        p[name] = PetriNet.Place(name)
        net.places.add(p[name])
        return p[name]

    def trans(name, label=None):
        t = PetriNet.Transition(name, label)
        net.transitions.add(t)
        return t

    # --- Places (states) ---
    start = place("p_start")
    a1 = place("p_after_A1")
    a2 = place("p_after_A2")
    a3 = place("p_after_A3")
    a4 = place("p_after_A4A5")
    a6 = place("p_after_A6")

    b1 = place("p_after_B1")
    b_m = place("p_after_B_method")
    b_fr = place("p_after_B5")
    b_ver = place("p_after_verification")
    b_ok = place("p_paid")
    b_fail = place("p_payment_failed")

    c1 = place("p_after_C1")
    c_and = place("p_and_split")
    c_pick = place("p_after_pick")
    c_print = place("p_after_print")
    c_join = place("p_and_join")
    c_pack = place("p_after_pack")

    # --- FIX: proper AND-split branch places ---
    c_pick_ready = place("p_pick_ready")
    c_print_ready = place("p_print_ready")
    c_after_parallel = place("p_after_parallel")


    d_in = place("p_qc_entry")
    d_done = place("p_qc_done")

    e1 = place("p_after_E1")
    e2 = place("p_after_E2")
    e3 = place("p_after_E3")
    e4 = place("p_after_E4")
    end = place("p_end")

    # --- Transitions (visible labels = your activities) ---
    tA1 = trans("tA1","A1_View_Product")
    tA2 = trans("tA2","A2_Add_To_Cart")
    tA3 = trans("tA3","A3_Checkout_Started")
    tA4 = trans("tA4","A4_Login_Customer")
    tA5 = trans("tA5","A5_Enter_Guest_Info")
    tA6 = trans("tA6","A6_Submit_Order")

    tB1 = trans("tB1","B1_Initiate_Payment")
    tB2 = trans("tB2","B2_PayPal_Payment")
    tB3 = trans("tB3","B3_CreditCard_Payment")
    tB4 = trans("tB4","B4_Invoice_Payment")
    tB5 = trans("tB5","B5_Fraud_Review")
    tB6 = trans("tB6","B6_Request_Verification")
    tB7 = trans("tB7","B7_Receive_Verification")
    tB8 = trans("tB8","B8_Payment_Confirmed")
    tB9 = trans("tB9","B9_Payment_Failed")

    tC1 = trans("tC1","C1_Reserve_Stock")
    # AND split/join via silent transitions
    tSplit = trans("tSplit", None)
    tJoin  = trans("tJoin", None)
    tC2 = trans("tC2","C2_Pick_Items")
    tC3 = trans("tC3","C3_Print_Documents")
    tC4 = trans("tC4","C4_Pack_Items")

    # QC optional + rework loop
    tQC = trans("tQC","D1_Quality_Check")
    tRW = trans("tRW","D2_Rework")
    tQDone = trans("tQDone","D3_QA_Completed")
    tSkipQC = trans("tSkipQC", None)  # skip

    tE1 = trans("tE1","E1_Create_Shipping_Label")
    tE2 = trans("tE2","E2_Handover_To_Courier")
    tE3 = trans("tE3","E3_Out_For_Delivery")
    tE4 = trans("tE4","E4_Dispatch")
    tE5 = trans("tE5","E5_Delivered")
    # --- FIX: allow payment-failed to reach end (WF-net soundness) ---
    tCancel = trans("tCancel", None)  # τ

    # --- Arcs ---
    petri_utils.add_arc_from_to(start, tA1, net); petri_utils.add_arc_from_to(tA1, a1, net)
    petri_utils.add_arc_from_to(a1, tA2, net);   petri_utils.add_arc_from_to(tA2, a2, net)
    petri_utils.add_arc_from_to(a2, tA3, net);   petri_utils.add_arc_from_to(tA3, a3, net)

    # XOR: login OR guest info
    petri_utils.add_arc_from_to(a3, tA4, net); petri_utils.add_arc_from_to(tA4, a4, net)
    petri_utils.add_arc_from_to(a3, tA5, net); petri_utils.add_arc_from_to(tA5, a4, net)

    petri_utils.add_arc_from_to(a4, tA6, net); petri_utils.add_arc_from_to(tA6, a6, net)

    # payment segment
    petri_utils.add_arc_from_to(a6, tB1, net); petri_utils.add_arc_from_to(tB1, b1, net)

    # XOR: payment method
    for tm in (tB2,tB3,tB4):
        petri_utils.add_arc_from_to(b1, tm, net)
        petri_utils.add_arc_from_to(tm, b_m, net)

    # optional fraud review after method
    petri_utils.add_arc_from_to(b_m, tB5, net); petri_utils.add_arc_from_to(tB5, b_fr, net)

    # verification loop (simple: request -> receive, may repeat in log; model allows one loop; log repair will handle extra)
    petri_utils.add_arc_from_to(b_m, tB6, net); petri_utils.add_arc_from_to(tB6, b_ver, net)
    petri_utils.add_arc_from_to(b_fr, tB6, net)  # after fraud review can verify too
    petri_utils.add_arc_from_to(b_ver, tB7, net); petri_utils.add_arc_from_to(tB7, b_m, net)

    # confirm or fail
    petri_utils.add_arc_from_to(b_m, tB8, net); petri_utils.add_arc_from_to(tB8, b_ok, net)
    petri_utils.add_arc_from_to(b_m, tB9, net); petri_utils.add_arc_from_to(tB9, b_fail, net)
    # --- FIX: close failed cases so all paths reach sink ---
    petri_utils.add_arc_from_to(b_fail, tCancel, net)
    petri_utils.add_arc_from_to(tCancel, end, net)

    # fulfillment starts only if paid
    petri_utils.add_arc_from_to(b_ok, tC1, net); petri_utils.add_arc_from_to(tC1, c1, net)

    # --- FIXED AND split/join (real parallelism) ---
    petri_utils.add_arc_from_to(c1, tSplit, net)
    petri_utils.add_arc_from_to(tSplit, c_pick_ready, net)
    petri_utils.add_arc_from_to(tSplit, c_print_ready, net)

    petri_utils.add_arc_from_to(c_pick_ready, tC2, net)
    petri_utils.add_arc_from_to(tC2, c_pick, net)

    petri_utils.add_arc_from_to(c_print_ready, tC3, net)
    petri_utils.add_arc_from_to(tC3, c_print, net)

    petri_utils.add_arc_from_to(c_pick, tJoin, net)
    petri_utils.add_arc_from_to(c_print, tJoin, net)
    petri_utils.add_arc_from_to(tJoin, c_after_parallel, net)

    petri_utils.add_arc_from_to(c_after_parallel, tC4, net)
    petri_utils.add_arc_from_to(tC4, c_pack, net)

    # QC optional: skip OR do QC (+ optional rework loop)
    petri_utils.add_arc_from_to(c_pack, tSkipQC, net); petri_utils.add_arc_from_to(tSkipQC, d_done, net)

    petri_utils.add_arc_from_to(c_pack, tQC, net); petri_utils.add_arc_from_to(tQC, d_in, net)
    petri_utils.add_arc_from_to(d_in, tRW, net); petri_utils.add_arc_from_to(tRW, d_in, net)     # loop
    petri_utils.add_arc_from_to(d_in, tQDone, net); petri_utils.add_arc_from_to(tQDone, d_done, net)

    # logistics
    petri_utils.add_arc_from_to(d_done, tE1, net); petri_utils.add_arc_from_to(tE1, e1, net)
    petri_utils.add_arc_from_to(e1, tE2, net); petri_utils.add_arc_from_to(tE2, e2, net)
    petri_utils.add_arc_from_to(e2, tE3, net); petri_utils.add_arc_from_to(tE3, e3, net)
    petri_utils.add_arc_from_to(e3, tE4, net); petri_utils.add_arc_from_to(tE4, e4, net)
    petri_utils.add_arc_from_to(e4, tE5, net); petri_utils.add_arc_from_to(tE5, end, net)

    initial_marking = Marking({start: 1})
    final_marking = Marking({end: 1})

    return net, initial_marking, final_marking


if __name__ == "__main__":
    net, im, fm = build_fixed_order_petri_net()
    pnml_exporter.apply(net, im, "fixed_order_process.pnml", final_marking=fm)
    gviz = pn_visualizer.apply(net, im, fm)
    pn_visualizer.save(gviz, "fixed_order_process.png")
    print("Saved fixed_order_process.pnml and fixed_order_process.png")
