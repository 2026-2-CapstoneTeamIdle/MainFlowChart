using System;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.VisualNovel
{
    [Serializable]
    public sealed class DialogueLine
    {
        public string lineId = string.Empty;
        public string speaker = string.Empty;

        [TextArea]
        public string text = string.Empty;
    }

    public sealed class FlagSystemModule : GameModuleBehaviour
    {
        private readonly HashSet<string> flags = new(StringComparer.Ordinal);

        public override string ModuleId => "flag_system";

        public event Action<string, bool> Changed;

        public bool Has(string flagId)
        {
            return flags.Contains(flagId);
        }

        public void Set(string flagId, bool value = true)
        {
            if (string.IsNullOrWhiteSpace(flagId))
            {
                throw new ArgumentException("Flag ID cannot be empty.", nameof(flagId));
            }

            if (value)
            {
                flags.Add(flagId);
            }
            else
            {
                flags.Remove(flagId);
            }

            Changed?.Invoke(flagId, value);
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
        }
    }

    public sealed class DialogueRunnerModule : GameModuleBehaviour
    {
        [SerializeField]
        private List<DialogueLine> lines = new();

        private int currentIndex = -1;

        public override string ModuleId => "dialogue_runner";

        public DialogueLine Current { get; private set; }

        public event Action<DialogueLine> LineChanged;

        public event Action Completed;

        public void StartDialogue(IEnumerable<DialogueLine> nextLines)
        {
            lines = new List<DialogueLine>(nextLines);
            currentIndex = -1;
            Next();
        }

        public bool Next()
        {
            currentIndex++;
            if (currentIndex >= lines.Count)
            {
                Current = null;
                Completed?.Invoke();
                return false;
            }

            Current = lines[currentIndex];
            LineChanged?.Invoke(Current);
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
        }
    }

    [Serializable]
    public sealed class StoryChoice
    {
        public string choiceId = string.Empty;
        public string text = string.Empty;
        public string requiredFlag = string.Empty;
        public string setFlag = string.Empty;
    }

    public sealed class ChoiceBranchSystemModule : GameModuleBehaviour
    {
        private FlagSystemModule flags;

        public override string ModuleId => "choice_branch_system";

        public event Action<StoryChoice> ChoiceSelected;

        public bool IsAvailable(StoryChoice choice)
        {
            return choice != null
                && (
                    string.IsNullOrWhiteSpace(choice.requiredFlag) || flags.Has(choice.requiredFlag)
                );
        }

        public bool Select(StoryChoice choice)
        {
            if (!IsAvailable(choice))
            {
                return false;
            }

            if (!string.IsNullOrWhiteSpace(choice.setFlag))
            {
                flags.Set(choice.setFlag);
            }

            ChoiceSelected?.Invoke(choice);
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            flags = context.GetRequired<FlagSystemModule>();
            context.Register(this);
        }
    }

    public sealed class EndingResolverModule : GameModuleBehaviour
    {
        [Serializable]
        private sealed class EndingRule
        {
            public string endingId = string.Empty;
            public string requiredFlag = string.Empty;
            public int priority;
        }

        [SerializeField]
        private List<EndingRule> endings = new();

        private FlagSystemModule flags;

        public override string ModuleId => "ending_resolver";

        public string Resolve(string fallbackEndingId = "default")
        {
            EndingRule selected = null;
            foreach (var ending in endings)
            {
                if (
                    !string.IsNullOrWhiteSpace(ending.requiredFlag)
                    && !flags.Has(ending.requiredFlag)
                )
                {
                    continue;
                }

                if (selected == null || ending.priority > selected.priority)
                {
                    selected = ending;
                }
            }

            return selected?.endingId ?? fallbackEndingId;
        }

        protected override void OnInitialize(GameContext context)
        {
            flags = context.GetRequired<FlagSystemModule>();
            context.Register(this);
        }
    }
}
