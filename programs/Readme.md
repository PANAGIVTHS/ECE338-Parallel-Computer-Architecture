### Structure
Inside the folders there are C programs with two functions, one for x86 and one for RISC-V. The `Makefile` compiles the given program for x86 and dumps the assembly file at `<program>.asm`, it later parses that file and generates the `<program.mem>` file that has the RISC-V instructions ready to run on the GPU.

### Usage
To create a new program, create a new folder with the program name and then create a `<program>.c` file containing both the RISC-V and the x86 main functions using the `__riscv` constant. For example:

In `<program>/<program>.c`:
```c
#ifdef __riscv
int _start() {
    int threadIdx_x;
    __asm__ volatile("mv %0, x31" : "=r"(threadIdx_x));

    // Your RISC-V code...
}
#else
#include <stdio.h>
int main() {
    // Your x86 code...
}
#endif

```

The compiler will generate the RISC-V assembly instructions as a hex automatically:
```cmd
make PROG=<program>
```
