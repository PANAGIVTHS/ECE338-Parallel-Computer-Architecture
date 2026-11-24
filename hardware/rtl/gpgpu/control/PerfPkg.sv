//! Performance counters: the one definition of every counter
//! (docs/perf-counters-spec.md). The enum order is the order of the counters
//! in their block of the register map (ControlPkg PERF_*), and the enum widths
//! are those blocks' slot counts, so a counter that does not fit is an
//! elaboration error.
package PerfPkg;

    localparam int unsigned PERF_COUNTER_W = ControlPkg::PERF_COUNTER_BYTES * 8;
    typedef logic [PERF_COUNTER_W-1:0] perf_count_t;

    //! Global counters, one each for the whole GPU. The run partition (the
    //! run's cycles), the AW, W, AR and R partitions each sum to
    //! PERF_KERNEL_CYCLES; the rest are events and accumulators.
    (* host *) typedef enum logic [$clog2(ControlPkg::PERF_GLOBAL_SLOTS)-1:0] {
        // Run: every cycle from START to IDLE, and its reset and drain leaves
        // (RUNNING is the sum of a warp's leaves)
        PERF_KERNEL_CYCLES,
        PERF_RUN_RESET,
        PERF_RUN_DRAIN,

        // DDR AW channel partition
        PERF_AW_TRANSFER, // valid & ready: also the number of bursts
        PERF_AW_BLOCKED,  // valid & ~ready
        PERF_AW_IDLE,     // ~valid

        // DDR W channel partition
        PERF_W_TRANSFER,  // valid & ready: one 64-bit beat
        PERF_W_BLOCKED,   // valid & ~ready
        PERF_W_WAIT_AW,   // ~valid, a slot's beats wait for their AW
        PERF_W_IDLE,      // ~valid, no beats waiting

        // DDR write ring
        PERF_WR_INFLIGHT_SUM, // + occupied slots each cycle
        PERF_WR_OWED_SUM,     // + bursts sent on W, B not yet arrived
        PERF_WR_RING_FULL,    // cycles with no free slot

        // DDR AR channel partition
        PERF_AR_TRANSFER, // valid & ready: also the number of read bursts
        PERF_AR_BLOCKED,  // valid & ~ready
        PERF_AR_IDLE,     // ~valid

        // DDR R channel partition
        PERF_R_TRANSFER,  // valid & ready: one 64-bit beat
        PERF_R_BLOCKED,   // valid & ~ready
        PERF_R_WAIT,      // ~valid, a burst's AR accepted and its RLAST not yet arrived
        PERF_R_IDLE,      // ~valid, no burst owed

        // DDR read ring (occupied slots = RD_OWED_SUM + AR_TRANSFER + AR_BLOCKED)
        PERF_RD_OWED_SUM,     // + bursts whose AR is accepted, RLAST not yet arrived

        // Coalescing
        PERF_WR_LANE_STORES,  // + lane stores admitted to the DDR write path
        PERF_RD_LANE_LOADS,   // + lane loads admitted to the DDR read path

        // BRAM data memory
        PERF_BRAM_ACCESSES,   // + lane accesses issued
        PERF_BRAM_BUSY,       // cycles with an access issued
        PERF_BRAM_DEFERRED,   // + picks deferred to the next cycle

        PERF_GLOBAL_COUNT // number of global counters, not a counter
    } perf_global_t;

    //! Warp leaves: in every RUNNING cycle each warp is in exactly one, so a
    //! warp's leaves sum to its RUNNING cycles. Listed in priority order: when
    //! several apply, the first one is the cycle's leaf.
    (* host *) typedef enum logic [$clog2(ControlPkg::PERF_WARP_SLOTS)-1:0] {
        PERF_WARP_ST_RING_FULL, // store stall: a lane not admitted, no free slot
        PERF_WARP_ST_ADMIT,     // store stall: a lane not admitted, a slot free
        PERF_WARP_ST_DATA,      // store stall: all admitted, data not yet sent
        PERF_WARP_LD_RING_FULL, // load stall: a lane not admitted, no free slot
        PERF_WARP_LD_ADMIT,     // load stall: a lane not admitted, a slot free
        PERF_WARP_LD_DATA,      // load stall: all admitted, data not yet received
        PERF_WARP_BRAM,         // memory stall on BRAM lanes only
        PERF_WARP_PIPE_FILL,    // not enabled, or decode not yet enabled
        PERF_WARP_BRANCH,       // taken-branch flush
        PERF_WARP_LOAD_USE,     // load-use bubble
        PERF_WARP_MUL,          // multiplier hazard
        PERF_WARP_ISSUED,       // an instruction moved from ID to EX

        PERF_WARP_LEAF_COUNT // number of warp leaves, not a leaf
    } perf_warp_leaf_t;

    //! Top-level groups the host sums warp leaves into. The hardware counts
    //! only leaves; the groups exist for the host.
    (* host *) typedef enum logic [1:0] {
        PERF_GROUP_ISSUE,
        PERF_GROUP_PIPELINE,
        PERF_GROUP_MEMORY
    } perf_group_t;

    //! The group of every warp leaf, indexed by leaf
    (* host *) localparam perf_group_t PERF_WARP_LEAF_GROUP [PERF_WARP_LEAF_COUNT] = '{
        PERF_WARP_ST_RING_FULL: PERF_GROUP_MEMORY,
        PERF_WARP_ST_ADMIT:     PERF_GROUP_MEMORY,
        PERF_WARP_ST_DATA:      PERF_GROUP_MEMORY,
        PERF_WARP_LD_RING_FULL: PERF_GROUP_MEMORY,
        PERF_WARP_LD_ADMIT:     PERF_GROUP_MEMORY,
        PERF_WARP_LD_DATA:      PERF_GROUP_MEMORY,
        PERF_WARP_BRAM:         PERF_GROUP_MEMORY,
        PERF_WARP_PIPE_FILL:    PERF_GROUP_PIPELINE,
        PERF_WARP_BRANCH:       PERF_GROUP_PIPELINE,
        PERF_WARP_LOAD_USE:     PERF_GROUP_PIPELINE,
        PERF_WARP_MUL:          PERF_GROUP_PIPELINE,
        PERF_WARP_ISSUED:       PERF_GROUP_ISSUE
    };

    //! What a counter adds each cycle (docs/perf-counters-spec.md §3.1)
    (* host *) typedef enum logic [1:0] {
        PERF_KIND_TOTAL,       // 1 every cycle of the run
        PERF_KIND_LEAF,        // 1 in each cycle its condition holds
        PERF_KIND_EVENT,       // the number of events in the cycle
        PERF_KIND_ACCUMULATOR  // a quantity's current value
    } perf_kind_t;

    //! The groups the host reports the global counters in
    (* host *) typedef enum logic [3:0] {
        PERF_GLOBAL_GROUP_RUN,
        PERF_GLOBAL_GROUP_AW,
        PERF_GLOBAL_GROUP_W,
        PERF_GLOBAL_GROUP_WRITE_RING,
        PERF_GLOBAL_GROUP_AR,
        PERF_GLOBAL_GROUP_R,
        PERF_GLOBAL_GROUP_READ_RING,
        PERF_GLOBAL_GROUP_COALESCING,
        PERF_GLOBAL_GROUP_BRAM
    } perf_global_group_t;

    //! The group of every global counter, indexed by counter
    (* host *) localparam perf_global_group_t PERF_GLOBAL_GROUP_OF [PERF_GLOBAL_COUNT] = '{
        PERF_KERNEL_CYCLES:   PERF_GLOBAL_GROUP_RUN,
        PERF_RUN_RESET:       PERF_GLOBAL_GROUP_RUN,
        PERF_RUN_DRAIN:       PERF_GLOBAL_GROUP_RUN,
        PERF_AW_TRANSFER:     PERF_GLOBAL_GROUP_AW,
        PERF_AW_BLOCKED:      PERF_GLOBAL_GROUP_AW,
        PERF_AW_IDLE:         PERF_GLOBAL_GROUP_AW,
        PERF_W_TRANSFER:      PERF_GLOBAL_GROUP_W,
        PERF_W_BLOCKED:       PERF_GLOBAL_GROUP_W,
        PERF_W_WAIT_AW:       PERF_GLOBAL_GROUP_W,
        PERF_W_IDLE:          PERF_GLOBAL_GROUP_W,
        PERF_WR_INFLIGHT_SUM: PERF_GLOBAL_GROUP_WRITE_RING,
        PERF_WR_OWED_SUM:     PERF_GLOBAL_GROUP_WRITE_RING,
        PERF_WR_RING_FULL:    PERF_GLOBAL_GROUP_WRITE_RING,
        PERF_AR_TRANSFER:     PERF_GLOBAL_GROUP_AR,
        PERF_AR_BLOCKED:      PERF_GLOBAL_GROUP_AR,
        PERF_AR_IDLE:         PERF_GLOBAL_GROUP_AR,
        PERF_R_TRANSFER:      PERF_GLOBAL_GROUP_R,
        PERF_R_BLOCKED:       PERF_GLOBAL_GROUP_R,
        PERF_R_WAIT:          PERF_GLOBAL_GROUP_R,
        PERF_R_IDLE:          PERF_GLOBAL_GROUP_R,
        PERF_RD_OWED_SUM:     PERF_GLOBAL_GROUP_READ_RING,
        PERF_WR_LANE_STORES:  PERF_GLOBAL_GROUP_COALESCING,
        PERF_RD_LANE_LOADS:   PERF_GLOBAL_GROUP_COALESCING,
        PERF_BRAM_ACCESSES:   PERF_GLOBAL_GROUP_BRAM,
        PERF_BRAM_BUSY:       PERF_GLOBAL_GROUP_BRAM,
        PERF_BRAM_DEFERRED:   PERF_GLOBAL_GROUP_BRAM
    };

    //! The kind of every global counter, indexed by counter (warp leaves are
    //! all PERF_KIND_LEAF)
    (* host *) localparam perf_kind_t PERF_GLOBAL_KIND [PERF_GLOBAL_COUNT] = '{
        PERF_KERNEL_CYCLES:   PERF_KIND_TOTAL,
        PERF_RUN_RESET:       PERF_KIND_LEAF,
        PERF_RUN_DRAIN:       PERF_KIND_LEAF,
        PERF_AW_TRANSFER:     PERF_KIND_LEAF,
        PERF_AW_BLOCKED:      PERF_KIND_LEAF,
        PERF_AW_IDLE:         PERF_KIND_LEAF,
        PERF_W_TRANSFER:      PERF_KIND_LEAF,
        PERF_W_BLOCKED:       PERF_KIND_LEAF,
        PERF_W_WAIT_AW:       PERF_KIND_LEAF,
        PERF_W_IDLE:          PERF_KIND_LEAF,
        PERF_WR_INFLIGHT_SUM: PERF_KIND_ACCUMULATOR,
        PERF_WR_OWED_SUM:     PERF_KIND_ACCUMULATOR,
        PERF_WR_RING_FULL:    PERF_KIND_LEAF,
        PERF_AR_TRANSFER:     PERF_KIND_LEAF,
        PERF_AR_BLOCKED:      PERF_KIND_LEAF,
        PERF_AR_IDLE:         PERF_KIND_LEAF,
        PERF_R_TRANSFER:      PERF_KIND_LEAF,
        PERF_R_BLOCKED:       PERF_KIND_LEAF,
        PERF_R_WAIT:          PERF_KIND_LEAF,
        PERF_R_IDLE:          PERF_KIND_LEAF,
        PERF_RD_OWED_SUM:     PERF_KIND_ACCUMULATOR,
        PERF_WR_LANE_STORES:  PERF_KIND_EVENT,
        PERF_RD_LANE_LOADS:   PERF_KIND_EVENT,
        PERF_BRAM_ACCESSES:   PERF_KIND_EVENT,
        PERF_BRAM_BUSY:       PERF_KIND_LEAF,
        PERF_BRAM_DEFERRED:   PERF_KIND_EVENT
    };

endpackage
