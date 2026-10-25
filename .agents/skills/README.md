# Project-local Unity skills

This directory vendors a focused subset of the official
[`Unity-Technologies/skills`](https://github.com/Unity-Technologies/skills)
repository for agents working on MainFlowChart.

- Source revision: `9d282100540601cfddc4bbd69f36a239d7a6f55c`
- Imported: 2026-10-16
- License: [Unity Companion License](LICENSE.md)

## Included

### Unity automation and validation

- `unity-cli`
- `unity-pipeline`
- `unity-package-management`
- `project-auditor-fixes`

### Unity 2D content and runtime

- `create-2d-physics`
- `create-tile-palette-or-rule-tiles`
- `2d-pixel-perfect`
- `sprite-editor`
- `manage-sprite-atlas`

### Presentation and localization

- `ui-ugui`
- `audio-setup-mixers`
- `optimize-audio`
- `optimize-text-mesh-pro`
- `localization`

The selection intentionally excludes 3D, multiplayer, advertising, in-app
purchase, LiveOps, Vivox, and industrial asset transformation workflows because
MainFlowChart currently targets offline Unity 2D prototype generation.

These skills guide development agents; they are not runtime dependencies and
are not copied into generated Unity projects. A skill may require the Unity CLI,
a running Unity Editor, or an additional Unity package before it can perform its
workflow. Review the selected skill's `SKILL.md` before using it.

