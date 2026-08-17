#!/bin/bash
# dai bash completion
# Usage: source <(dai completion bash)

_dai_completion() {
  local cur prev words cword
  _init_completion || return

  # Commands
  local commands="tools skills config doctor validate help version"

  # Tools subcommands
  local tools_commands="list search call"

  # Skills subcommands
  local skills_commands="list search categories"

  # Config subcommands
  local config_commands="get set list init delete"

  # DAI options
  local options="--json --no-color --quiet --debug --help --version"

  # Completion logic
  case $prev in
    dai)
      COMPREPLY=($(compgen -W "$commands $options" -- "$cur"))
      ;;
    tools)
      COMPREPLY=($(compgen -W "$tools_commands --json --category --search" -- "$cur"))
      ;;
    tools:list)
      COMPREPLY=($(compgen -W "--json --category --search" -- "$cur"))
      ;;
    tools:search)
      COMPREPLY=($(compgen -W "--json" -- "$cur"))
      ;;
    tools:call)
      # Complete with tool names
      COMPREPLY=($(compgen -W "skills.list skills.search validate.quality config.get config.set config.list doctor.check" -- "$cur"))
      ;;
    skills)
      COMPREPLY=($(compgen -W "$skills_commands --json --category --search" -- "$cur"))
      ;;
    skills:list)
      COMPREPLY=($(compgen -W "--json --category --search" -- "$cur"))
      ;;
    skills:search)
      COMPREPLY=($(compgen -W "--json" -- "$cur"))
      ;;
    skills:categories)
      COMPREPLY=($(compgen -W "--json" -- "$cur"))
      ;;
    config)
      COMPREPLY=($(compgen -W "$config_commands --json" -- "$cur"))
      ;;
    config:get)
      COMPREPLY=($(compgen -W "--json" -- "$cur"))
      ;;
    config:set)
      COMPREPLY=($(compgen -W "--json" -- "$cur"))
      ;;
    config:list)
      COMPREPLY=($(compgen -W "--json" -- "$cur"))
      ;;
    config:delete)
      COMPREPLY=($(compgen -W "--json" -- "$cur"))
      ;;
    doctor)
      COMPREPLY=($(compgen -W "--verbose --json" -- "$cur"))
      ;;
    validate)
      COMPREPLY=($(compgen -W "--level --strict --json --report" -- "$cur"))
      ;;
    --level)
      COMPREPLY=($(compgen -W "1 2 3" -- "$cur"))
      ;;
    --report|--category|--search|--args)
      # These need a value, complete with file path for --report
      if [[ "$prev" == "--report" ]]; then
        _filedir
      fi
      ;;
    --json|--no-color|--quiet|--debug|--strict|--verbose|--help|--version)
      # No further completion needed
      ;;
    -j|-q|-v|-h)
      COMPREPLY=($(compgen -W "" -- "$cur"))
      ;;
    *)
      # Check if previous word is a flag that needs a value
      if [[ "$cur" == -* ]]; then
        COMPREPLY=($(compgen -W "$options" -- "$cur"))
      fi
      ;;
  esac
}

complete -F _dai_completion dai
