//! Performance counters: the one definition of every counter
//! (docs/perf-counters-spec.md). The enum order is the order of the counters
//! in their block of the register map (ControlPkg PERF_*), and the enum widths
//! are those blocks' slot counts, so a counter that does not fit is an
//! elaboration error.
package PerfPkg;

    localparam int unsigned PERF_COUNTER_W = ControlPkg::PERF_COUNTER_BYTES * 8;
    typedef logic [PERF_COUNTER_W-1:0] perf_count_t;

    //! Global counters, one each for the whole GPU. The run partition (the
    //! run's cycles), the AW and the W partitions each sum to
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

        // Coalescing
        PERF_WR_LANE_STORES,  // + lane stores admitted to the DDR write path

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
        PERF_WARP_BRAM:         PERF_GROUP_MEMORY,
        PERF_WARP_PIPE_FILL:    PERF_GROUP_PIPELINE,
        PERF_WARP_BRANCH:       PERF_GROUP_PIPELINE,
        PERF_WARP_LOAD_USE:     PERF_GROUP_PIPELINE,
        PERF_WARP_MUL:          PERF_GROUP_PIPELINE,
        PERF_WARP_ISSUED:       PERF_GROUP_ISSUE
    };

endpackage
