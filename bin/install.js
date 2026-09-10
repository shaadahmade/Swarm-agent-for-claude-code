#!/usr/bin/env node
// Installs the agent-swarm skill into a Claude Code skills directory.
//
//   npx agent-swarm-skill            install into ./.claude/skills (this project)
//   npx agent-swarm-skill --global   install into ~/.claude/skills (all projects)
//   npx agent-swarm-skill --force    overwrite an existing installation

const fs = require("fs");
const os = require("os");
const path = require("path");

const args = new Set(process.argv.slice(2));
if (args.has("--help") || args.has("-h")) {
  console.log(`agent-swarm-skill

  npx agent-swarm-skill            install into ./.claude/skills (this project)
  npx agent-swarm-skill --global   install into ~/.claude/skills (all projects)
  npx agent-swarm-skill --force    overwrite an existing installation`);
  process.exit(0);
}

const NAME = "agent-swarm";
const source = path.join(__dirname, "..", "skills", NAME);
const base = args.has("--global") || args.has("-g") ? os.homedir() : process.cwd();
const target = path.join(base, ".claude", "skills", NAME);

if (!fs.existsSync(path.join(source, "SKILL.md"))) {
  console.error(`error: cannot find the skill payload at ${source}`);
  process.exit(1);
}

if (fs.existsSync(target)) {
  if (!args.has("--force") && !args.has("-f")) {
    console.error(`error: ${target} already exists.`);
    console.error("Re-run with --force to overwrite it.");
    process.exit(1);
  }
  fs.rmSync(target, { recursive: true, force: true });
}

fs.mkdirSync(path.dirname(target), { recursive: true });
fs.cpSync(source, target, { recursive: true });

// Shell scripts must stay executable for anyone who runs them directly.
const scripts = path.join(target, "scripts");
if (fs.existsSync(scripts)) {
  for (const f of fs.readdirSync(scripts)) {
    if (f.endsWith(".sh")) fs.chmodSync(path.join(scripts, f), 0o755);
  }
}

console.log(`Installed ${NAME} to ${target}`);
console.log("Restart Claude Code, then run: /agent-swarm <your goal>");
console.log("");
console.log("Requires the claude CLI, bash, and python3 on PATH.");
