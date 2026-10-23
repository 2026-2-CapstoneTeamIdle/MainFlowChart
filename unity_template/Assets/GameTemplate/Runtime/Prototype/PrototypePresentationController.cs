using TeamIdle.GameTemplate.Common;
using TeamIdle.GameTemplate.Platformer;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypePresentationController : MonoBehaviour
    {
        [SerializeField]
        private HealthComponent playerHealth;

        [SerializeField]
        private CollectibleSystemModule collectibles;

        [SerializeField]
        private GoalSystemModule goal;

        [SerializeField]
        private PrototypePlatformerStageController stage;

        [SerializeField]
        private PrototypeCameraFollow cameraFollow;

        [SerializeField]
        private UnityEngine.UI.Text healthText;

        [SerializeField]
        private UnityEngine.UI.Text collectibleText;

        [SerializeField]
        private UnityEngine.UI.Text statusText;

        [SerializeField]
        private UnityEngine.UI.Image damageFlash;

        [SerializeField]
        private ParticleSystem feedbackParticles;

        [SerializeField]
        private bool showHitFeedback = true;

        [SerializeField]
        private bool showCollectibleFeedback = true;

        [SerializeField]
        private bool showCheckpointFeedback = true;

        [SerializeField]
        private bool useCameraShake = true;

        private float flashAlpha;
        private float statusVisibleUntil;
        private float previousHealth;
        private float bindingStartedAt;
        private bool initialized;

        public bool IsBound =>
            playerHealth != null
            && collectibles != null
            && goal != null
            && stage != null
            && healthText != null
            && collectibleText != null
            && statusText != null
            && damageFlash != null;

        public bool IsInitialized => initialized;

        public string BindingStatus =>
            $"health={playerHealth != null},collectibles={collectibles != null},"
            + $"goal={goal != null},stage={stage != null},camera={cameraFollow != null},"
            + $"healthText={healthText != null},collectibleText={collectibleText != null},"
            + $"statusText={statusText != null},damageFlash={damageFlash != null}";

        public void Bind(
            HealthComponent nextPlayerHealth,
            CollectibleSystemModule nextCollectibles,
            GoalSystemModule nextGoal,
            PrototypePlatformerStageController nextStage,
            PrototypeCameraFollow nextCameraFollow,
            UnityEngine.UI.Text nextHealthText,
            UnityEngine.UI.Text nextCollectibleText,
            UnityEngine.UI.Text nextStatusText,
            UnityEngine.UI.Image nextDamageFlash,
            ParticleSystem nextFeedbackParticles
        )
        {
            playerHealth = nextPlayerHealth;
            collectibles = nextCollectibles;
            goal = nextGoal;
            stage = nextStage;
            cameraFollow = nextCameraFollow;
            healthText = nextHealthText;
            collectibleText = nextCollectibleText;
            statusText = nextStatusText;
            damageFlash = nextDamageFlash;
            feedbackParticles = nextFeedbackParticles;
        }

        public void Configure(
            bool hitFeedback,
            bool collectibleFeedback,
            bool checkpointFeedback,
            bool cameraShake
        )
        {
            showHitFeedback = hitFeedback;
            showCollectibleFeedback = collectibleFeedback;
            showCheckpointFeedback = checkpointFeedback;
            useCameraShake = cameraShake;
        }

        private void Start()
        {
            bindingStartedAt = Time.unscaledTime;
            TryInitialize();
        }

        private bool TryInitialize()
        {
            if (initialized)
            {
                return true;
            }

            ResolveRuntimeBindings();
            if (!IsBound)
            {
                return false;
            }

            initialized = true;
            previousHealth = playerHealth.Current;
            playerHealth.Changed += OnHealthChanged;
            collectibles.Collected += OnCollected;
            goal.Completed += OnGoalCompleted;
            stage.CheckpointActivated += OnCheckpointActivated;
            RefreshHud();
            ShowStatus("Reach the goal", 2.5f);
            return true;
        }

        private void ResolveRuntimeBindings()
        {
            playerHealth ??= FindLoadedObject<HealthComponent>();
            goal ??= FindLoadedObject<GoalSystemModule>();
            collectibles ??= goal == null ? null : goal.Collectibles;
            collectibles ??= FindLoadedObject<CollectibleSystemModule>();
            stage ??= FindLoadedObject<PrototypePlatformerStageController>();
            cameraFollow ??= FindLoadedObject<PrototypeCameraFollow>();
        }

        private static T FindLoadedObject<T>()
            where T : UnityEngine.Object
        {
            foreach (var candidate in Resources.FindObjectsOfTypeAll<T>())
            {
                if (candidate != null && candidate.hideFlags == HideFlags.None)
                {
                    return candidate;
                }
            }

            return null;
        }

        private void Update()
        {
            if (!TryInitialize())
            {
                if (Time.unscaledTime - bindingStartedAt >= 2f)
                {
                    Debug.LogError(
                        $"Presentation controller is missing required runtime bindings: {BindingStatus}"
                    );
                    enabled = false;
                }
                return;
            }

            flashAlpha = Mathf.MoveTowards(flashAlpha, 0f, Time.unscaledDeltaTime * 2.5f);
            var color = damageFlash.color;
            color.a = flashAlpha;
            damageFlash.color = color;
            if (statusText.enabled && Time.unscaledTime >= statusVisibleUntil)
            {
                statusText.enabled = false;
            }
        }

        private void OnDestroy()
        {
            if (playerHealth != null)
            {
                playerHealth.Changed -= OnHealthChanged;
            }
            if (collectibles != null)
            {
                collectibles.Collected -= OnCollected;
            }
            if (goal != null)
            {
                goal.Completed -= OnGoalCompleted;
            }
            if (stage != null)
            {
                stage.CheckpointActivated -= OnCheckpointActivated;
            }
        }

        private void OnHealthChanged(float current, float maximum)
        {
            if (showHitFeedback && current < previousHealth)
            {
                flashAlpha = 0.42f;
                ShowStatus("Hit!", 0.8f);
                EmitFeedback(new Color(1f, 0.2f, 0.2f));
                if (useCameraShake)
                {
                    cameraFollow?.Shake(0.18f, 0.2f);
                }
            }

            previousHealth = current;
            RefreshHud();
        }

        private void OnCollected(int current, int required)
        {
            if (showCollectibleFeedback)
            {
                ShowStatus($"Collected {current}/{required}", 1.2f);
                EmitFeedback(new Color(1f, 0.82f, 0.2f));
            }

            RefreshHud();
        }

        private void OnCheckpointActivated(int index, Vector3 position)
        {
            if (!showCheckpointFeedback)
            {
                return;
            }

            ShowStatus($"Checkpoint {index}", 1.8f);
            EmitFeedback(new Color(0.25f, 0.9f, 0.95f));
        }

        private void OnGoalCompleted()
        {
            ShowStatus("STAGE CLEAR", 10f);
            EmitFeedback(new Color(0.2f, 1f, 0.45f), 28);
        }

        private void RefreshHud()
        {
            healthText.text =
                $"HP  {Mathf.CeilToInt(playerHealth.Current)} / "
                + Mathf.CeilToInt(playerHealth.Maximum);
            collectibleText.text =
                $"ITEM  {collectibles.CollectedCount} / {collectibles.RequiredCount}    "
                + $"SCORE  {collectibles.Score} / {collectibles.RequiredScore}"
                + (collectibles.RequirementMet ? "  READY" : string.Empty);
        }

        private void ShowStatus(string message, float duration)
        {
            statusText.text = message;
            statusText.enabled = true;
            statusVisibleUntil = Time.unscaledTime + duration;
        }

        private void EmitFeedback(Color color, int count = 14)
        {
            if (feedbackParticles == null || playerHealth == null)
            {
                return;
            }

            feedbackParticles.transform.position = playerHealth.transform.position;
            var main = feedbackParticles.main;
            main.startColor = color;
            feedbackParticles.Emit(count);
        }
    }
}
