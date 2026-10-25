using TeamIdle.GameTemplate.TowerDefense;
using UnityEngine;

namespace TeamIdle.GameTemplate.Prototype
{
    public sealed class PrototypeTowerEndpoint : MonoBehaviour
    {
        private PathFollower2D follower;

        private void Awake()
        {
            follower = GetComponent<PathFollower2D>();
            if (follower != null)
            {
                follower.ReachedEnd += ReachEnd;
            }
        }

        private void OnDestroy()
        {
            if (follower != null)
            {
                follower.ReachedEnd -= ReachEnd;
            }
        }

        private void ReachEnd()
        {
            FindFirstObjectByType<BaseDefenseSystemModule>()?.LoseLives();
            Destroy(gameObject);
        }
    }
}
