# Shared skill deployment for AI agents (Claude Code, Gemini CLI, etc.)
#
# Returns home.file entries that deploy skills to ~/.{agent}/skills/.
# Each agent module calls this with its target prefix.
#
# Usage:
#   mkSkillFiles { inherit lib siderolabs-docs; prefix = ".claude"; }
{
  lib,
  siderolabs-docs,
  prefix,
}:
let
  skillsDir = ./.;

  # Local skills: each subdirectory containing SKILL.md
  localSkills = lib.mapAttrs' (
    skillName: _:
    lib.nameValuePair "${prefix}/skills/${skillName}" {
      source = skillsDir + "/${skillName}";
      recursive = true;
    }
  ) (lib.filterAttrs (name: type: type == "directory") (builtins.readDir skillsDir));

  # External skills fetched from upstream repos
  externalSkills = {
    "${prefix}/skills/siderolabs/SKILL.md".source = "${siderolabs-docs}/public/skill.md";
  };
in
localSkills // externalSkills
