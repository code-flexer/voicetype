# VoiceType

Read README.md and RELEASE_PLAN.md before work. This checkout was recovered from a user-provided 0.3.0 distribution archive; it may not contain the original repository's complete history, tests or build tools.

- Keep one canonical source checkout here, regardless of future public/private visibility.
- RELEASE_PLAN.md is the source of truth for publication readiness.
- Preserve the original archive and provenance outside this repository in Workspace/project-notes/voicetype.
- Prepare this project for open-source release under the MIT license in LICENSE. Source installation is the default; a separate installer ZIP is optional. Do not publish without the user's concrete decision.
- Do not run Install.command, Uninstall.command or install.py merely to inspect the project. They change packages, permissions and startup configuration.
- Do not capture audio, download models or alter Hammerspoon/login items without a task requiring that behavior.
- Keep recordings, transcripts, logs, local settings, credentials, certificates and build outputs out of Git.
- No remote push, public repository creation or release upload without a concrete user decision.
