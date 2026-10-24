using System;
using System.Collections.Generic;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.SurvivorLike
{
    public sealed class UpgradeSelectionSystemModule : GameModuleBehaviour
    {
        public sealed class UpgradeChoice
        {
            public UpgradeDefinition Upgrade { get; set; }
            public UpgradeRarity Rarity { get; set; }
        }

        [SerializeField]
        private List<UpgradeDefinition> upgradePool = new();

        [SerializeField]
        private int choiceCount = 3;

        private readonly List<UpgradeChoice> currentChoices = new();
        private ExperienceSystemModule experience;
        private RaritySystemModule rarity;

        public override string ModuleId => "upgrade_selection_system";

        public IReadOnlyList<UpgradeChoice> CurrentChoices => currentChoices;

        public event Action<IReadOnlyList<UpgradeChoice>> ChoicesPresented;

        public event Action<UpgradeChoice> Selected;

        public bool Select(int index)
        {
            if (index < 0 || index >= currentChoices.Count)
            {
                return false;
            }

            var choice = currentChoices[index];
            currentChoices.Clear();
            Selected?.Invoke(choice);
            return true;
        }

        protected override void OnInitialize(GameContext context)
        {
            experience = context.GetRequired<ExperienceSystemModule>();
            rarity = context.GetRequired<RaritySystemModule>();
            experience.LevelGained += OnLevelGained;
            context.Register(this);
        }

        protected override void OnShutdown()
        {
            if (experience != null)
            {
                experience.LevelGained -= OnLevelGained;
            }
        }

        private void OnLevelGained(int _)
        {
            currentChoices.Clear();
            var candidates = new List<UpgradeDefinition>(upgradePool);
            var count = Mathf.Min(Mathf.Max(1, choiceCount), candidates.Count);
            for (var index = 0; index < count; index++)
            {
                var candidateIndex = UnityEngine.Random.Range(0, candidates.Count);
                currentChoices.Add(
                    new UpgradeChoice
                    {
                        Upgrade = candidates[candidateIndex],
                        Rarity = rarity.Roll(),
                    }
                );
                candidates.RemoveAt(candidateIndex);
            }

            ChoicesPresented?.Invoke(currentChoices);
        }
    }
}
