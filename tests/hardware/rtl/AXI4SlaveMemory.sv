`timescale 1ns/1ps

// AXI4 slave memory model for the GPGPU's DDR master (spec §6.6 item 2).
//
// Sparse 64-bit beat memory with:
//   * random AWREADY/WREADY/ARREADY gaps (READY_PCT: chance per cycle that a
//     ready is high);
//   * a random LATENCY_MIN..LATENCY_MAX cycle delay from a burst's last
//     address/data handshake to its first B/R beat, and random BVALID/RVALID
//     gaps (VALID_PCT: chance per cycle that a due beat is presented);
//   * per-beat error injection (set_error): a read beat answers with the
//     injected response, a write burst answers with the worst response of
//     its beats and leaves memory unchanged;
//   * a backdoor (write_word/read_word/clear) to preload texture data and
//     read back framebuffer data, and handshake counters to check traffic.
//
// Responses return in issue order (the master uses one AXI ID). Write data
// may arrive before its address. Every protocol violation the model can see
// is fatal: a burst the HP port would reject (not INCR, not full-beat size,
// longer than AXI_MAX_BEATS_PER_BURST, unaligned, crossing 4 KiB), a WLAST
// on the wrong beat, and a payload or VALID changed while VALID waited for
// READY.

// Connects a DUT's flat AXI4 master ports <prefix>_* (as GPGPU and the IP
// wrapper name them) to an AXI4FullInterface the model is attached to. This
// file is compiled before the benches, so they can use it.
`define AXI4_SLAVE_CONNECT(prefix, bus) \
    .prefix``_awid(bus.aw.id), .prefix``_awaddr(bus.aw.addr), .prefix``_awlen(bus.aw.len), \
    .prefix``_awsize(bus.aw.size), .prefix``_awburst(bus.aw.burst), .prefix``_awlock(bus.aw.lock), \
    .prefix``_awcache(bus.aw.cache), .prefix``_awprot(bus.aw.prot), .prefix``_awqos(bus.aw.qos), \
    .prefix``_awvalid(bus.aw_valid), .prefix``_awready(bus.aw_ready), \
    .prefix``_wdata(bus.w.data), .prefix``_wstrb(bus.w.strb), .prefix``_wlast(bus.w.last), \
    .prefix``_wvalid(bus.w_valid), .prefix``_wready(bus.w_ready), \
    .prefix``_bid(bus.b.id), .prefix``_bresp(bus.b.resp), \
    .prefix``_bvalid(bus.b_valid), .prefix``_bready(bus.b_ready), \
    .prefix``_arid(bus.ar.id), .prefix``_araddr(bus.ar.addr), .prefix``_arlen(bus.ar.len), \
    .prefix``_arsize(bus.ar.size), .prefix``_arburst(bus.ar.burst), .prefix``_arlock(bus.ar.lock), \
    .prefix``_arcache(bus.ar.cache), .prefix``_arprot(bus.ar.prot), .prefix``_arqos(bus.ar.qos), \
    .prefix``_arvalid(bus.ar_valid), .prefix``_arready(bus.ar_ready), \
    .prefix``_rid(bus.r.id), .prefix``_rdata(bus.r.data), .prefix``_rresp(bus.r.resp), \
    .prefix``_rlast(bus.r.last), .prefix``_rvalid(bus.r_valid), .prefix``_rready(bus.r_ready)

module AXI4SlaveMemory
    import AXI4FullPkg::*;
#(
    parameter int unsigned LATENCY_MIN,
    parameter int unsigned LATENCY_MAX,
    parameter int unsigned READY_PCT,
    parameter int unsigned VALID_PCT,
    parameter int unsigned SEED
) (
    input logic clk,
    input logic rst_n,

    AXI4FullInterface.slave axi
);

    localparam int unsigned BEAT_BYTES = AXI_DATA_W / 8;
    localparam int unsigned BEAT_SHIFT = $clog2(BEAT_BYTES);
    localparam int unsigned WORDS_PER_BEAT = AXI_DATA_W / 32;
    localparam int unsigned BOUNDARY_BYTES = 4096;

    if (LATENCY_MIN > LATENCY_MAX) begin : g_latency_check
        $fatal(1, "AXI slave LATENCY_MIN (%0d) exceeds LATENCY_MAX (%0d)", LATENCY_MIN, LATENCY_MAX);
    end
    if (READY_PCT < 1 || READY_PCT > 100 || VALID_PCT < 1 || VALID_PCT > 100) begin : g_pct_check
        $fatal(1, "AXI slave READY_PCT (%0d) and VALID_PCT (%0d) must be 1..100", READY_PCT, VALID_PCT);
    end
    if (SEED == 0) begin : g_seed_check
        $fatal(1, "AXI slave SEED must be non-zero");
    end

    typedef logic [AXI_ADDR_W-BEAT_SHIFT-1:0] beat_index_t;

    typedef struct {
        axi_ar_t ar;
        longint unsigned due;
    } read_burst_t;

    typedef struct {
        axi_b_t b;
        longint unsigned due;
    } write_resp_t;

    // Backdoor state, shared with the bench through the functions below.
    axi_data_t mem [beat_index_t];
    axi_resp_t errors [beat_index_t];

    // Handshake counters since the last clear(); the bench reads them.
    int unsigned aw_count, w_count, b_count, ar_count, r_count;

    axi_aw_t aw_q [$];
    axi_w_t w_q [$];
    write_resp_t b_q [$];
    read_burst_t ar_q [$];
    int unsigned r_beat;

    longint unsigned cycle;
    int unsigned rand_state;

    // A payload waiting for READY must hold; these remember the last one.
    logic aw_waiting, w_waiting, ar_waiting;
    axi_aw_t aw_held;
    axi_w_t w_held;
    axi_ar_t ar_held;

    // ============================================================
    // Backdoor
    // ============================================================

    function automatic beat_index_t beat_of(input axi_addr_t addr);
        return beat_index_t'(addr >> BEAT_SHIFT);
    endfunction

    function automatic int unsigned lane_of(input axi_addr_t addr);
        return (addr >> 2) % WORDS_PER_BEAT;
    endfunction

    // Never-written memory reads as zero.
    function automatic axi_data_t beat_at(input beat_index_t beat);
        return mem.exists(beat) != 0 ? mem[beat] : '0;
    endfunction

    // Byte-addressed 32-bit word access; addr must be word-aligned.
    function automatic void write_word(input axi_addr_t addr, input logic [31:0] data);
        axi_data_t beat;
        if (addr[1:0] != 2'b00)
            $fatal(1, "[ERROR] AXI slave backdoor write to unaligned address %h", addr);
        beat = beat_at(beat_of(addr));
        beat[lane_of(addr) * 32 +: 32] = data;
        mem[beat_of(addr)] = beat;
    endfunction

    function automatic logic [31:0] read_word(input axi_addr_t addr);
        axi_data_t beat;
        if (addr[1:0] != 2'b00)
            $fatal(1, "[ERROR] AXI slave backdoor read from unaligned address %h", addr);
        beat = beat_at(beat_of(addr));
        return beat[lane_of(addr) * 32 +: 32];
    endfunction

    // Any burst touching the beat that holds addr answers with resp.
    function automatic void set_error(input axi_addr_t addr, input axi_resp_t resp);
        if (resp == AXI_RESP_OKAY)
            errors.delete(beat_of(addr));
        else
            errors[beat_of(addr)] = resp;
    endfunction

    // Empties memory and errors and zeroes the counters. Call it only while
    // no transaction is in flight.
    function automatic void clear();
        mem.delete();
        errors.delete();
        aw_count = 0; w_count = 0; b_count = 0; ar_count = 0; r_count = 0;
    endfunction

    // No burst accepted and unanswered, and no data waiting for its address.
    function automatic bit idle();
        return aw_q.size() == 0 && w_q.size() == 0 && b_q.size() == 0 && ar_q.size() == 0;
    endfunction

    // ============================================================
    // Randomness: xorshift32, so a SEED reproduces a run on any simulator.
    // ============================================================

    function automatic int unsigned next_rand();
        rand_state ^= rand_state << 13;
        rand_state ^= rand_state >> 17;
        rand_state ^= rand_state << 5;
        return rand_state;
    endfunction

    function automatic bit chance(input int unsigned pct);
        return next_rand() % 100 < pct;
    endfunction

    function automatic longint unsigned due_after_latency();
        int unsigned latency;
        latency = LATENCY_MIN + next_rand() % (LATENCY_MAX - LATENCY_MIN + 1);
        return cycle + 64'(latency);
    endfunction

    // ============================================================
    // Burst checks and helpers
    // ============================================================

    function automatic void check_burst(input string channel, input axi_ax_t ax);
        int unsigned beats;
        beats = int'(ax.len) + 1;
        if (ax.burst != AXI_BURST_INCR)
            $fatal(1, "[ERROR] AXI slave %0s addr=%h: burst %0d is not INCR", channel, ax.addr, ax.burst);
        if (ax.size != 3'(BEAT_SHIFT))
            $fatal(1, "[ERROR] AXI slave %0s addr=%h: size %0d is not a full %0d-byte beat",
                   channel, ax.addr, ax.size, BEAT_BYTES);
        if (beats > AXI_MAX_BEATS_PER_BURST)
            $fatal(1, "[ERROR] AXI slave %0s addr=%h: %0d beats exceed %0d",
                   channel, ax.addr, beats, AXI_MAX_BEATS_PER_BURST);
        if (ax.addr % BEAT_BYTES != 0)
            $fatal(1, "[ERROR] AXI slave %0s addr=%h is not beat-aligned", channel, ax.addr);
        if (ax.addr / BOUNDARY_BYTES != (ax.addr + beats * BEAT_BYTES - 1) / BOUNDARY_BYTES)
            $fatal(1, "[ERROR] AXI slave %0s addr=%h: %0d beats cross a 4 KiB boundary",
                   channel, ax.addr, beats);
    endfunction

    function automatic axi_resp_t error_at(input beat_index_t beat);
        return errors.exists(beat) != 0 ? errors[beat] : AXI_RESP_OKAY;
    endfunction

    // DECERR outranks SLVERR outranks OKAY.
    function automatic axi_resp_t worse(input axi_resp_t a, input axi_resp_t b);
        if (a == AXI_RESP_DECERR || b == AXI_RESP_DECERR) return AXI_RESP_DECERR;
        if (a == AXI_RESP_SLVERR || b == AXI_RESP_SLVERR) return AXI_RESP_SLVERR;
        return AXI_RESP_OKAY;
    endfunction

    // Retire the oldest write once all its beats are here.
    function automatic void complete_write();
        axi_aw_t aw;
        axi_w_t w;
        axi_resp_t resp;
        beat_index_t beat;
        axi_data_t data;
        aw = aw_q[0];
        if (w_q.size() < int'(aw.len) + 1)
            return;
        void'(aw_q.pop_front());
        resp = AXI_RESP_OKAY;
        for (int unsigned i = 0; i <= aw.len; i++)
            resp = worse(resp, error_at(beat_of(aw.addr) + beat_index_t'(i)));
        for (int unsigned i = 0; i <= aw.len; i++) begin
            w = w_q.pop_front();
            if (w.last != (i == int'(aw.len)))
                $fatal(1, "[ERROR] AXI slave W: WLAST=%b on beat %0d of %0d for addr=%h",
                       w.last, i, int'(aw.len) + 1, aw.addr);
            if (resp == AXI_RESP_OKAY) begin
                beat = beat_of(aw.addr) + beat_index_t'(i);
                data = beat_at(beat);
                for (int unsigned byte_lane = 0; byte_lane < BEAT_BYTES; byte_lane++)
                    if (w.strb[byte_lane])
                        data[byte_lane * 8 +: 8] = w.data[byte_lane * 8 +: 8];
                mem[beat] = data;
            end
        end
        b_q.push_back('{b: '{id: aw.id, resp: resp}, due: due_after_latency()});
    endfunction

    // ============================================================
    // Channels
    // ============================================================

    always @(posedge clk) begin
        if (!rst_n) begin
            aw_q.delete(); w_q.delete(); b_q.delete(); ar_q.delete();
            r_beat <= 0;
            cycle <= 0;
            rand_state = SEED;
            aw_waiting <= 1'b0; w_waiting <= 1'b0; ar_waiting <= 1'b0;
            axi.aw_ready <= 1'b0;
            axi.w_ready <= 1'b0;
            axi.ar_ready <= 1'b0;
            axi.b_valid <= 1'b0;
            axi.b <= '0;
            axi.r_valid <= 1'b0;
            axi.r <= '0;
        end else begin
            cycle <= cycle + 1;

            // A VALID waiting for READY must stay high with the same payload.
            if (aw_waiting && !(axi.aw_valid && axi.aw == aw_held))
                $fatal(1, "[ERROR] AXI slave AW: AWVALID or payload changed before AWREADY");
            if (w_waiting && !(axi.w_valid && axi.w == w_held))
                $fatal(1, "[ERROR] AXI slave W: WVALID or payload changed before WREADY");
            if (ar_waiting && !(axi.ar_valid && axi.ar == ar_held))
                $fatal(1, "[ERROR] AXI slave AR: ARVALID or payload changed before ARREADY");
            aw_waiting <= axi.aw_valid && !axi.aw_ready;
            w_waiting <= axi.w_valid && !axi.w_ready;
            ar_waiting <= axi.ar_valid && !axi.ar_ready;
            aw_held <= axi.aw;
            w_held <= axi.w;
            ar_held <= axi.ar;

            // Address and write data
            if (axi.aw_valid && axi.aw_ready) begin
                check_burst("AW", axi.aw);
                aw_q.push_back(axi.aw);
                aw_count++;
            end
            if (axi.w_valid && axi.w_ready) begin
                w_q.push_back(axi.w);
                w_count++;
            end
            if (axi.ar_valid && axi.ar_ready) begin
                check_burst("AR", axi.ar);
                ar_q.push_back('{ar: axi.ar, due: due_after_latency()});
                ar_count++;
            end
            while (aw_q.size() != 0 && w_q.size() > int'(aw_q[0].len))
                complete_write();

            axi.aw_ready <= chance(READY_PCT);
            axi.w_ready <= chance(READY_PCT);
            axi.ar_ready <= chance(READY_PCT);

            // B: one response per burst, held until BREADY
            if (axi.b_valid && axi.b_ready) begin
                void'(b_q.pop_front());
                b_count++;
            end
            if (!axi.b_valid || axi.b_ready) begin
                if (b_q.size() != 0 && b_q[0].due <= cycle && chance(VALID_PCT)) begin
                    axi.b_valid <= 1'b1;
                    axi.b <= b_q[0].b;
                end else begin
                    axi.b_valid <= 1'b0;
                end
            end

            // R: the oldest burst's beats in order, each held until RREADY
            if (axi.r_valid && axi.r_ready) begin
                r_count++;
                if (axi.r.last) begin
                    void'(ar_q.pop_front());
                    r_beat <= 0;
                end else begin
                    r_beat <= r_beat + 1;
                end
            end
            if (!axi.r_valid || axi.r_ready) begin
                // The beat after the one just taken; a finished burst was popped above.
                automatic int unsigned beat = !(axi.r_valid && axi.r_ready) ? r_beat
                                            : axi.r.last ? 0 : r_beat + 1;
                if (ar_q.size() != 0 && ar_q[0].due <= cycle && chance(VALID_PCT)) begin
                    automatic beat_index_t index = beat_of(ar_q[0].ar.addr) + beat_index_t'(beat);
                    axi.r_valid <= 1'b1;
                    axi.r <= '{
                        id: ar_q[0].ar.id,
                        data: beat_at(index),
                        resp: error_at(index),
                        last: beat == int'(ar_q[0].ar.len)
                    };
                end else begin
                    axi.r_valid <= 1'b0;
                end
            end
        end
    end

endmodule
