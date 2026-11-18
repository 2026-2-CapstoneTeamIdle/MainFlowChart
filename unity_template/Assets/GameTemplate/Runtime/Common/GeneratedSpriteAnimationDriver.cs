using UnityEngine;

namespace TeamIdle.GameTemplate.Common
{
    [RequireComponent(typeof(SpriteRenderer), typeof(Animator))]
    public sealed class GeneratedSpriteAnimationDriver : MonoBehaviour
    {
        private Animator animator;
        private SpriteRenderer spriteRenderer;
        private Vector3 previousPosition;
        private Color previousColor;
        private float hitUntil;
        private string currentState = string.Empty;

        private void Awake()
        {
            animator = GetComponent<Animator>();
            spriteRenderer = GetComponent<SpriteRenderer>();
            previousPosition = transform.position;
            previousColor = spriteRenderer.color;
        }

        public void PlayHit(float duration = 0.25f)
        {
            hitUntil = Mathf.Max(hitUntil, Time.time + duration);
        }

        private void LateUpdate()
        {
            if (animator == null || animator.runtimeAnimatorController == null)
            {
                return;
            }

            var color = spriteRenderer.color;
            if (color != previousColor && color != Color.white)
            {
                PlayHit();
            }

            var movement = transform.position - previousPosition;
            var moving = movement.sqrMagnitude > 0.000001f;
            var locomotion = HasState("walk") ? "walk" : "run";
            var nextState =
                Time.time < hitUntil ? "hit"
                : Mathf.Abs(movement.y) > 0.002f && HasState("jump") ? "jump"
                : moving ? locomotion
                : "idle";
            if (currentState != nextState && HasState(nextState))
            {
                animator.Play(Animator.StringToHash("Base Layer." + nextState), 0, 0f);
                currentState = nextState;
            }

            previousPosition = transform.position;
            previousColor = color;
        }

        private bool HasState(string stateName) =>
            animator.HasState(0, Animator.StringToHash("Base Layer." + stateName));
    }
}
