using System.Collections;
using System.IO;
using NUnit.Framework;
using TeamIdle.GameTemplate.Card;
using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Core;
using TeamIdle.GameTemplate.Platformer;
using TeamIdle.GameTemplate.Prototype;
using TeamIdle.GameTemplate.RaisingSimulation;
using TeamIdle.GameTemplate.SurvivorLike;
using TeamIdle.GameTemplate.VisualNovel;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace TeamIdle.GameTemplate.FeatureTests
{
    /// <summary>
    /// Host-owned acceptance tests. Generated code may satisfy these tests but must never edit them.
    /// A test is ignored when its feature was not requested by the user.
    /// </summary>
    public sealed class FeatureChecklistTests
    {
        private const string ScenePath = "Assets/Scenes/Bootstrap.unity";
        private const string DesignPath = "Assets/GameTemplate/Generated/GameLogicDesign.json";

        [UnitySetUp]
        public IEnumerator SetUp()
        {
            InputAdapterModule.TestInputEnabled = true;
            InputAdapterModule.TestMovement = Vector2.zero;
            InputAdapterModule.TestConfirmPressed = false;
            InputAdapterModule.TestDashPressed = false;
            yield return SceneManager.LoadSceneAsync(ScenePath, LoadSceneMode.Single);
            for (var frame = 0; frame < 10; frame++)
            {
                yield return null;
            }

            Assert.That(GameBootstrap.Instance, Is.Not.Null, "GameBootstrap must exist.");
        }

        [UnityTearDown]
        public IEnumerator TearDown()
        {
            InputAdapterModule.TestInputEnabled = false;
            InputAdapterModule.TestMovement = Vector2.zero;
            InputAdapterModule.TestConfirmPressed = false;
            InputAdapterModule.TestDashPressed = false;
            yield return null;
        }

        [UnityTest]
        [Category("FeatureChecklist")]
        public IEnumerator FC01_EightDirectionAttack()
        {
            RequireFeature("8방향 공격");
            var player = GameObject.Find("Player");
            Assert.That(player, Is.Not.Null, "A controllable Player is required.");
            Assert.That(
                HasInitializedAttackModule(),
                Is.True,
                "An initialized attack module must be bound to the generated game."
            );
            yield return null;
        }

        [UnityTest]
        [Category("FeatureChecklist")]
        public IEnumerator FC02_EightDirectionMovement()
        {
            RequireFeature("8방향 이동", "top_down_movement");
            var player = GameObject.Find("Player");
            var movement = Object.FindFirstObjectByType<TopDownMovementModule>();
            Assert.That(player, Is.Not.Null, "Player must exist.");
            Assert.That(movement, Is.Not.Null, "TopDownMovementModule must exist.");
            var start = player.transform.position;
            InputAdapterModule.TestMovement = new Vector2(1f, 1f).normalized;
            yield return new WaitForSeconds(0.35f);
            var delta = player.transform.position - start;
            Assert.That(delta.x, Is.GreaterThan(0.05f), "Diagonal input must move on X.");
            Assert.That(delta.y, Is.GreaterThan(0.05f), "Diagonal input must move on Y.");
        }

        [UnityTest]
        [Category("FeatureChecklist")]
        public IEnumerator FC03_AutomaticAttack()
        {
            RequireFeature("자동 공격", "auto_target_system");
            var attack = Object.FindFirstObjectByType<AutoTargetSystemModule>();
            Assert.That(attack, Is.Not.Null, "AutoTargetSystemModule must exist.");
            Assert.That(attack.IsInitialized, Is.True, "Automatic attack must be initialized.");
            var before = Object.FindObjectsByType<Projectile2D>(FindObjectsSortMode.None).Length;
            yield return new WaitForSeconds(2f);
            var after = Object.FindObjectsByType<Projectile2D>(FindObjectsSortMode.None).Length;
            Assert.That(after, Is.GreaterThan(before), "Automatic attack must emit a projectile.");
        }

        [UnityTest]
        [Category("FeatureChecklist")]
        public IEnumerator FC04_Attack()
        {
            RequireFeature("공격");
            var damage = Object.FindFirstObjectByType<HealthDamageSystemModule>();
            Assert.That(damage, Is.Not.Null, "HealthDamageSystemModule must exist.");
            var target = new GameObject("FeatureChecklistDamageTarget");
            var health = target.AddComponent<HealthComponent>();
            health.SetMaximum(10f);
            var before = health.Current;
            damage.ApplyDamage(health, 1f);
            yield return null;
            Assert.That(health.Current, Is.LessThan(before), "Attack must reduce target health.");
        }

        [UnityTest]
        [Category("FeatureChecklist")]
        public IEnumerator FC05_Jump()
        {
            RequireFeature("점프", "platformer_movement");
            var movement = Object.FindFirstObjectByType<PlatformerMovementModule>();
            var player = GameObject.Find("Player");
            Assert.That(movement, Is.Not.Null, "PlatformerMovementModule must exist.");
            Assert.That(player, Is.Not.Null, "Player must exist.");
            var body = player.GetComponent<Rigidbody2D>();
            Assert.That(body, Is.Not.Null, "Player must have Rigidbody2D.");
            var groundCheck = player.transform.Find("GroundCheck");
            Assert.That(groundCheck, Is.Not.Null, "Player must have a GroundCheck transform.");
            var testGround = new GameObject("FeatureChecklistJumpGround");
            testGround.transform.position = groundCheck.position + Vector3.down * 0.05f;
            testGround.AddComponent<BoxCollider2D>().size = new Vector2(2f, 0.1f);
            Physics2D.SyncTransforms();
            movement.Bind(body, testGround.transform);
            body.linearVelocity = Vector2.zero;
            InputAdapterModule.TestConfirmPressed = true;
            movement.SendMessage("Update");
            InputAdapterModule.TestConfirmPressed = false;
            movement.SendMessage("FixedUpdate");
            Assert.That(
                body.linearVelocity.y,
                Is.GreaterThan(0.1f),
                "Jump must add upward velocity."
            );
            yield return null;
        }

        [UnityTest]
        [Category("FeatureChecklist")]
        public IEnumerator FC06_Growth()
        {
            RequireFeature("성장", "experience_system", "stat_system");
            var experience = Object.FindFirstObjectByType<ExperienceSystemModule>();
            var stats = Object.FindFirstObjectByType<StatSystemModule>();
            Assert.That(
                experience != null || stats != null,
                Is.True,
                "A growth-capable experience or stat system must exist."
            );
            if (experience != null)
            {
                var before = experience.Level;
                experience.Add(experience.RequiredExperience);
                yield return null;
                Assert.That(
                    experience.Level,
                    Is.GreaterThan(before),
                    "Experience must raise level."
                );
            }
            else
            {
                Assert.That(stats.IsInitialized, Is.True, "Stat system must be initialized.");
            }
        }

        [UnityTest]
        [Category("FeatureChecklist")]
        public IEnumerator FC07_CardDeckConstruction()
        {
            RequireFeature("카드 덱 구성", "deck_system");
            var deck = Object.FindFirstObjectByType<DeckSystemModule>();
            Assert.That(deck, Is.Not.Null, "DeckSystemModule must exist.");
            Assert.That(deck.IsInitialized, Is.True, "Deck must be initialized.");
            Assert.That(deck.Hand.Count, Is.GreaterThan(0), "Starting hand must contain cards.");
            var before = deck.Hand.Count;
            var card = deck.Hand[0];
            Assert.That(deck.Discard(card), Is.True, "A hand card must be discardable.");
            deck.Draw();
            yield return null;
            Assert.That(deck.Hand.Count, Is.EqualTo(before), "Draw must replenish the hand.");
        }

        [UnityTest]
        [Category("FeatureChecklist")]
        public IEnumerator FC08_DialogueChoice()
        {
            RequireFeature("대화 선택", "choice_branch_system");
            var choices = Object.FindFirstObjectByType<ChoiceBranchSystemModule>();
            var flags = Object.FindFirstObjectByType<FlagSystemModule>();
            Assert.That(choices, Is.Not.Null, "ChoiceBranchSystemModule must exist.");
            Assert.That(flags, Is.Not.Null, "FlagSystemModule must exist.");
            var choice = new StoryChoice
            {
                choiceId = "feature-checklist-choice",
                text = "Test choice",
                setFlag = "feature-checklist-selected",
            };
            Assert.That(choices.Select(choice), Is.True, "Available choice must be selectable.");
            yield return null;
            Assert.That(
                flags.Has("feature-checklist-selected"),
                Is.True,
                "Choice must change branch state."
            );
        }

        [UnityTest]
        [Category("FeatureChecklist")]
        public IEnumerator FC09_TowerPlacement()
        {
            RequireFeature("타워 배치", "wave_spawner");
            var builder = Object.FindFirstObjectByType<PrototypeTowerBuildController>();
            Assert.That(builder, Is.Not.Null, "Tower build controller must exist.");
            Assert.That(builder.enabled, Is.True, "Tower build input must be enabled.");
            Assert.That(
                Object.FindObjectsByType<PrototypeTowerBuildSlot>(FindObjectsSortMode.None).Length,
                Is.GreaterThan(0),
                "At least one visible build pad must exist."
            );
            yield return null;
        }

        private static void RequireFeature(string featureName, params string[] moduleIds)
        {
            var path = Path.GetFullPath(DesignPath);
            Assert.That(File.Exists(path), Is.True, $"Generated design is missing: {path}");
            var design = File.ReadAllText(path);
            var requested = design.Contains(featureName);
            if (!requested && GameBootstrap.Instance?.Config != null)
            {
                foreach (var selected in GameBootstrap.Instance.Config.SelectedModules)
                {
                    if (System.Array.IndexOf(moduleIds, selected) >= 0)
                    {
                        requested = true;
                        break;
                    }
                }
            }

            if (!requested)
            {
                Assert.Ignore($"Feature was not requested: {featureName}");
            }
        }

        private static bool HasInitializedAttackModule()
        {
            foreach (
                var module in Object.FindObjectsByType<GameModuleBehaviour>(
                    FindObjectsSortMode.None
                )
            )
            {
                if (
                    module.IsInitialized
                    && module.ModuleId.Contains("attack", System.StringComparison.OrdinalIgnoreCase)
                )
                {
                    return true;
                }
            }

            return false;
        }
    }
}
