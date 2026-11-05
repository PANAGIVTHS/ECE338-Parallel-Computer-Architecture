interface AXI4FullInterface;
    import AXI4FullPkg::*;

    axi_aw_t aw; logic aw_valid, aw_ready;
    axi_w_t  w;  logic w_valid,  w_ready;
    axi_b_t  b;  logic b_valid,  b_ready;
    axi_ar_t ar; logic ar_valid, ar_ready;
    axi_r_t  r;  logic r_valid,  r_ready;

    modport master (output aw, aw_valid, w, w_valid, b_ready, ar, ar_valid, r_ready,
                    input  aw_ready, w_ready, b, b_valid, ar_ready, r, r_valid);
    modport slave  (input  aw, aw_valid, w, w_valid, b_ready, ar, ar_valid, r_ready,
                    output aw_ready, w_ready, b, b_valid, ar_ready, r, r_valid);
endinterface
