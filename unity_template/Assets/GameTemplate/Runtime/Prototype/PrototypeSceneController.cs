using System.Collections.Generic;
using TeamIdle.GameTemplate.Card;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Platformer;
using TeamIdle.GameTemplate.RaisingSimulation;
using TeamIdle.GameTemplate.SurvivorLike;
using TeamIdle.GameTemplate.TowerDefense;
using TeamIdle.GameTemplate.VisualNovel;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeSceneController : MonoBehaviour
    {
        [SerializeField]
        private string gameTitle = "Generated 2D Game";

        [SerializeField]
        private string genre = "Unassigned";

        private GUIStyle titleStyle;
        private Vector2 scrollPosition;
        private bool suppressLegacyHud;

        public void Configure(string nextTitle, string nextGenre)
        {
            gameTitle = nextTitle;
            genre = nextGenre;
        }

        private void Start()
        {
            suppressLegacyHud =
                genre == "Platformer"
                && FindFirstObjectByType<PrototypePresentationController>() != null;
            if (genre == "VisualNovel")
            {
                FindFirstObjectByType<DialogueRunnerModule>()?.Next();
            }
        }

        private void OnGUI()
        {
            if (suppressLegacyHud)
            {
                return;
            }

            titleStyle ??= new GUIStyle(GUI.skin.label)
            {
                fontSize = 20,
                fontStyle = FontStyle.Bold,
            };

            GUILayout.BeginArea(new Rect(16f, 16f, 390f, Screen.height - 32f), GUI.skin.box);
            scrollPosition = GUILayout.BeginScrollView(scrollPosition);
            GUILayout.Label(gameTitle, titleStyle);
            GUILayout.Label($"Prototype profile: {genre}");
            GUILayout.Space(8f);

            switch (genre)
            {
                case "Platformer":
                    DrawPlatformer();
                    break;
                case "TowerDefense":
                    DrawTowerDefense();
                    break;
                case "CardGame":
                    DrawCardGame();
                    break;
                case "VisualNovel":
                    DrawVisualNovel();
                    break;
                case "RaisingSimulation":
                    DrawRaisingSimulation();
                    break;
                case "SurvivorLike":
                    DrawSurvivorLike();
                    break;
                default:
                    GUILayout.Label("No genre-specific scene profile was selected.");
                    break;
            }

            GUILayout.Space(12f);
            GUILayout.Label("Placeholder visuals are replaced by validated assets later.");
            GUILayout.EndScrollView();
            GUILayout.EndArea();
        }

        private static void DrawPlatformer()
        {
            GUILayout.Label("Move: A/D or arrow keys    Jump: Space");
            var collectibles = FindFirstObjectByType<CollectibleSystemModule>();
            var goal = FindFirstObjectByType<GoalSystemModule>();
            if (collectibles != null)
            {
                GUILayout.Label(
                    $"Collectibles: {collectibles.CollectedCount} / "
                        + $"{collectibles.RequiredCount}, score: {collectibles.Score} / "
                        + $"{collectibles.RequiredScore} "
                        + (collectibles.RequirementMet ? "ready" : "required")
                );
            }

            if (goal != null)
            {
                GUILayout.Label(goal.IsCompleted ? "Stage complete" : "Reach the green goal");
            }
        }

        private static void DrawTowerDefense()
        {
            var waves = FindFirstObjectByType<WaveSpawnerModule>();
            var defense = FindFirstObjectByType<BaseDefenseSystemModule>();
            var economy = FindFirstObjectByType<EconomySystemModule>();
            var build = FindFirstObjectByType<PrototypeTowerBuildController>();
            GUILayout.Label("HOW TO PLAY", GUI.skin.box);
            GUILayout.Label("1. Click a yellow build pad to place an attack tower.");
            GUILayout.Label("2. Towers fire automatically at enemies on the path.");
            GUILayout.Label("3. Stop enemies before they reach the green base.");
            GUILayout.Label(
                "The first wave starts automatically. Press Space/Enter for the next wave."
            );
            GUILayout.Label(
                $"Gold: {economy?.Currency ?? 0}    Tower cost: {build?.BuildCost ?? 0}"
            );
            GUILayout.Label($"Built towers: {build?.BuiltTowerCount ?? 0}");
            GUILayout.Label($"Wave: {waves?.WaveNumber ?? 0}");
            GUILayout.Label(
                waves?.IsWaveRunning == true ? "Wave in progress" : "Ready for next wave"
            );
            GUILayout.Label($"Base lives: {defense?.Lives ?? 0}");
            var keyboardStart =
                Event.current.type == EventType.KeyDown
                && (
                    Event.current.keyCode == KeyCode.Space
                    || Event.current.keyCode == KeyCode.Return
                );
            if (waves != null && (GUILayout.Button("Start next wave") || keyboardStart))
            {
                waves.StartNextWave();
                if (keyboardStart)
                {
                    Event.current.Use();
                }
            }
        }

        private static void DrawCardGame()
        {
            var deck = FindFirstObjectByType<DeckSystemModule>();
            var effects = FindFirstObjectByType<CardEffectSystemModule>();
            var resources = FindFirstObjectByType<CardResourceSystemModule>();
            var turns = FindFirstObjectByType<TurnSystemModule>();
            GUILayout.Label($"Turn: {turns?.TurnNumber ?? 0} / {turns?.CurrentOwner}");
            GUILayout.Label($"Resource: {resources?.Current ?? 0}");
            GUILayout.Label("Hand");
            if (deck != null && effects != null)
            {
                var hand = new List<CardData>(deck.Hand);
                foreach (var card in hand)
                {
                    if (
                        GUILayout.Button(
                            $"{card.displayName}  cost {card.cost} / power {card.power}"
                        )
                    )
                    {
                        effects.Play(card, _ => { });
                    }
                }
            }

            if (turns != null && GUILayout.Button("End turn"))
            {
                turns.EndTurn();
                if (turns.CurrentOwner == TurnSystemModule.TurnOwner.Player)
                {
                    resources?.Refill();
                    deck?.Draw();
                }
            }
        }

        private static void DrawVisualNovel()
        {
            var dialogue = FindFirstObjectByType<DialogueRunnerModule>();
            var choices = FindFirstObjectByType<ChoiceBranchSystemModule>();
            if (dialogue?.Current != null)
            {
                GUILayout.Label(dialogue.Current.speaker, GUI.skin.box);
                GUILayout.Label(dialogue.Current.text, GUILayout.MinHeight(70f));
            }
            else
            {
                GUILayout.Label("Dialogue complete");
            }

            if (dialogue != null && GUILayout.Button("Continue"))
            {
                dialogue.Next();
            }

            if (choices != null)
            {
                GUILayout.Label("Choice preview");
                if (GUILayout.Button("Trust the character"))
                {
                    choices.Select(
                        new StoryChoice
                        {
                            choiceId = "trust",
                            text = "Trust the character",
                            setFlag = "trusted",
                        }
                    );
                }
            }
        }

        private static void DrawRaisingSimulation()
        {
            var stats = FindFirstObjectByType<StatSystemModule>();
            var time = FindFirstObjectByType<TimeTurnSystemModule>();
            var activities = FindFirstObjectByType<ActivitySystemModule>();
            GUILayout.Label($"Day {time?.Day ?? 0} / turn {time?.TurnInDay ?? 0}");
            GUILayout.Label($"Knowledge: {stats?.Get("knowledge") ?? 0}");
            GUILayout.Label($"Fitness: {stats?.Get("fitness") ?? 0}");
            GUILayout.Label($"Fatigue: {stats?.Get("fatigue") ?? 0}");
            if (activities != null && GUILayout.Button("Study"))
            {
                activities.Execute(CreateActivity("study", "knowledge", 8, "fatigue", 3));
            }

            if (activities != null && GUILayout.Button("Exercise"))
            {
                activities.Execute(CreateActivity("exercise", "fitness", 8, "fatigue", 4));
            }

            if (activities != null && GUILayout.Button("Rest"))
            {
                activities.Execute(CreateActivity("rest", "fatigue", -10));
            }
        }

        private static ActivityDefinition CreateActivity(
            string id,
            string firstStat,
            int firstAmount,
            string secondStat = null,
            int secondAmount = 0
        )
        {
            var activity = new ActivityDefinition { activityId = id, turnCost = 1 };
            activity.changes.Add(
                new ActivityDefinition.StatChange { statId = firstStat, amount = firstAmount }
            );
            if (!string.IsNullOrWhiteSpace(secondStat))
            {
                activity.changes.Add(
                    new ActivityDefinition.StatChange { statId = secondStat, amount = secondAmount }
                );
            }

            return activity;
        }

        private static void DrawSurvivorLike()
        {
            GUILayout.Label("Move: WASD or arrow keys");
            GUILayout.Label("Enemies spawn around you and chase automatically.");
            GUILayout.Label("Your wing projectiles automatically attack the nearest enemy.");
            var experience = FindFirstObjectByType<ExperienceSystemModule>();
            var upgrades = FindFirstObjectByType<UpgradeSelectionSystemModule>();
            GUILayout.Label(
                $"Level {experience?.Level ?? 0}    XP {experience?.Experience ?? 0} / "
                    + $"{experience?.RequiredExperience ?? 0}"
            );
            if (experience != null && GUILayout.Button("Add test XP"))
            {
                experience.Add(5);
            }

            if (upgrades != null && upgrades.CurrentChoices.Count > 0)
            {
                GUILayout.Label("Choose a wing upgrade");
                for (var index = 0; index < upgrades.CurrentChoices.Count; index++)
                {
                    var choice = upgrades.CurrentChoices[index];
                    if (
                        GUILayout.Button(
                            $"[{choice.Rarity}] {choice.Upgrade.displayName}: "
                                + choice.Upgrade.description
                        )
                    )
                    {
                        upgrades.Select(index);
                        break;
                    }
                }
            }
        }
    }

#if false // Moved to PrototypeWingUpgradeApplier.cs for a stable Unity script reference.
    public sealed class PrototypeWingUpgradeApplier : MonoBehaviour
    {
        private UpgradeSelectionSystemModule upgrades;
        private TopDownMovementModule movement;
        private AutoTargetSystemModule autoTarget;

        private void Start()
        {
            upgrades = FindFirstObjectByType<UpgradeSelectionSystemModule>();
            movement = FindFirstObjectByType<TopDownMovementModule>();
            autoTarget = FindFirstObjectByType<AutoTargetSystemModule>();
            if (upgrades != null)
            {
                upgrades.Selected += Apply;
            }
        }

        private void OnDestroy()
        {
            if (upgrades != null)
            {
                upgrades.Selected -= Apply;
            }
        }

        private void Apply(UpgradeSelectionSystemModule.UpgradeChoice choice)
        {
            if (choice?.Upgrade == null)
            {
                return;
            }

            var multiplier = choice.Rarity switch
            {
                UpgradeRarity.Rare => 1.5f,
                UpgradeRarity.Epic => 2f,
                UpgradeRarity.Legendary => 3f,
                _ => 1f,
            };
            switch (choice.Upgrade.upgradeId)
            {
                case "wing-power" when autoTarget != null:
                    autoTarget.Damage += 5f * multiplier;
                    break;
                case "wing-speed" when movement != null:
                    movement.MoveSpeed += 0.5f * multiplier;
                    break;
                case "attack-speed" when autoTarget != null:
                    autoTarget.AttacksPerSecond += 0.2f * multiplier;
                    break;
                case "feather-count" when autoTarget != null:
                    autoTarget.ProjectileCount += Mathf.Max(1, Mathf.RoundToInt(multiplier));
                    break;
            }
        }
    }
#endif
}
