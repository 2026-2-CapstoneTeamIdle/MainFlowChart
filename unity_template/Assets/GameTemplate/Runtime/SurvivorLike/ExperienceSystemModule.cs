using System;
using TeamIdle.GameTemplate.Core;
using UnityEngine;

namespace TeamIdle.GameTemplate.SurvivorLike
{
    public sealed class ExperienceSystemModule : GameModuleBehaviour
    {
        [SerializeField]
        private int baseRequiredExperience = 10;

        [SerializeField]
        private float requirementGrowth = 1.25f;
        public override string ModuleId => "experience_system";
        public int Level { get; private set; }
        public int Experience { get; private set; }
        public int RequiredExperience { get; private set; }
        public event Action<int> LevelGained;
        public event Action<int, int> ExperienceChanged;

        public void Add(int amount)
        {
            Experience += Mathf.Max(0, amount);
            while (Experience >= RequiredExperience)
            {
                Experience -= RequiredExperience;
                Level++;
                RequiredExperience = Mathf.Max(
                    RequiredExperience + 1,
                    Mathf.RoundToInt(RequiredExperience * requirementGrowth)
                );
                LevelGained?.Invoke(Level);
            }
            ExperienceChanged?.Invoke(Experience, RequiredExperience);
        }

        protected override void OnInitialize(GameContext context)
        {
            Level = 1;
            RequiredExperience = Mathf.Max(1, baseRequiredExperience);
            context.Register(this);
        }
    }
}
