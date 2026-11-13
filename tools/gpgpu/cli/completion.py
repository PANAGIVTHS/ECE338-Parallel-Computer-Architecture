"""Tab completion scripts. They ask the CLI itself, through Typer's completion protocol.

They run the command as typed, so `./gpgpu` completes without being on PATH.
"""

SCRIPTS = {
    "zsh": r"""
(( $+functions[compdef] )) || { autoload -Uz compinit && compinit }
_gpgpu() {
    eval $(env _TYPER_COMPLETE_ARGS="${words[1,$CURRENT]}" _GPGPU_COMPLETE=complete_zsh $words[1])
}
compdef _gpgpu gpgpu
""",
    # Bash splits words at ":". Complete from the line as typed, then drop what it will not replace.
    "bash": r"""
_gpgpu() {
    local line="${COMP_LINE:0:COMP_POINT}" IFS=$'\n' words=()
    IFS=' ' read -ra words <<< "$line"
    [[ "$line" == *" " ]] && words+=("")
    local current="${words[-1]}"
    COMPREPLY=($(env COMP_WORDS="$line" COMP_CWORD=$((${#words[@]} - 1)) _GPGPU_COMPLETE=complete_bash "$1"))
    COMPREPLY=("${COMPREPLY[@]#"${current%"${current##*:}"}"}")
}
complete -o default -F _gpgpu gpgpu
""",
}
