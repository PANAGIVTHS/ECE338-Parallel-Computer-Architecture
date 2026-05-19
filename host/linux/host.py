import serial
import time
import sys

# ==========================================
# CONFIGURATION
# ==========================================
# CHANGE THIS to match your CH341T adapter's port!
# Windows: 'COM3', 'COM4', etc.
# Linux/Mac: '/dev/ttyUSB0', '/dev/cu.usbserial-xxx'
COM_PORT = '/dev/ttyUSB0'
BAUD_RATE = 9600

# Architecture limits
IMEM_WORDS = 1024
DMEM_WORDS = 1024
REG_WORDS  = 32

IMEM_BYTES = IMEM_WORDS * 4
EXPECTED_RX_BYTES = (DMEM_WORDS + REG_WORDS) * 4

def main():
    print("=================================================")
    print(" GPGPU Hardware Driver")
    print("=================================================")

    # 1. Open the Serial Port
    try:
        # We use a 5-second timeout. If the FPGA doesn't reply within 5s, we abort.
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=10.0)
        print(f"[System] Successfully opened {COM_PORT} at {BAUD_RATE} baud.")
    except serial.SerialException as e:
        print(f"FATAL ERROR: Could not open {COM_PORT}. Is it plugged in?")
        print(e)
        sys.exit(1)

    # 2. Read and Parse program.mem
    try:
        with open("program.mem", "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print("FATAL ERROR: program.mem not found in the current directory.")
        sys.exit(1)

    # 3. Convert Hex Strings to Raw Bytes
    tx_bytearray = bytearray()
    instruction_count = 0

    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            continue # Skip empty lines
        
        # Convert "00000093" -> b'\x00\x00\x00\x93' (Big-Endian format)
        tx_bytearray.extend(bytes.fromhex(clean_line))
        instruction_count += 1

    # 4. The Padding Trap!
    # Your Verilog HostController waits for EXACTLY 4096 bytes before dropping into RUN mode.
    # We must pad the rest of the array with 0x00000000 (NOPs).
    bytes_short = IMEM_BYTES - len(tx_bytearray)
    if bytes_short > 0:
        tx_bytearray.extend(b'\x00' * bytes_short)

    # 5. Transmit to FPGA
    print(f"\n[TX] Sending {instruction_count} instructions ({len(tx_bytearray)} bytes padded)...")
    ser.write(tx_bytearray)
    ser.flush() # Wait until all bytes are physically pushed out of the USB port
    print("[TX] Transmission complete! Core should now be executing.")

    # 6. Wait for Execution and Receive Dumps
    print(f"\n[RX] Waiting for FPGA to dump {EXPECTED_RX_BYTES} bytes...")
    
    rx_bytearray = bytearray()
    
    # Read exactly the number of bytes we expect
    rx_bytearray = ser.read(EXPECTED_RX_BYTES)

    if len(rx_bytearray) == 0:
        print("\nFATAL ERROR: Timeout! The FPGA did not send any data back.")
        print("Check your wiring (Adapter RX -> FPGA TX) and ensure the core_complete signal fired.")
        ser.close()
        sys.exit(1)
        
    elif len(rx_bytearray) < EXPECTED_RX_BYTES:
        print(f"\nWARNING: Only received {len(rx_bytearray)} / {EXPECTED_RX_BYTES} bytes.")
        print("The dump was cut short!")

    else:
        print("[RX] Memory dump received successfully!")

    ser.close()

    # 7. Parse the Raw Bytes back into Hex text files
    print("\n[System] Parsing received bytes...")
    
    dmem_bytes = rx_bytearray[0 : DMEM_WORDS*4]
    reg_bytes  = rx_bytearray[DMEM_WORDS*4 : EXPECTED_RX_BYTES]

    # Save Data Memory
    with open("fpga_dram_dump.mem", "w") as f:
        for i in range(0, len(dmem_bytes), 4):
            word = dmem_bytes[i:i+4]
            f.write(word.hex() + "\n")

    # Save Register File
    with open("fpga_reg_dump.mem", "w") as f:
        for i in range(0, len(reg_bytes), 4):
            word = reg_bytes[i:i+4]
            f.write(word.hex() + "\n")

    print("[System] Done! Results saved to 'fpga_dram_dump.mem' and 'fpga_reg_dump.mem'.")
    print("=================================================")

if __name__ == "__main__":
    main()