using System.Text;
using TeamIdle.GameTemplate.Core;
using TeamIdle.GameTemplate.SurvivorLike;
using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    public sealed class PlayerStatDisplayModule : GameModuleBehaviour
    {
        [SerializeField]
        private KeyCode toggleKey = KeyCode.E;

        private GameObject panel;
        private UnityEngine.UI.Text statText;
        private HealthComponent playerHealth;
        private EconomySystemModule economy;
        private ItemCollectionSystemModule inventory;
        private ScoreSystemModule score;
        private ExperienceSystemModule experience;

        public override string ModuleId => "player_stat_display";
        public bool IsVisible { get; private set; }
        public string DisplayText => statText != null ? statText.text : string.Empty;

        private void Update()
        {
            if (Input.GetKeyDown(toggleKey))
                Toggle();
            if (IsVisible)
                Refresh();
        }

        public void Toggle()
        {
            SetVisible(!IsVisible);
        }

        public void SetVisible(bool visible)
        {
            IsVisible = visible;
            panel.SetActive(visible);
            if (visible)
                Refresh();
        }

        public void Refresh()
        {
            economy ??= FindFirstObjectByType<EconomySystemModule>();
            inventory ??= FindFirstObjectByType<ItemCollectionSystemModule>();
            score ??= FindFirstObjectByType<ScoreSystemModule>();
            experience ??= FindFirstObjectByType<ExperienceSystemModule>();
            if (playerHealth == null)
            {
                var player = GameObject.Find("Player");
                playerHealth = player != null ? player.GetComponent<HealthComponent>() : null;
            }

            var builder = new StringBuilder("PLAYER STATS (E)\n");
            if (playerHealth != null)
                builder.AppendLine($"HP: {playerHealth.Current:0}/{playerHealth.Maximum:0}");
            if (experience != null)
                builder.AppendLine(
                    $"Level: {experience.Level}  EXP: {experience.Experience}/{experience.RequiredExperience}"
                );
            if (economy != null)
                builder.AppendLine($"Currency: {economy.Currency}");
            if (inventory != null)
                builder.AppendLine($"Items: {inventory.TotalCount}");
            if (score != null)
                builder.AppendLine($"Score: {score.Score}");
            statText.text = builder.ToString().TrimEnd();
        }

        protected override void OnInitialize(GameContext context)
        {
            context.TryGet(out economy);
            context.TryGet(out inventory);
            context.TryGet(out score);
            context.TryGet(out experience);
            var root = RuntimeFeatureUi.CreatePanel(
                "PlayerStatPanel",
                new Vector2(0.02f, 0.55f),
                new Vector2(0.32f, 0.96f),
                new Color(0.03f, 0.05f, 0.09f, 0.92f)
            );
            panel = root.gameObject;
            statText = RuntimeFeatureUi.CreateText(
                "Stats",
                root,
                string.Empty,
                22,
                Vector2.zero,
                Vector2.one
            );
            SetVisible(false);
            context.Register(this);
        }

        protected override void OnShutdown()
        {
            if (panel != null)
                Destroy(panel);
        }
    }
}
